"""
Stream-Driven Strategy Worker — event-driven replacement for the 60s APScheduler polling.

Each active strategy runs as a persistent asyncio task that:
  1. Reads trade/quote events from its StreamRouter queue
  2. Accumulates state (price, volume, bid/ask, session high/low)
  3. Refreshes option greeks from REST every 5 minutes
  4. Fires the StrategyExecutor on every underlying trade tick
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from database import SessionLocals
from config import Environment
from models import User, Strategy, Position
from engine.strategy_executor import StrategyExecutor
from engine.stream_router import get_stream_router
from engine.tradier_stream_manager import get_stream_manager
from engine.event_logger import log_event
from utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

_GREEKS_REFRESH_INTERVAL = timedelta(minutes=5)
_MARKET_CLOSED_LOG_INTERVAL = timedelta(minutes=1)


@dataclass
class StrategyMarketState:
    """
    Accumulates stream events for one strategy into a coherent market_data snapshot.
    Tracks underlying separately from the option contract so EMA/VWAP use the
    right price series.
    """
    underlying_symbol: str
    option_symbol: Optional[str] = None

    # Underlying tracking (for EMA, VWAP, volume spike)
    underlying_price: float = 0.0
    tick_volume: int = 0       # size of the most recent individual trade
    cum_volume: int = 0        # cumulative intraday volume from cvol field
    session_high: float = 0.0
    session_low: float = 0.0

    # Option contract pricing (for bid/ask spread check and option price)
    option_bid: float = 0.0
    option_ask: float = 0.0
    option_last: float = 0.0

    # Greeks — populated by periodic REST refresh
    delta: Optional[float] = None
    open_interest: Optional[int] = None
    greeks_last_fetched: Optional[datetime] = None

    def apply(self, event: dict):
        symbol = event.get("symbol", "")
        etype = event.get("type", "")

        if etype in ("trade", "tradex"):
            price = float(event.get("price") or event.get("last") or 0)
            size = int(event.get("size") or 0)
            cvol_raw = event.get("cvol")

            if symbol == self.underlying_symbol and price > 0:
                self.underlying_price = price
                self.tick_volume = size
                self.cum_volume = int(cvol_raw) if cvol_raw else self.cum_volume + size

                if not self.session_high:
                    self.session_high = price
                    self.session_low = price
                else:
                    self.session_high = max(self.session_high, price)
                    self.session_low = min(self.session_low, price)

            elif symbol == self.option_symbol and price > 0:
                self.option_last = price

        elif etype == "quote":
            bid = float(event.get("bid") or 0)
            ask = float(event.get("ask") or 0)
            if symbol == self.option_symbol:
                self.option_bid = bid
                self.option_ask = ask

    def needs_greeks_refresh(self) -> bool:
        if self.greeks_last_fetched is None:
            return True
        return datetime.utcnow() - self.greeks_last_fetched > _GREEKS_REFRESH_INTERVAL

    def to_market_data(self) -> dict:
        return {
            "symbol": self.underlying_symbol,
            "option_symbol": self.option_symbol,   # OCC symbol needed for order placement
            "price": self.underlying_price,
            "volume": self.tick_volume,
            "bid": self.option_bid,
            "ask": self.option_ask,
            "delta": self.delta,
            "open_interest": self.open_interest,
            "high": self.session_high,
            "low": self.session_low,
        }


class StreamDrivenWorker:
    """
    Manages one persistent asyncio task per active strategy.
    Tasks are started at app startup for already-active strategies,
    and can be added/removed dynamically as strategies are toggled.
    """

    MAX_CONCURRENT = 10

    def __init__(self):
        self._tasks: dict[int, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        self._running = False

    async def start(self):
        self._running = True
        try:
            db = SessionLocals[Environment.DEV]()
            try:
                active = db.query(Strategy).filter(Strategy.is_active == True).all()
                for strategy in active:
                    await self.start_strategy(strategy.id)
                logger.info(f"StreamDrivenWorker started — {len(active)} active strategies")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Could not load active strategies at startup (DB may be unavailable): {e}")

    async def stop(self):
        self._running = False
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("StreamDrivenWorker stopped")

    async def start_strategy(self, strategy_id: int):
        if strategy_id in self._tasks:
            return
        task = asyncio.create_task(
            self._run_strategy(strategy_id),
            name=f"strategy-{strategy_id}",
        )
        self._tasks[strategy_id] = task
        task.add_done_callback(lambda t: self._on_task_done(strategy_id, t))
        logger.info(f"Stream task started for strategy {strategy_id}")

    def _on_task_done(self, strategy_id: int, task: asyncio.Task):
        self._tasks.pop(strategy_id, None)
        if self._running and not task.cancelled():
            logger.warning(f"Strategy {strategy_id} task exited unexpectedly — scheduling restart")
            asyncio.create_task(self._auto_restart(strategy_id))

    async def _auto_restart(self, strategy_id: int):
        await asyncio.sleep(5)
        db = SessionLocals[Environment.DEV]()
        try:
            strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if strategy and strategy.is_active:
                logger.info(f"Auto-restarting task for strategy {strategy_id}")
                await self.start_strategy(strategy_id)
        except Exception as e:
            logger.error(f"Auto-restart failed for strategy {strategy_id}: {e}")
        finally:
            db.close()

    async def stop_strategy(self, strategy_id: int):
        task = self._tasks.pop(strategy_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_strategy(self, strategy_id: int):
        async with self._semaphore:
            db = SessionLocals[Environment.DEV]()
            try:
                strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
                if not strategy:
                    return
                user = db.query(User).filter(User.id == strategy.user_id).first()
                if not user:
                    return

                instruments = strategy.instruments or []
                if not instruments:
                    return

                underlying = instruments[0]
                state = StrategyMarketState(underlying_symbol=underlying)

                # Sync DB position against Tradier before doing anything else.
                # This reconciles cases where the app was restarted mid-trade or
                # the position was manually opened/closed in the broker UI.
                await self._startup_sync(strategy_id, underlying, state, db)

                # state.option_symbol is now set by _startup_sync if a position
                # exists in Tradier; otherwise select the best available contract.
                if not state.option_symbol:
                    state.option_symbol = await self._select_option_contract(strategy, underlying)

                symbols_to_stream = [underlying]
                if state.option_symbol:
                    symbols_to_stream.append(state.option_symbol)

                router = get_stream_router()
                stream_mgr = get_stream_manager()

                q = router.register_strategy(strategy_id, symbols_to_stream)
                await stream_mgr.subscribe(symbols_to_stream)

                executor = StrategyExecutor(db)
                strategy_refreshed_at = datetime.utcnow()
                contract_retry_at: Optional[datetime] = None  # throttle failed contract-selection retries
                last_market_closed_log: Optional[datetime] = None

                try:
                    while self._running and strategy.is_active:
                        try:
                            event = await asyncio.wait_for(q.get(), timeout=60)
                        except asyncio.TimeoutError:
                            db.refresh(strategy)
                            db.refresh(user)
                            strategy_refreshed_at = datetime.utcnow()
                            # On every 60s heartbeat, reconcile our DB position
                            # against what Tradier actually holds.  If the position
                            # was closed externally (manual close in the broker UI)
                            # zero it out here so we stop hunting for an exit.
                            await self._reconcile_position(strategy_id, state, db)
                            continue

                        # Drop tick entirely if market is closed — prevents stale
                        # stream events or reconnect bursts from placing orders
                        if not is_market_open():
                            now = datetime.utcnow()
                            if last_market_closed_log is None or now - last_market_closed_log >= _MARKET_CLOSED_LOG_INTERVAL:
                                logger.info(f"Strategy {strategy_id}: market closed, waiting")
                                last_market_closed_log = now
                            continue

                        state.apply(event)

                        # Fire signal check on every underlying trade tick with valid price
                        if (
                            event.get("type") in ("trade", "tradex")
                            and event.get("symbol") == underlying
                            and state.underlying_price > 0
                        ):
                            # Refresh strategy params from DB every 30s so UI edits
                            # (e.g. TP/SL changes) take effect without a server restart
                            if (datetime.utcnow() - strategy_refreshed_at).total_seconds() >= 30:
                                db.refresh(strategy)
                                strategy_refreshed_at = datetime.utcnow()

                            if state.needs_greeks_refresh():
                                await self._refresh_greeks(state)

                            # Re-read position state from DB on every tick.
                            # This is the single source of truth — once a position
                            # is open we ONLY look for exits; once it's gone we
                            # look for a new entry.
                            open_pos = db.query(Position).filter(
                                Position.strategy_id == strategy_id,
                                Position.qty > 0,
                            ).first()

                            if open_pos:
                                result = await executor.execute_exit_tick(
                                    user, strategy, state.to_market_data()
                                )
                                # If the position was just closed, clear the contract
                                # and reset option bid/ask so stale quotes from the old
                                # contract don't pollute the next entry's sizing/P&L calc
                                if result and result.get('positions_closed'):
                                    state.option_symbol = None
                                    state.option_bid = 0.0
                                    state.option_ask = 0.0
                            else:
                                # No position open — select a contract if we don't
                                # have one yet (happens once after exit or on cold start)
                                if not state.option_symbol:
                                    now = datetime.utcnow()
                                    # Only retry contract selection every 30s to avoid
                                    # hammering the options chain API on every tick when
                                    # no suitable contract is available yet
                                    if contract_retry_at is None or now >= contract_retry_at:
                                        state.option_symbol = await self._select_option_contract(
                                            strategy, underlying
                                        )
                                        contract_retry_at = now + timedelta(seconds=30)
                                        if state.option_symbol:
                                            # Reset stale quotes from previous contract
                                            state.option_bid = 0.0
                                            state.option_ask = 0.0
                                            await stream_mgr.subscribe([state.option_symbol])
                                            router.add_symbol_to_strategy(strategy_id, state.option_symbol)

                                await executor.execute_strategy_tick(
                                    user, strategy, state.to_market_data()
                                )

                finally:
                    router.unregister_strategy(strategy_id, symbols_to_stream)
                    await stream_mgr.unsubscribe(symbols_to_stream)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Strategy {strategy_id} task error: {e}", exc_info=True)
            finally:
                db.close()

    async def _startup_sync(
        self,
        strategy_id: int,
        underlying: str,
        state: "StrategyMarketState",
        db,
    ):
        """
        On startup, call Tradier to find the actual open option position for this
        underlying and sync the DB accordingly.

        Three outcomes:
          A) Tradier has a position, DB matches  → set state.option_symbol, done
          B) Tradier has a position, DB is stale → update DB qty/option_symbol/price
          C) Tradier has no position, DB shows one → zero out DB (was manually closed)
        """
        try:
            from tradier_integration.client import get_tradier_client
            client = get_tradier_client()
            tradier_positions = await asyncio.to_thread(client.get_positions)

            # Find any option contract for our underlying held in Tradier
            # OCC symbols start with the underlying ticker
            held = [
                p for p in tradier_positions
                if str(p.get("symbol", "")).startswith(underlying)
                and str(p.get("symbol", "")) != underlying  # exclude stock itself
                and float(p.get("quantity", 0)) > 0
            ]

            db_pos = db.query(Position).filter(
                Position.strategy_id == strategy_id,
            ).first()

            if held:
                tradier_pos = held[0]
                occ_symbol = tradier_pos["symbol"]
                qty = int(float(tradier_pos.get("quantity", 1)))
                cost_basis = float(tradier_pos.get("cost_basis", 0))
                entry_price = cost_basis / (qty * 100) if qty > 0 else 0.0

                if db_pos:
                    db_pos.qty = qty
                    db_pos.option_symbol = occ_symbol
                    if entry_price > 0:
                        db_pos.avg_entry_price = entry_price
                else:
                    # No DB record at all — log and skip; position will be created
                    # properly when the next entry fires through our normal flow
                    logger.warning(
                        f"Strategy {strategy_id}: Tradier has {occ_symbol} but no DB "
                        "position record exists — cannot resume automatically"
                    )
                    state.option_symbol = occ_symbol
                    return

                db.commit()
                state.option_symbol = occ_symbol
                logger.info(
                    f"Strategy {strategy_id}: synced from Tradier — "
                    f"{occ_symbol} qty={qty} entry=${entry_price:.2f}"
                )

            else:
                # No position in Tradier — zero out DB if stale
                if db_pos and db_pos.qty > 0:
                    logger.info(
                        f"Strategy {strategy_id}: DB shows open position but "
                        "Tradier has none — clearing (was manually closed)"
                    )
                    db_pos.qty = 0
                    db_pos.unrealized_pnl = 0.0
                    db.commit()

        except Exception as e:
            logger.warning(f"Startup Tradier sync failed for strategy {strategy_id}: {e}")

    async def _reconcile_position(
        self,
        strategy_id: int,
        state: "StrategyMarketState",
        db,
    ):
        """
        Compare DB open position against Tradier actual holdings.
        If the DB shows a position but Tradier no longer holds it,
        the position was closed externally (manual close in broker UI).
        We zero out the DB record and emit a POSITION_MANUALLY_CLOSED event.
        """
        position = db.query(Position).filter(
            Position.strategy_id == strategy_id,
            Position.qty > 0,
        ).first()

        if not position:
            return  # nothing open in DB, nothing to reconcile

        contract = state.option_symbol or position.option_symbol
        if not contract:
            return  # can't identify the contract

        try:
            from tradier_integration.client import get_tradier_client
            client = get_tradier_client()
            tradier_positions = await asyncio.to_thread(client.get_positions)
            held_symbols = {p.get("symbol") for p in tradier_positions}

            if contract not in held_symbols:
                logger.warning(
                    f"Strategy {strategy_id}: {contract} not found in Tradier — "
                    "position was manually closed externally"
                )
                position.qty = 0
                position.unrealized_pnl = 0.0
                db.commit()

                log_event(
                    db=db,
                    user_id=position.user_id,
                    event_type="POSITION_MANUALLY_CLOSED",
                    title=f"Position closed manually: {contract}",
                    symbol=position.symbol,
                    strategy_id=strategy_id,
                    severity="warning",
                    event_data={"option_symbol": contract},
                )

                # Clear so next entry picks a fresh contract
                state.option_symbol = None

        except Exception as e:
            logger.warning(f"Position reconciliation failed for strategy {strategy_id}: {e}")

    async def _select_option_contract(
        self, strategy: Strategy, underlying: str
    ) -> Optional[str]:
        """Select best 0DTE option contract via Tradier options chain API."""
        try:
            from datetime import date
            from tradier_integration.client import get_tradier_client

            client = get_tradier_client()
            params = strategy.params_json
            delta_min = params.get("delta_min", 0.40)
            delta_max = params.get("delta_max", 0.90)
            min_oi = params.get("min_open_interest", 0)
            max_spread_pct = params.get("max_bid_ask_spread", 0.50)

            today_str = date.today().isoformat()

            # Confirm today has a valid expiry; fall back to nearest if not
            expirations = await asyncio.to_thread(client.get_option_expirations, underlying)
            if today_str not in expirations:
                future = [e for e in expirations if e >= today_str]
                if not future:
                    logger.warning(f"No upcoming expirations found for {underlying}")
                    return None
                expiry = future[0]
                logger.info(f"No 0DTE for {underlying} today, using nearest: {expiry}")
            else:
                expiry = today_str

            chain = await asyncio.to_thread(client.get_option_chain, underlying, expiry, True)
            if not chain:
                logger.warning(f"Empty option chain for {underlying} {expiry}")
                return None

            # Filter calls within delta range with sufficient liquidity
            candidates = []
            rejected_delta = 0
            rejected_oi = 0
            rejected_no_ask = 0
            rejected_spread = 0
            calls_seen = 0

            for contract in chain:
                if contract.get("option_type", "").lower() != "call":
                    continue
                calls_seen += 1
                sym = contract.get("symbol", "?")
                strike = contract.get("strike", "?")

                greeks = contract.get("greeks") or {}
                delta = greeks.get("delta")
                if delta is None:
                    rejected_delta += 1
                    continue
                delta = abs(float(delta))
                if not (delta_min <= delta <= delta_max):
                    rejected_delta += 1
                    continue

                oi = contract.get("open_interest", 0) or 0
                if oi < min_oi:
                    rejected_oi += 1
                    continue

                bid = float(contract.get("bid") or 0)
                ask = float(contract.get("ask") or 0)
                if ask <= 0:
                    rejected_no_ask += 1
                    continue
                spread_pct = (ask - bid) / ask
                if spread_pct > max_spread_pct:
                    rejected_spread += 1
                    logger.debug(
                        f"  {sym} strike={strike} delta={delta:.2f} bid={bid} ask={ask} "
                        f"spread={spread_pct:.1%} — rejected (>{max_spread_pct:.0%} spread)"
                    )
                    continue

                # Score: closest delta to midpoint wins
                target_delta = (delta_min + delta_max) / 2
                score = -abs(delta - target_delta)
                candidates.append((score, contract["symbol"]))

            if not candidates:
                # Compute delta range across all calls for diagnostics
                all_deltas = []
                for c in chain:
                    if c.get("option_type", "").lower() != "call":
                        continue
                    g = c.get("greeks") or {}
                    d = g.get("delta")
                    if d is not None:
                        all_deltas.append((abs(float(d)), c.get("strike"), c.get("symbol")))
                if all_deltas:
                    all_deltas.sort()
                    closest = min(all_deltas, key=lambda x: abs(x[0] - (delta_min + delta_max) / 2))
                    delta_vals = [d for d, _, _ in all_deltas]
                    logger.warning(
                        f"No suitable contracts for {underlying} {expiry} — "
                        f"{calls_seen} calls scanned: "
                        f"{rejected_delta} wrong delta (need {delta_min}–{delta_max}), "
                        f"{rejected_no_ask} no ask, "
                        f"{rejected_spread} spread too wide (>{max_spread_pct:.0%}), "
                        f"{rejected_oi} low OI | "
                        f"delta range seen: {min(delta_vals):.3f}–{max(delta_vals):.3f} | "
                        f"closest to target: strike={closest[1]} delta={closest[0]:.3f} ({closest[2]})"
                    )
                else:
                    logger.warning(
                        f"No suitable contracts for {underlying} {expiry} — "
                        f"{calls_seen} calls scanned: "
                        f"{rejected_delta} wrong delta (need {delta_min}–{delta_max}), "
                        f"{rejected_no_ask} no ask, "
                        f"{rejected_spread} spread too wide (>{max_spread_pct:.0%}), "
                        f"{rejected_oi} low OI | no greeks available"
                    )
                return None

            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            logger.info(f"Selected contract for {underlying}: {best}")
            return best

        except Exception as e:
            logger.warning(f"Could not select option contract for {underlying}: {e}")
            return None

    async def _refresh_greeks(self, state: StrategyMarketState):
        try:
            from services.market_data.options.enhanced_service import get_enhanced_options_service
            svc = get_enhanced_options_service(enable_realtime=False)
            if state.option_symbol:
                data = await svc._get_rest_data(state.option_symbol)
                if data:
                    state.delta = data.get("delta")
                    state.open_interest = data.get("open_interest")
            state.greeks_last_fetched = datetime.utcnow()
        except Exception as e:
            logger.warning(
                f"Greeks refresh failed for {state.underlying_symbol}: {e}"
            )


_worker: "StreamDrivenWorker | None" = None


def get_stream_driven_worker() -> "StreamDrivenWorker":
    global _worker
    if _worker is None:
        _worker = StreamDrivenWorker()
    return _worker

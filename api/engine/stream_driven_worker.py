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
import re
from datetime import datetime, timedelta, date
from typing import Optional

from database import SessionLocals, default_environment
from config import Environment
from models import User, Strategy, Position, Trade
from engine.strategy_executor import StrategyExecutor
from engine.stream_router import get_stream_router
from engine.tradier_stream_manager import get_stream_manager
from engine.event_logger import log_event
from notifications.discord import notify_position_closed
from utils.market_hours import is_market_open
from utils.symbol_helpers import is_option_symbol, parse_occ_symbol
from engine.signal_generator import resolve_direction

logger = logging.getLogger(__name__)


def _occ_expiry(occ: Optional[str]) -> Optional[date]:
    """Parse the expiry date out of an OCC option symbol (…YYMMDD[C|P]NNNNNNNN).
    Returns None if it doesn't look like an option symbol."""
    m = re.search(r"(\d{6})[CP]\d{8}$", occ or "")
    if not m:
        return None
    ymd = m.group(1)
    try:
        return date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None


def _contract_expired(occ: Optional[str]) -> bool:
    """True if the contract's expiry is strictly before today.

    Strictly before — a 0DTE contract on its expiry day is still tradeable intraday,
    so expiry == today is NOT expired. This exists because a contract armed on a
    Friday afternoon and held over the weekend is dead by Monday, the broker rejects
    every order for it ("Expiration date must be greater than the current date"), and
    since a failed order never opens a position, nothing else ever clears it. That
    silently halted all trading 2026-07-20 → 07-24.
    """
    exp = _occ_expiry(occ)
    return exp is not None and exp < date.today()


_MARKET_CLOSED_LOG_INTERVAL = timedelta(minutes=1)
_RECONCILE_INTERVAL = timedelta(seconds=60)
# How often to re-price the armed (not yet bought) contract against Tradier while
# we wait for an entry signal. The contract is chosen once, but the wait can run
# for hours — and on 0DTE, gamma walks delta out of the strategy's band in
# minutes. Without this the engine buys, at entry time, a strike that only met
# the delta/OI criteria back when it was picked.
_DRIFT_CHECK_INTERVAL = timedelta(seconds=30)
# Per-strategy "still alive" heartbeat at INFO. Without this, an open
# position evaluating cleanly (no exit signal) produces zero output, since
# the no-exit log in strategy_executor is DEBUG. Heartbeat surfaces loop
# liveness, eval cadence, and current quote state without flooding logs.
_HEARTBEAT_INTERVAL = timedelta(seconds=30)
# Minimum interval between strategy evaluations on the same strategy. Stream
# ticks can arrive 10+ per second on liquid names; without this, every tick
# triggers a fresh executor pass before the previous fill has settled, which
# is what produced the 2026-05-04 runaway loop. Tuned for 0DTE scalping.
_EVAL_INTERVAL = timedelta(seconds=1)
# Wall-clock forced reconcile cadence. The existing reconcile relies on the
# 60s queue-idle timeout; a busy WS queue (or runaway loop) can prevent that
# timeout from ever firing, leaving local DB and broker out of sync for hours.
_FORCED_RECONCILE_INTERVAL = timedelta(seconds=60)


@dataclass
class SelectedContract:
    """A contract that passed the delta / OI / spread filters, with the greeks it
    passed on — so the caller doesn't have to re-fetch what selection already read."""
    symbol: str
    delta: float
    open_interest: int


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

    # Greeks of the armed contract, sourced from the Tradier chain at selection and
    # re-priced on _DRIFT_CHECK_INTERVAL while we wait to enter. These feed the
    # delta / min_open_interest gates in SignalGenerator, which only fire when the
    # value is not None — so leaving them unset silently disables those gates.
    delta: Optional[float] = None
    open_interest: Optional[int] = None
    drift_checked_at: Optional[datetime] = None

    # Exactly what THIS strategy has subscribed on the shared WS session. The
    # refcount in TradierStreamManager is global, so unsubscribing a symbol we
    # never subscribed decrements someone else's count and can rip the stream out
    # from under another strategy holding the same strike. Reselection makes the
    # armed contract a moving target, so we can't rely on a startup snapshot.
    streamed_symbols: set = field(default_factory=set)

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

    def arm(self, sel: "SelectedContract"):
        """Adopt a freshly selected contract as the one we'd buy on the next entry
        signal. Quotes are zeroed so the previous contract's bid/ask can't price
        this one; drift_checked_at is stamped because sel's greeks ARE the check."""
        self.option_symbol = sel.symbol
        self.delta = sel.delta
        self.open_interest = sel.open_interest
        self.option_bid = 0.0
        self.option_ask = 0.0
        self.drift_checked_at = datetime.utcnow()

    def disarm(self):
        """Drop the armed contract. Greeks go with it — a stale delta from the old
        strike must never be what the entry gate sees for the next one."""
        self.option_symbol = None
        self.delta = None
        self.open_interest = None
        self.option_bid = 0.0
        self.option_ask = 0.0
        self.drift_checked_at = None

    def needs_drift_check(self) -> bool:
        if self.drift_checked_at is None:
            return True
        return datetime.utcnow() - self.drift_checked_at > _DRIFT_CHECK_INTERVAL

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
            db = SessionLocals[default_environment()]()
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
        db = SessionLocals[default_environment()]()
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
            db = SessionLocals[default_environment()]()
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
                    sel = await self._select_option_contract(strategy, underlying)
                    if sel:
                        state.arm(sel)

                symbols_to_stream = [underlying]
                if state.option_symbol:
                    symbols_to_stream.append(state.option_symbol)

                router = get_stream_router()
                stream_mgr = get_stream_manager()

                q = router.register_strategy(strategy_id, symbols_to_stream)
                await stream_mgr.subscribe(symbols_to_stream)
                state.streamed_symbols.update(symbols_to_stream)

                executor = StrategyExecutor(db)
                strategy_refreshed_at = datetime.utcnow()
                contract_retry_at: Optional[datetime] = None  # throttle failed contract-selection retries
                last_market_closed_log: Optional[datetime] = None
                last_closed_reconcile_at: Optional[datetime] = None
                last_eval_at: Optional[datetime] = None
                last_forced_reconcile_at: Optional[datetime] = None
                last_heartbeat_at: Optional[datetime] = None

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
                            # After-hours stream events keep the queue warm so the
                            # 60s timeout-driven reconcile never fires.  Reconcile
                            # here on a 60s throttle so manual closes done after
                            # the bell still get caught and logged.
                            if last_closed_reconcile_at is None or now - last_closed_reconcile_at >= _RECONCILE_INTERVAL:
                                await self._reconcile_position(strategy_id, state, db)
                                last_closed_reconcile_at = now
                            continue

                        state.apply(event)

                        # Heartbeat — proves the loop is alive between entries/exits.
                        # Any market-hours event keeps this ticking; after-hours and
                        # 60s queue-idle have their own log paths.
                        now_hb = datetime.utcnow()
                        if (
                            last_heartbeat_at is None
                            or now_hb - last_heartbeat_at >= _HEARTBEAT_INTERVAL
                        ):
                            open_count = db.query(Position).filter(
                                Position.strategy_id == strategy_id,
                                Position.qty > 0,
                            ).count()
                            last_eval_age = (
                                f"{(now_hb - last_eval_at).total_seconds():.1f}s"
                                if last_eval_at else "never"
                            )
                            quote_str = (
                                f" option={state.option_symbol} bid={state.option_bid:.2f} ask={state.option_ask:.2f}"
                                if state.option_symbol else ""
                            )
                            logger.info(
                                f"Strategy {strategy_id} heartbeat: {open_count} open, "
                                f"underlying={state.underlying_price:.2f}, last_eval={last_eval_age}{quote_str}"
                            )
                            last_heartbeat_at = now_hb

                        # Fire signal check on every underlying trade tick with valid price
                        if (
                            event.get("type") in ("trade", "tradex")
                            and event.get("symbol") == underlying
                            and state.underlying_price > 0
                        ):
                            now = datetime.utcnow()

                            # Forced wall-clock reconcile — independent of queue
                            # idleness, so a busy stream can't starve sync.
                            if (
                                last_forced_reconcile_at is None
                                or now - last_forced_reconcile_at >= _FORCED_RECONCILE_INTERVAL
                            ):
                                await self._reconcile_position(strategy_id, state, db)
                                last_forced_reconcile_at = now

                            # Per-tick eval debounce — drop ticks that arrive
                            # faster than the executor can meaningfully act on.
                            # State accumulator already absorbed the tick above;
                            # we only skip the executor invocation.
                            if (
                                last_eval_at is not None
                                and now - last_eval_at < _EVAL_INTERVAL
                            ):
                                continue
                            last_eval_at = now

                            # Refresh strategy params from DB every 30s so UI edits
                            # (e.g. TP/SL changes) take effect without a server restart
                            if (datetime.utcnow() - strategy_refreshed_at).total_seconds() >= 30:
                                db.refresh(strategy)
                                strategy_refreshed_at = datetime.utcnow()

                            # Re-read position state from DB on every tick.
                            # This is the single source of truth — once a position
                            # is open we ONLY look for exits; once it's gone we
                            # look for a new entry.
                            # At most one row should be open (the entry lockout
                            # is per-underlying), but rows are now per-contract —
                            # order explicitly so a duplicate can never be picked
                            # non-deterministically between ticks.
                            open_pos = db.query(Position).filter(
                                Position.strategy_id == strategy_id,
                                Position.qty > 0,
                            ).order_by(Position.id.desc()).first()

                            if open_pos:
                                result = await executor.execute_exit_tick(
                                    user, strategy, state.to_market_data()
                                )
                                # Position just closed — release the contract so the
                                # next entry re-selects against a current chain rather
                                # than reusing the strike (and greeks) we just exited.
                                if result and result.get('positions_closed'):
                                    await self._disarm_contract(
                                        strategy_id, state, stream_mgr, router
                                    )
                            else:
                                # Drop an expired armed contract before doing anything
                                # with it. A 0DTE strike armed Friday afternoon is dead by
                                # Monday; the broker rejects every order for it, and a
                                # failed order never opens a position to clear it — so
                                # without this, one weekend permanently halts the strategy
                                # (incident 2026-07-20 → 07-24).
                                if state.option_symbol and _contract_expired(state.option_symbol):
                                    logger.warning(
                                        f"Strategy {strategy_id}: armed contract "
                                        f"{state.option_symbol} expired — disarming and reselecting"
                                    )
                                    await self._disarm_contract(
                                        strategy_id, state, stream_mgr, router
                                    )

                                # No position open — arm a contract if we don't have one
                                # (cold start, or we just exited / drifted out of band)
                                if not state.option_symbol:
                                    now = datetime.utcnow()
                                    # Only retry contract selection every 30s to avoid
                                    # hammering the options chain API on every tick when
                                    # no suitable contract is available yet
                                    if contract_retry_at is None or now >= contract_retry_at:
                                        sel = await self._select_option_contract(
                                            strategy, underlying
                                        )
                                        contract_retry_at = now + timedelta(seconds=30)
                                        if sel:
                                            await self._arm_contract(
                                                strategy_id, state, sel, stream_mgr, router
                                            )
                                elif state.needs_drift_check():
                                    # Armed but not yet bought. Re-price it: the entry
                                    # signal may still be minutes or hours away.
                                    await self._check_contract_drift(
                                        strategy, strategy_id, state, stream_mgr, router
                                    )

                                await executor.execute_strategy_tick(
                                    user, strategy, state.to_market_data()
                                )

                finally:
                    # Release what we actually hold NOW, not the startup snapshot —
                    # reselection means the armed contract has likely changed since.
                    held = list(state.streamed_symbols)
                    router.unregister_strategy(strategy_id, held)
                    await stream_mgr.unsubscribe(held)
                    state.streamed_symbols.clear()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Strategy {strategy_id} task error: {e}", exc_info=True)
            finally:
                db.close()

    def _tradier_client_for(self, strategy_id: int, db):
        """Per-user Tradier client (live for live mode, sandbox for paper) for
        ACCOUNT-specific reads — so position reconcile queries the SAME account
        the engine places orders on, not the global sandbox singleton.

        Raises if the strategy's user can't be resolved; every caller already
        wraps the reconcile in try/except and safely skips the tick on error.
        (Market-data reads — quotes, option chain, market clock — are
        env-independent and intentionally keep using the shared client.)"""
        from engine.trading_client_manager import trading_manager

        strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strat is None:
            raise RuntimeError(f"reconcile: strategy {strategy_id} not found")
        user = db.query(User).filter(User.id == strat.user_id).first()
        if user is None:
            raise RuntimeError(f"reconcile: user for strategy {strategy_id} not found")
        return trading_manager.get_client(user)

    @staticmethod
    def _position_for_contract(db, strategy_id: int, underlying: str, occ: str):
        """The Position row for exactly this contract, created if absent.

        One row per (user, strategy, underlying, contract) — never one row per
        ticker. Both recovery paths below used to grab "the strategy's position
        row" and overwrite its `option_symbol`, which is how a single SPY row came
        to carry 1,922 trades across every strike ever held and why no historical
        trade could be attributed to the contract it actually closed.
        """
        strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strat is None:
            return None
        pos = db.query(Position).filter(
            Position.user_id == strat.user_id,
            Position.strategy_id == strategy_id,
            Position.symbol == underlying,
            Position.option_symbol == occ,
        ).first()
        if pos is None:
            pos = Position(
                user_id=strat.user_id,
                strategy_id=strategy_id,
                symbol=underlying,
                option_symbol=occ,
                qty=0,
                avg_entry_price=0.0,
                current_price=0.0,
                unrealized_pnl=0.0,
                opened_at=datetime.utcnow(),
            )
            db.add(pos)
            db.flush()   # assign an id without ending the caller's transaction
            logger.info(
                f"Strategy {strategy_id}: created position row for {occ} (id={pos.id})"
            )
        return pos

    @staticmethod
    def _adoptable_broker_options(
        db, user_id: int, strategy_id: int, underlying: str, tradier_positions
    ):
        """Broker option positions on `underlying` this strategy may adopt.

        Returns (adoptable, declined). `declined` is NOT cosmetic — see the
        callers: an empty `adoptable` with declined > 0 means "the broker holds
        something we chose not to manage", which must never be treated as "the
        broker is flat". Conflating the two zeroes a row for a position that is
        still live at the broker, leaving a real 0DTE contract with no stop
        loss, no take profit and no forced EOD exit.

        Only ONE filter is applied, deliberately:

        OWNERSHIP — skip a contract another of THIS USER's strategies already
        has an open Position row for. Two rows against one broker holding
        double-count unrealized P&L into the account-wide daily-loss gate and
        let each strategy close contracts the other owns. Scoped by user_id
        because OCC symbols are global: two accounts running SPY 0DTE land on
        the same contract string routinely, and an unscoped query would let one
        user's row block another user's engine from managing its own position.

        There is deliberately NO side filter. Adoption is how the engine regains
        the ability to CLOSE something it already owns, so it is an exit-enabling
        path and rule 4 applies: direction gates what we OPEN — the chain scan
        and the opposite-side entry gate — never what we may manage. Filtering
        by side here meant that flipping Direction in the form while holding a
        live call orphaned that call at the broker with no recovery path.
        """
        adoptable, declined = [], 0
        for p in tradier_positions:
            sym = str(p.get("symbol", ""))
            parsed = parse_occ_symbol(sym)
            # Match on the parsed OCC root, not a prefix: startswith("SPY")
            # also matches SPYG and SPYD contracts.
            if parsed is not None:
                if parsed.root != underlying:
                    continue
            elif not sym.startswith(underlying) or sym == underlying:
                continue
            if float(p.get("quantity", 0)) <= 0:
                continue
            claimed = db.query(Position).filter(
                Position.user_id == user_id,
                Position.option_symbol == sym,
                Position.strategy_id != strategy_id,
                Position.qty > 0,
            ).first()
            if claimed is not None:
                logger.warning(
                    f"Strategy {strategy_id}: not adopting {sym} — strategy "
                    f"{claimed.strategy_id} already holds it (qty={claimed.qty})"
                )
                declined += 1
                continue
            adoptable.append(p)
        return adoptable, declined

    @staticmethod
    def _flatten_other_contracts(db, strategy_id: int, keep_position_id) -> int:
        """Zero every OPEN position row for this strategy except `keep_position_id`.

        The broker is the authority on what we hold. With per-contract rows, a
        stale open row for a contract the broker no longer shows would give the
        worker's `open_pos` lookup two candidates and it would manage the wrong
        one. Returns how many rows were zeroed.
        """
        stale = db.query(Position).filter(
            Position.strategy_id == strategy_id,
            Position.qty > 0,
            Position.id != (keep_position_id or -1),
        ).all()
        for row in stale:
            logger.warning(
                f"Strategy {strategy_id}: zeroing stale open row id={row.id} "
                f"({row.option_symbol}) — broker does not hold it"
            )
            row.qty = 0
            row.unrealized_pnl = 0.0
        return len(stale)

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
            client = self._tradier_client_for(strategy_id, db)
            tradier_positions = await asyncio.to_thread(client.get_positions)

            # Option contracts for our underlying that this strategy may adopt.
            strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
            if strat is None:
                logger.error(f"Strategy {strategy_id}: row vanished — skipping sync")
                return
            held, declined = self._adoptable_broker_options(
                db, strat.user_id, strategy_id, underlying, tradier_positions
            )

            if held:
                tradier_pos = held[0]
                occ_symbol = tradier_pos["symbol"]
                qty = int(float(tradier_pos.get("quantity", 1)))
                cost_basis = float(tradier_pos.get("cost_basis", 0))
                entry_price = cost_basis / (qty * 100) if qty > 0 else 0.0

                # Find-or-CREATE the row for the contract the broker actually
                # holds. Previously this grabbed whatever row the strategy had and
                # rewrote its option_symbol — and when no row existed at all it
                # gave up ("cannot resume automatically"), leaving a real broker
                # position unmanaged. Both are fixed by keying on the contract.
                db_pos = self._position_for_contract(db, strategy_id, underlying, occ_symbol)
                if db_pos is None:
                    logger.error(
                        f"Strategy {strategy_id}: cannot resolve strategy row — "
                        f"skipping startup sync for {occ_symbol}"
                    )
                    return

                db_pos.qty = qty
                if entry_price > 0:
                    db_pos.avg_entry_price = entry_price
                    if not db_pos.current_price:
                        db_pos.current_price = entry_price

                # The broker holds exactly this contract, so nothing else is open.
                self._flatten_other_contracts(db, strategy_id, db_pos.id)

                db.commit()
                state.option_symbol = occ_symbol
                logger.info(
                    f"Strategy {strategy_id}: synced from Tradier — "
                    f"{occ_symbol} qty={qty} entry=${entry_price:.2f} (position id={db_pos.id})"
                )

            elif declined:
                # The broker HOLDS something here; we just declined to manage it
                # (another strategy owns the row). Falling through to the zeroing
                # branch would mark our rows closed against a live broker
                # position — no SL, no TP, no EOD exit. Leave state untouched.
                logger.warning(
                    f"Strategy {strategy_id}: broker holds {declined} contract(s) on "
                    f"{underlying} claimed by another strategy — leaving DB rows alone"
                )

            else:
                # No position in Tradier — zero out every open row, not just one.
                open_rows = db.query(Position).filter(
                    Position.strategy_id == strategy_id,
                    Position.qty > 0,
                ).all()
                for db_pos in open_rows:
                    closed_contract = db_pos.option_symbol
                    logger.info(
                        f"Strategy {strategy_id}: DB shows {closed_contract} open but "
                        "Tradier has none — clearing (was manually closed)"
                    )
                    db_pos.qty = 0
                    db_pos.unrealized_pnl = 0.0

                    log_event(
                        db=db,
                        user_id=db_pos.user_id,
                        event_type="POSITION_MANUALLY_CLOSED",
                        title=f"Position closed manually: {closed_contract or underlying}",
                        symbol=db_pos.symbol,
                        strategy_id=strategy_id,
                        severity="warning",
                        event_data={
                            "option_symbol": closed_contract,
                            "detected_at": "startup_sync",
                        },
                    )
                if open_rows:
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

        Also handles the inverse: if DB shows flat (qty=0) but Tradier holds
        contracts for this strategy's underlying, adopt the broker truth so
        the executor can manage the position rather than silently leaving it
        unmanaged (this was the 2026-05-04 incident).
        """
        # Settle anything we stopped waiting on BEFORE comparing local state to the
        # broker. A late fill has to be recorded (and the entry block lifted) first,
        # otherwise this tick reconciles against a position we haven't written down yet.
        await self._resolve_unconfirmed_orders(strategy_id, db)

        # Pick up any row for this strategy regardless of qty so we can detect
        # the inverse-drift case (broker has contracts, DB shows flat).
        # The OPEN row, if any. With per-contract rows there can be several rows
        # for a strategy but at most one should be open — the entry lockout
        # guarantees it. Ordered so a duplicate can never be picked at random.
        position = db.query(Position).filter(
            Position.strategy_id == strategy_id,
            Position.qty > 0,
        ).order_by(Position.id.desc()).first()

        # If DB is flat, look at the broker — if the broker holds something
        # for this underlying, adopt it so the executor stops missing exits.
        if position is None:
            try:
                client = self._tradier_client_for(strategy_id, db)
                tradier_positions = await asyncio.to_thread(client.get_positions)
                underlying = state.underlying_symbol
                strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
                held, _declined = self._adoptable_broker_options(
                    db, strat.user_id if strat else 0, strategy_id, underlying,
                    tradier_positions
                )
                if held:
                    tradier_pos = held[0]
                    occ = tradier_pos["symbol"]
                    qty = int(float(tradier_pos.get("quantity", 1)))
                    cost_basis = float(tradier_pos.get("cost_basis", 0))
                    entry_price = cost_basis / (qty * 100) if qty > 0 else 0.0

                    # Adopt into the row for THIS contract, creating it if needed —
                    # never by rewriting some other contract's row.
                    adopted = self._position_for_contract(
                        db, strategy_id, underlying, occ
                    )
                    if adopted is None:
                        logger.error(
                            f"Strategy {strategy_id}: cannot resolve strategy row — "
                            f"skipping adoption of {occ}"
                        )
                        return
                    adopted.qty = qty
                    if entry_price > 0:
                        adopted.avg_entry_price = entry_price
                        if not adopted.current_price:
                            adopted.current_price = entry_price
                    adopted.opened_at = datetime.utcnow()
                    self._flatten_other_contracts(db, strategy_id, adopted.id)
                    db.commit()
                    state.option_symbol = occ
                    logger.warning(
                        f"Strategy {strategy_id}: broker held {occ} qty={qty} "
                        f"while DB was flat — adopting broker truth (position id={adopted.id})"
                    )
                    log_event(
                        db=db,
                        user_id=adopted.user_id,
                        event_type="POSITION_ADOPTED_FROM_BROKER",
                        title=f"Adopted untracked position: {occ}",
                        detail=f"Broker held {qty} contracts not tracked locally — adopted.",
                        symbol=adopted.symbol,
                        strategy_id=strategy_id,
                        severity="warning",
                        event_data={"option_symbol": occ, "qty": qty},
                    )
            except Exception as e:
                logger.warning(f"Inverse-drift reconcile failed for strategy {strategy_id}: {e}")
            return

        # The POSITION's contract wins over the armed one. `state.option_symbol`
        # is whatever is currently armed, which diverges from what we hold every
        # time the engine reselects a strike (the 2026-07-14 mispricing). Now that
        # the row names exactly one contract, it is the authority on what we own.
        contract = position.option_symbol or state.option_symbol
        if not contract:
            return  # can't identify the contract

        try:
            client = self._tradier_client_for(strategy_id, db)
            tradier_positions = await asyncio.to_thread(client.get_positions)

            held = {
                p.get("symbol"): int(float(p.get("quantity", 0) or 0))
                for p in tradier_positions
            }
            tradier_qty = held.get(contract, 0)

            # Options trade in 100-share contracts. Hoisted above the branches:
            # both the full-close and the partial-close path need it.
            multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1

            if tradier_qty <= 0:
                logger.warning(
                    f"Strategy {strategy_id}: {contract} not found in Tradier — "
                    "position was manually closed externally"
                )
                qty_closed = position.qty

                # Ask the broker what it actually filled the close at. Without this we
                # fall back to the last streamed quote, which is a guess — and on
                # 2026-07-13 a hand-close in the Tradier portal left NO Trade row at all,
                # silently dropping its -$104 from P&L history.
                fill = await self._broker_close_fill(client, contract)
                if fill:
                    exit_price, filled_qty, price_source = fill[0], fill[1], "broker_fill"
                else:
                    filled_qty = qty_closed
                    exit_price, price_source = await self._fallback_exit_price(
                        client, position, contract, state
                    )

                approx_pnl = (exit_price - position.avg_entry_price) * filled_qty * multiplier

                # Record the closing leg. Zeroing the position keeps the engine honest
                # about what it holds, but without this row the trade never happened as
                # far as P&L, win-rate, and every downstream metric are concerned.
                db.add(Trade(
                    user_id=position.user_id,
                    strategy_id=strategy_id,
                    position_id=position.id,
                    symbol=position.symbol,
                    side='sell',
                    order_type='market',
                    qty=filled_qty,
                    filled_qty=filled_qty,
                    price=position.avg_entry_price,
                    exit_price=exit_price,
                    exit_timestamp=datetime.utcnow(),
                    pnl=approx_pnl,
                    status='executed',
                    timestamp=datetime.utcnow(),
                    notes={
                        'signal_type': 'exit',
                        'signal_reason': 'Closed externally (broker UI / outside the engine)',
                        'option_symbol': contract,
                        'reconciled': True,
                        'exit_price_source': price_source,
                    },
                ))

                position.qty = 0
                position.current_price = exit_price
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
                try:
                    user = position.user
                    notify_position_closed(
                        user_prefs=user.notification_preferences if user else None,
                        symbol=position.symbol,
                        qty=qty_closed,
                        price=exit_price,
                        pnl=approx_pnl,
                        strategy_name="Manual close (broker)",
                        option_symbol=contract,
                        entry_price=position.avg_entry_price,
                    )
                except Exception as e:
                    logger.warning(f"Discord notify (manual close) failed: {e}")

                # Clear so next entry picks a fresh contract
                state.option_symbol = None

            elif tradier_qty < position.qty:
                # Partial manual close — adjust local qty down to match broker
                logger.warning(
                    f"Strategy {strategy_id}: {contract} qty drift — "
                    f"local={position.qty} tradier={tradier_qty} (partial manual close)"
                )
                position.qty = tradier_qty
                # 100x multiplier, same as every other unrealized-P&L write in
                # the engine — without it a partial manual close silently
                # under-reported the remaining leg by 100x.
                position.unrealized_pnl = (
                    (position.current_price or position.avg_entry_price) - position.avg_entry_price
                ) * tradier_qty * multiplier
                db.commit()

                log_event(
                    db=db,
                    user_id=position.user_id,
                    event_type="POSITION_QTY_RECONCILED",
                    title=f"Position qty adjusted: {contract}",
                    detail=f"Local qty reduced to match Tradier ({tradier_qty})",
                    symbol=position.symbol,
                    strategy_id=strategy_id,
                    severity="warning",
                    event_data={"option_symbol": contract, "tradier_qty": tradier_qty},
                )

            elif tradier_qty > position.qty:
                # Tradier shows more contracts than we tracked — likely a manual
                # buy in the broker UI. Don't silently adopt them; just warn.
                logger.warning(
                    f"Strategy {strategy_id}: {contract} qty drift — "
                    f"local={position.qty} tradier={tradier_qty} (extra contracts on broker)"
                )

        except Exception as e:
            logger.warning(f"Position reconciliation failed for strategy {strategy_id}: {e}")

    async def _select_option_contract(
        self, strategy: Strategy, underlying: str
    ) -> Optional[SelectedContract]:
        """Select best 0DTE option contract via Tradier options chain API.

        Which side of the chain is scanned comes from the strategy's
        `direction` param ('call' or 'put'); see resolve_direction.
        """
        try:
            from datetime import date
            from tradier_integration.client import get_tradier_client

            client = get_tradier_client()
            params = strategy.params_json
            # Same resolver the entry-signal path uses, so the contract we arm
            # and the signal that fires can never disagree about direction.
            direction = resolve_direction(params)
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

            # Filter contracts on the chosen side within delta range, with
            # sufficient liquidity. Delta is compared on |delta| below, so a
            # put's negative delta lands in the same 0.40–0.90 band as a call's
            # — the band means "how far in the money", not "which direction".
            candidates = []
            rejected_delta = 0
            rejected_oi = 0
            rejected_no_ask = 0
            rejected_spread = 0
            scanned = 0

            for contract in chain:
                if contract.get("option_type", "").lower() != direction:
                    continue
                scanned += 1
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

                # Score: closest delta to midpoint wins. Picking mid-band (rather
                # than the first passing strike) is also what keeps drift-driven
                # reselection from thrashing — a fresh pick starts far from both edges.
                target_delta = (delta_min + delta_max) / 2
                score = -abs(delta - target_delta)
                candidates.append(
                    (score, SelectedContract(symbol=contract["symbol"], delta=delta, open_interest=oi))
                )

            if not candidates:
                # Compute delta range across the scanned side for diagnostics
                all_deltas = []
                for c in chain:
                    if c.get("option_type", "").lower() != direction:
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
                        f"{scanned} {direction}s scanned: "
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
                        f"{scanned} {direction}s scanned: "
                        f"{rejected_delta} wrong delta (need {delta_min}–{delta_max}), "
                        f"{rejected_no_ask} no ask, "
                        f"{rejected_spread} spread too wide (>{max_spread_pct:.0%}), "
                        f"{rejected_oi} low OI | no greeks available"
                    )
                return None

            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0][1]
            logger.info(
                f"Selected {direction} for {underlying}: {best.symbol} "
                f"delta={best.delta:.3f} OI={best.open_interest}"
            )
            return best

        except Exception as e:
            logger.warning(f"Could not select option contract for {underlying}: {e}")
            return None

    async def _resolve_unconfirmed_orders(self, strategy_id: int, db):
        """Re-poll orders whose fill we never confirmed. Cheap no-op when there are none."""
        from engine.order_manager import OrderManager

        strat = db.query(Strategy).filter(Strategy.id == strategy_id).first()
        if strat is None:
            return
        if not OrderManager.has_unconfirmed_orders(strat.user_id, strategy_id):
            return
        user = db.query(User).filter(User.id == strat.user_id).first()
        if user is None:
            return
        try:
            n = await OrderManager(db).resolve_unconfirmed_orders(user, strat)
            if n:
                logger.warning(
                    f"Strategy {strategy_id}: settled {n} previously-unconfirmed order(s); "
                    "entries unblocked"
                )
        except Exception as e:
            logger.warning(f"Resolving unconfirmed orders failed for {strategy_id}: {e}")

    @staticmethod
    def _price_is_plausible_premium(price: float, underlying_price: float) -> bool:
        """Reject an option 'price' that is really the UNDERLYING's price.

        The engine trades 0DTE contracts in the 0.30–0.90 delta band; such a
        contract is worth single-digit dollars against an underlying in the
        hundreds. A premium at a quarter of the underlying's price is not a
        premium — it is the underlying leaking through a path that failed to
        resolve the option quote. That contamination is what turned a $2.23
        SPY contract into a $223k "close" on Sat 2026-08-01, and the number
        went straight into the daily-loss gate.

        Returns True when the underlying price is unknown — no basis to reject.
        """
        if price <= 0:
            return False
        if underlying_price <= 0:
            return True
        return price < underlying_price * 0.25

    async def _fallback_exit_price(
        self, client, position, contract: str, state: "StrategyMarketState"
    ) -> tuple:
        """Best available exit price when the broker has no close-fill on record
        (e.g. the close happened in a previous session — Tradier's /orders only
        covers the current one). Returns (price, source).

        Ordered most- to least-trustworthy. Every candidate is sanity-checked
        against the underlying so a contaminated mark can never be recorded as a
        realized fill. If nothing survives, we book the exit AT COST (P&L 0) and
        log an error rather than invent a number — an obviously-flagged zero is
        recoverable, a five-figure phantom silently disables the loss cap.
        """
        underlying = state.underlying_price or 0.0
        entry = position.avg_entry_price or 0.0

        # 1. Ask the broker what the contract is worth right now.
        try:
            quotes = await asyncio.to_thread(client.get_quotes, [contract])
            q = quotes[0] if quotes else {}
            bid = float(q.get("bid") or 0)
            ask = float(q.get("ask") or 0)
            rest_price = (bid + ask) / 2 if ask > 0 else float(q.get("last") or 0)
            if self._price_is_plausible_premium(rest_price, underlying):
                return rest_price, "rest_quote"
            # A zero quote on an EXPIRED contract is not missing data — the
            # contract expired worthless and the loss is the full premium. This
            # is the outcome when an EOD exit fails to fire and a 0DTE is held
            # past the bell, so it must be booked, not swallowed.
            if rest_price <= 0 and _contract_expired(contract):
                logger.warning(
                    f"{contract} expired and quotes zero — booking exit at $0 "
                    "(expired worthless)"
                )
                return 0.0, "expired_worthless"
        except Exception as e:
            logger.warning(f"REST quote for {contract} failed during reconcile: {e}")

        # 2. Our own last mark. Trustworthy only because _check_exit_signals now
        #    marks positions off the held contract's quote, never the underlying.
        marked = position.current_price or 0.0
        if self._price_is_plausible_premium(marked, underlying):
            logger.warning(
                f"No broker close-fill and no REST quote for {contract} — "
                f"recording exit at last mark {marked} (approximate)"
            )
            return marked, "approx_streamed_quote"

        # 3. Nothing usable. Book flat and shout.
        logger.error(
            f"No trustworthy exit price for {contract} "
            f"(rest/mark rejected against underlying={underlying}, entry={entry}) — "
            "recording exit AT COST so P&L is not fabricated; reconcile manually"
        )
        return entry, "unknown_booked_at_cost"

    async def _broker_close_fill(self, client, contract: str) -> Optional[tuple]:
        """The broker's actual closing fill for `contract`: (price, qty), or None.

        Used when a position is closed outside the engine, so the Trade row carries the
        real avg_fill_price instead of whatever the stream last quoted. Tradier's /orders
        only covers the current session — an external close from a previous day won't be
        found here, and the caller falls back to the streamed price."""
        try:
            orders = await asyncio.to_thread(client.get_orders)
        except Exception as e:
            logger.warning(f"Close-fill lookup failed for {contract}: {e}")
            return None

        fills = [
            o for o in orders
            if o.get("option_symbol") == contract
            and (o.get("status") or "").lower() == "filled"
            and str(o.get("side", "")).startswith("sell")
        ]
        if not fills:
            return None

        fills.sort(key=lambda o: str(o.get("transaction_date") or o.get("create_date") or ""))
        last = fills[-1]
        price = float(last.get("avg_fill_price") or 0)
        qty = int(float(last.get("exec_quantity") or 0))
        return (price, qty) if price > 0 and qty > 0 else None

    async def _arm_contract(
        self, strategy_id: int, state: StrategyMarketState, sel: SelectedContract, stream_mgr, router
    ):
        """Adopt a contract and start streaming its quotes."""
        state.arm(sel)
        await stream_mgr.subscribe([sel.symbol])
        state.streamed_symbols.add(sel.symbol)
        router.add_symbol_to_strategy(strategy_id, sel.symbol)

    async def _disarm_contract(self, strategy_id: int, state: StrategyMarketState, stream_mgr, router):
        """Release the armed contract and stop streaming it. Must be paired with every
        clear of option_symbol — dropping the symbol without unsubscribing leaks both a
        refcount on the shared WS session and a route entry pointing at our queue.

        Only releases symbols WE subscribed: _reconcile_position can adopt a contract
        straight off the broker without ever streaming it, and unsubscribing that would
        decrement a refcount we never incremented."""
        sym = state.option_symbol
        state.disarm()
        if sym and sym in state.streamed_symbols:
            await stream_mgr.unsubscribe([sym])
            state.streamed_symbols.discard(sym)
            router.remove_symbol_from_strategy(strategy_id, sym)

    async def _check_contract_drift(
        self, strategy: Strategy, strategy_id: int, state: StrategyMarketState, stream_mgr, router
    ):
        """Re-price the armed contract off Tradier and disarm it if it no longer meets
        the strategy's criteria, so the next tick selects a fresh strike.

        Disarming (rather than just letting SignalGenerator reject the entry) is what
        avoids a deadlock: selection only runs when option_symbol is None, so a contract
        that drifts out of band while still armed would fail the entry gate on every
        tick, forever, with nothing able to replace it."""
        sym = state.option_symbol
        if not sym:
            return

        # An expired contract never comes back into band — disarm immediately so the
        # next tick reselects, instead of falling through to the "no greeks → hold"
        # path below, which would pin a dead contract forever.
        if _contract_expired(sym):
            logger.warning(f"Drift check: {sym} has expired — disarming")
            await self._disarm_contract(strategy_id, state, stream_mgr, router)
            return

        # A wrong-SIDE contract passes every criterion below — expiry, |delta|
        # and OI are all side-agnostic — so it has to be checked separately.
        # `direction` is editable in the UI and db.refresh(strategy) picks the
        # edit up within 30s, which would otherwise leave the old side armed:
        # the form, the signal reason and the opposite-side gate would all say
        # "put" while the next entry bought the call.
        #
        # Safe to disarm here because this method only runs when the strategy is
        # armed and FLAT (see the `elif state.needs_drift_check()` call site);
        # it is never reached while a position is open.
        want = resolve_direction(strategy.params_json)
        parsed = parse_occ_symbol(sym)
        if parsed is not None:
            side = 'call' if parsed.right == 'C' else 'put'
            if side != want:
                logger.info(
                    f"Drift check: {sym} is a {side} but the strategy now trades "
                    f"{want}s — disarming and reselecting"
                )
                await self._disarm_contract(strategy_id, state, stream_mgr, router)
                return

        # Stamp up front so a failing quote endpoint retries on the interval rather
        # than on every tick.
        state.drift_checked_at = datetime.utcnow()

        params = strategy.params_json
        delta_min = params.get("delta_min", 0.40)
        delta_max = params.get("delta_max", 0.90)
        min_oi = params.get("min_open_interest", 0)

        try:
            from tradier_integration.client import get_tradier_client

            quotes = await asyncio.to_thread(get_tradier_client().get_quotes, [sym], True)
        except Exception as e:
            logger.warning(f"Drift check failed for {sym}: {e} — keeping contract armed")
            return

        if not quotes:
            return

        greeks = quotes[0].get("greeks") or {}
        raw_delta = greeks.get("delta")
        if raw_delta is None:
            # No greeks back — hold the contract rather than disarming. Treating a
            # missing value as a failed check would churn strikes on a data hiccup.
            logger.debug(f"Drift check for {sym}: no greeks in quote, keeping armed")
            return

        delta = abs(float(raw_delta))
        oi = int(quotes[0].get("open_interest") or 0)
        state.delta = delta
        state.open_interest = oi

        if not (delta_min <= delta <= delta_max) or oi < min_oi:
            logger.info(
                f"Contract {sym} drifted out of criteria "
                f"(delta={delta:.3f} need {delta_min}–{delta_max}, "
                f"OI={oi} need >={min_oi}) — disarming and reselecting"
            )
            await self._disarm_contract(strategy_id, state, stream_mgr, router)


_worker: "StreamDrivenWorker | None" = None


def get_stream_driven_worker() -> "StreamDrivenWorker":
    global _worker
    if _worker is None:
        _worker = StreamDrivenWorker()
    return _worker

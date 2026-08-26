"""
Order Manager - Order lifecycle management and execution tracking

The Order Manager uses TradingClientManager which automatically routes orders
to the correct trading API based on user.selected_trading_mode:
  - Paper mode: Tradier SANDBOX
  - Live mode: Tradier LIVE
"""
import asyncio
import logging
import uuid
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import User, Strategy, Trade, Position
from engine.trading_client_manager import TradingClientManager
from engine.signal_generator import Signal, resolve_direction
from engine.event_logger import log_event
from notifications.discord import notify_position_opened, notify_position_closed
from utils.symbol_helpers import is_option_symbol, parse_occ_symbol

logger = logging.getLogger(__name__)


def _lt_emit_order(event: str, **fields):
    """Live-test only: append one order-lifecycle record to orders.jsonl,
    correlated by order_id. The `filled` event is the key datum — it captures
    the estimated price vs the broker's real avg_fill_price so we can prove
    whether live actually returns real fills. Never raises."""
    try:
        from live_test.logging_setup import is_enabled, get_jsonl_logger
        if not is_enabled():
            return
        get_jsonl_logger("orders").emit({"event": event, **fields})
    except Exception:
        pass


# Minimum interval between orders for the same (user, symbol). Belt-and-suspenders
# against runaway loops; tuned for 0DTE scalping where a few seconds is plenty.
MIN_ORDER_INTERVAL_SECONDS = 5.0

# Broker order states that will never change again (docs/tradier/accounts/order.md).
# Anything else — pending, open, partially_filled — means the order is still live and
# we must keep waiting rather than assume it died.
_TERMINAL_ORDER_STATUSES = {"filled", "rejected", "canceled", "expired"}

# Pre-flight order preview — call Tradier's preview endpoint before each
# place_order to validate buying power, contract validity, and surface
# commission/fees for the audit trail. Disable to fall back to direct placement.
ENABLE_ORDER_PREVIEW = True

# Cash-only GFV/T+1 protection: every accepted buy reserves cash in an
# in-process ledger, layered on top of Tradier's settled `cash.cash_available`.
# Effective available = settled_cash - sum(active reservations for this user).
# Reservations are released when the order reaches a terminal broker state
# (filled / rejected / canceled / expired). The TTL is a safety belt — if a
# release path is missed (crash, unhandled exception), the reservation lapses
# instead of locking cash forever.
RESERVATION_TTL_SECONDS = 60.0

# Per-options-contract estimate of broker commission + regulatory fees. Used
# as a safety buffer in non-prod environments where Tradier's preview returns
# commission=0 and fees=0 — without it, a sandbox-validated buy can slip past
# the gate at the edge of available cash and then fail in live for the missing
# fees. Sized conservatively above Tradier's published schedule (~$0.35 base
# commission + ~$0.10 regulatory). Refine from real Trade.commission/fees rows
# once live trading has produced a sample.
SANDBOX_FEE_BUFFER_PER_OPTION_CONTRACT = 0.65


class OrderResult:
    """Result of an order operation"""
    def __init__(
        self,
        success: bool,
        message: str,
        order_id: Optional[str] = None,
        trade: Optional[Trade] = None,
        filled_price: Optional[float] = None,
        filled_qty: Optional[int] = None
    ):
        self.success = success
        self.message = message
        self.order_id = order_id
        self.trade = trade
        self.filled_price = filled_price
        self.filled_qty = filled_qty


class OrderManager:
    """
    Manages order lifecycle:
    - Order creation from signals
    - Order submission via TradingClientManager (auto-routes paper/live)
    - Order status tracking
    - Fill handling and position updates
    - Trade recording
    """

    # Class-level so the rate limit holds across executor instances within a process.
    # Keyed by (user_id, symbol). Values are last submission timestamps (UTC).
    _last_order_at: Dict[Tuple[int, str], datetime] = {}

    # Throttle-event dedupe: per (user_id, symbol), the _last_order_at value
    # we've already emitted ORDER_RATE_LIMITED for. Workers retry every tick
    # while the 5s window holds, which produced ~4 duplicate events per cycle
    # in the system_events table. Resets implicitly when a new order stamps
    # _last_order_at to a new timestamp.
    _throttle_logged_for: Dict[Tuple[int, str], datetime] = {}

    # Class-level pending-buy ledger — in-memory, process-scoped. Survives
    # nothing across restarts (broker is the source of truth post-restart).
    # Maps reservation_id -> {user_id, amount, expires_at}.
    _pending_buy_reservations: Dict[str, Dict] = {}

    # Orders we placed but could not confirm within the terminal-status poll window.
    # "Unconfirmed" is NOT "didn't happen" — the broker may still fill it, and on
    # 2026-07-13 two of these filled while the engine had written no Position row.
    # While one is outstanding we must not BUY again for that strategy: a second
    # entry would stack on top of an invisible first one, and max_positions cannot
    # catch it because there is no Position row to count. Sells are never blocked —
    # an exit must always be able to run.
    # Keyed by (user_id, strategy_id) -> {order_id: meta}
    _unconfirmed_orders: Dict[Tuple[int, int], Dict[str, Dict]] = {}

    # Strategies we've already emitted ENTRY_BLOCKED_UNCONFIRMED for in the current
    # block. The eval loop ticks every second and an order can stay unconfirmed until
    # the 60s reconcile, so without this we'd write ~60 identical system_events per
    # episode. Cleared when the strategy's last unconfirmed order settles, so the NEXT
    # block logs again. (Cannot reuse _should_log_throttle — it keys off
    # _last_order_at, which is only ever stamped with real symbols.)
    _unconfirmed_block_logged: set = set()

    @classmethod
    def _mark_unconfirmed(cls, user_id: int, strategy_id: int, order_id: str, meta: Dict) -> None:
        cls._unconfirmed_orders.setdefault((user_id, strategy_id), {})[str(order_id)] = meta

    @classmethod
    def _clear_unconfirmed(cls, user_id: int, strategy_id: int, order_id: str) -> None:
        bucket = cls._unconfirmed_orders.get((user_id, strategy_id))
        if not bucket:
            return
        bucket.pop(str(order_id), None)
        if not bucket:
            cls._unconfirmed_orders.pop((user_id, strategy_id), None)
            cls._unconfirmed_block_logged.discard((user_id, strategy_id))

    @classmethod
    def has_unconfirmed_orders(cls, user_id: int, strategy_id: int) -> bool:
        return bool(cls._unconfirmed_orders.get((user_id, strategy_id)))

    async def resolve_unconfirmed_orders(self, user: User, strategy: Strategy) -> int:
        """Re-poll orders the terminal-status wait gave up on, and settle them.

        Called from the reconcile tick. For an order the broker has since FILLED, this
        backfills the Trade row that the timeout path skipped — with the broker's real
        avg_fill_price, not our estimate — so P&L history matches the account. Position
        state is NOT touched here: _reconcile_position already adopts broker holdings,
        and doing it in both places would double-count.

        Clearing the order also lifts the entry block. Returns how many were settled.
        """
        key = (user.id, strategy.id)
        pending = dict(self._unconfirmed_orders.get(key, {}))
        if not pending:
            return 0

        try:
            client = self.trading_client.get_client(user)
        except Exception as e:
            logger.warning(f"Cannot resolve unconfirmed orders — client unavailable: {e}")
            return 0

        resolved = 0
        for order_id, meta in pending.items():
            try:
                order = await asyncio.to_thread(client.get_order, order_id)
            except Exception as e:
                logger.warning(f"resolve_unconfirmed: get_order({order_id}) failed: {e}")
                continue

            status = (order.get("status") or "").lower()
            if status not in _TERMINAL_ORDER_STATUSES:
                continue  # still working at the broker — keep the entry block on

            if status == "filled":
                self._backfill_filled_order(user, strategy, order_id, order, meta)
            else:
                logger.info(
                    f"Unconfirmed order {order_id} settled as '{status}' — no contracts taken"
                )

            self._clear_unconfirmed(user.id, strategy.id, order_id)
            resolved += 1

        return resolved

    def _backfill_filled_order(
        self, user: User, strategy: Strategy, order_id: str, order: Dict, meta: Dict
    ) -> None:
        """Write the Trade row for an order that filled after we stopped waiting."""
        filled_price = self._extract_filled_price(order, meta.get("signal_price") or 0.0)
        filled_qty = self._extract_filled_qty(order, meta.get("qty") or 0)
        if filled_qty <= 0:
            return

        # Idempotence: the row may already exist if a previous tick backfilled it.
        # (The in-process dict is cleared on success, but a restart could re-enter here.)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        already = self.db.query(Trade).filter(
            Trade.strategy_id == strategy.id,
            Trade.timestamp >= cutoff,
        ).all()
        if any(str((t.notes or {}).get("order_id")) == str(order_id) for t in already):
            logger.info(f"Order {order_id} already recorded — skipping backfill")
            return

        trade = Trade(
            user_id=user.id,
            strategy_id=strategy.id,
            symbol=meta.get("symbol"),
            side=meta.get("side"),
            order_type='market',
            qty=filled_qty,
            filled_qty=filled_qty,
            price=filled_price,
            status='executed',
            timestamp=datetime.utcnow(),
            notes={
                'signal_type': meta.get('signal_type'),
                'signal_reason': meta.get('signal_reason'),
                'order_id': order_id,
                'option_symbol': meta.get('option_symbol'),
                'backfilled': True,
                'backfill_reason': 'order confirmed filled after terminal-status timeout',
            },
        )
        self.db.add(trade)
        self.db.commit()

        logger.warning(
            f"Backfilled unconfirmed order {order_id}: {meta.get('side')} {filled_qty}x "
            f"{meta.get('option_symbol') or meta.get('symbol')} @ {filled_price}"
        )
        log_event(
            db=self.db,
            user_id=user.id,
            event_type="ORDER_BACKFILLED",
            title=f"Backfilled late fill: {meta.get('symbol')}",
            detail=(
                f"Order {order_id} was unconfirmed at placement but the broker "
                f"filled it ({filled_qty} @ {filled_price}). Trade row written."
            ),
            symbol=meta.get("symbol"),
            strategy_id=strategy.id,
            severity="warning",
            event_data={
                "order_id": order_id,
                "filled_qty": filled_qty,
                "filled_price": filled_price,
            },
        )

    def __init__(self, db: Session):
        self.db = db
        self.trading_client = TradingClientManager()

    @classmethod
    def _check_order_rate_limit(cls, user_id: int, symbol: str) -> Tuple[bool, float]:
        """Return (allowed, seconds_until_allowed). Symbol-scoped, not user-global."""
        last = cls._last_order_at.get((user_id, symbol))
        if last is None:
            return True, 0.0
        elapsed = (datetime.utcnow() - last).total_seconds()
        if elapsed >= MIN_ORDER_INTERVAL_SECONDS:
            return True, 0.0
        return False, MIN_ORDER_INTERVAL_SECONDS - elapsed

    @classmethod
    def _stamp_order_submitted(cls, user_id: int, symbol: str) -> None:
        cls._last_order_at[(user_id, symbol)] = datetime.utcnow()

    @classmethod
    def _should_log_throttle(cls, user_id: int, symbol: str) -> bool:
        """First throttle hit within a window → True (emit the event).
        Subsequent hits referencing the same _last_order_at → False (suppress).
        A new stamp advances _last_order_at, so the next window logs again."""
        current = cls._last_order_at.get((user_id, symbol))
        if current is None:
            return True
        if cls._throttle_logged_for.get((user_id, symbol)) == current:
            return False
        cls._throttle_logged_for[(user_id, symbol)] = current
        return True

    @classmethod
    def _purge_expired_reservations(cls) -> None:
        """Drop reservations past their TTL. A non-empty expiry set means a
        release path was missed somewhere — we log so it's visible without
        disrupting the order flow."""
        now = datetime.utcnow()
        expired = [
            rid for rid, r in cls._pending_buy_reservations.items()
            if r["expires_at"] <= now
        ]
        for rid in expired:
            r = cls._pending_buy_reservations.pop(rid, None)
            if r:
                logger.warning(
                    f"Buy reservation {rid} (user={r['user_id']}, "
                    f"amount=${r['amount']:.2f}) expired without explicit release. "
                    "A release path was likely missed."
                )

    @classmethod
    def _active_reservations_total(cls, user_id: int) -> float:
        """Sum of currently-held reservation amounts for a user."""
        cls._purge_expired_reservations()
        return sum(
            r["amount"] for r in cls._pending_buy_reservations.values()
            if r["user_id"] == user_id
        )

    @classmethod
    def _acquire_buy_reservation(cls, user_id: int, amount: float) -> str:
        """Add a reservation and return its id."""
        reservation_id = str(uuid.uuid4())
        cls._pending_buy_reservations[reservation_id] = {
            "user_id": user_id,
            "amount": amount,
            "expires_at": datetime.utcnow() + timedelta(seconds=RESERVATION_TTL_SECONDS),
        }
        return reservation_id

    @classmethod
    def _release_buy_reservation(cls, reservation_id: Optional[str]) -> None:
        """Drop a reservation. Safe to call with None or with an unknown id."""
        if reservation_id:
            cls._pending_buy_reservations.pop(reservation_id, None)

    @staticmethod
    def _estimate_fee_buffer(user: User, qty: int, option_symbol: Optional[str]) -> float:
        """Per-order fee buffer added to the reservation in non-prod envs.

        Tradier sandbox returns commission/fees as 0 on previews, which makes
        a sandbox-validated buy quietly under-funded vs the same buy in live.
        We pad with a per-contract estimate so the cash gate behaves the same
        in dev/test as it will in prod. In prod we trust Tradier's `cost`
        field (which already includes commission + fees) and pad nothing.
        """
        if (user.selected_environment or "").lower() == "prod":
            return 0.0
        if option_symbol:
            return qty * SANDBOX_FEE_BUFFER_PER_OPTION_CONTRACT
        return 0.0  # equities are commission-free at Tradier

    async def _preview_or_abort(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        qty: int,
        side: str,
        option_symbol: Optional[str],
        order_type: str = "market",
        signal_price: Optional[float] = None,
    ) -> Tuple[bool, Optional[Dict], str, Optional[str]]:
        """Call broker preview before placing an order.

        Returns (ok, preview_dict, message, reservation_id):
          - ok=True  → preview validated, safe to place. preview_dict carries
                       commission/fees/cost/order_cost for the audit trail.
                       For buys, reservation_id holds cash in the in-process
                       ledger and MUST be released by the caller (try/finally).
                       reservation_id is None for sells and when previews are
                       disabled or unavailable.
          - ok=False → abort the order. message explains why. No reservation.

        Cash-account-only: validates `cost` (total cash debit) against settled
        cash minus any in-process pending-buy reservations on entry orders.
        Sells generate cash so the cash gate is skipped.

        Aborts on any preview transport error/timeout — fail-safe over fail-open.
        """
        if not ENABLE_ORDER_PREVIEW:
            return True, None, "preview disabled", None

        try:
            preview = await self.trading_client.preview_order(
                user=user,
                symbol=symbol,
                qty=qty,
                side=side,
                order_type=order_type,
                option_symbol=option_symbol,
            )
        except Exception as e:
            msg = f"Preview failed for {symbol}: {e}"
            logger.error(msg)
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="ORDER_PREVIEW_FAILED",
                title=f"Preview failed: {symbol}",
                detail=msg,
                symbol=symbol,
                strategy_id=strategy.id,
                severity="error",
                event_data={"side": side, "qty": qty},
            )
            return False, None, msg, None

        if preview is None:
            # No preview came back. Treat as "no preview available" and proceed rather
            # than blocking the trade — Tradier returns one for both sandbox and live,
            # so this is a transport hiccup, not an expected path.
            return True, None, "preview not available for trading mode", None

        # Entry-price drift observation. Compares the per-contract price the
        # signal triggered on against the per-contract price the broker preview
        # quotes at fill time. Observation only — does NOT gate the order. The
        # data feeds a future decision on whether to add a "cancel if drift
        # exceeds X" rule (TODO #4); we log the distribution first instead of
        # picking a threshold blind. Skipped for sells (handled by exit-side
        # analysis in TODO #6) and for non-option orders.
        if (
            side == "buy"
            and option_symbol
            and signal_price is not None
            and signal_price > 0
            and qty > 0
        ):
            order_cost = float(preview.get("order_cost") or 0.0)
            if order_cost > 0:
                preview_per_contract = order_cost / (qty * 100.0)
                drift_pct = (preview_per_contract - signal_price) / signal_price
                drift_dollars = (preview_per_contract - signal_price) * qty * 100.0
                drift_msg = (
                    f"Entry preview drift {symbol} ({option_symbol}): "
                    f"signal=${signal_price:.4f} preview=${preview_per_contract:.4f} "
                    f"drift={drift_pct:+.2%} (${drift_dollars:+.2f} on {qty} contracts)"
                )
                logger.info(drift_msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="ORDER_PREVIEW_DRIFT",
                    title=f"Preview drift: {option_symbol} {drift_pct:+.2%}",
                    detail=drift_msg,
                    symbol=symbol,
                    strategy_id=strategy.id,
                    severity="info",
                    event_data={
                        "signal_price": signal_price,
                        "preview_per_contract": preview_per_contract,
                        "drift_pct": drift_pct,
                        "drift_dollars": drift_dollars,
                        "qty": qty,
                        "side": side,
                        "option_symbol": option_symbol,
                        "order_cost": order_cost,
                    },
                )

        # Cash gate — only on buys. Sells generate cash.
        if side == "buy":
            try:
                client = self.trading_client.get_client(user)
                balances = await asyncio.to_thread(client.get_balances)
                # Real cash accounts expose cash.cash_available (settled cash).
                # Margin/PDT/sandbox accounts return cash=None — fall back to
                # total_cash so buying-power validation still runs in dev.
                # Production cash accounts will pass through the preferred path.
                cash_block = balances.get("cash") or {}
                settled_cash_raw = cash_block.get("cash_available")
                if settled_cash_raw is None:
                    settled_cash = float(balances.get("total_cash") or 0.0)
                    logger.warning(
                        f"No cash.cash_available on this account "
                        f"(account_type={balances.get('account_type')!r}); "
                        f"falling back to total_cash=${settled_cash:.2f} for buy gate."
                    )
                else:
                    settled_cash = float(settled_cash_raw)
            except Exception as e:
                msg = f"Could not fetch settled cash for buy preview: {e}"
                logger.error(msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="ORDER_PREVIEW_FAILED",
                    title=f"Preview cash check failed: {symbol}",
                    detail=msg,
                    symbol=symbol,
                    strategy_id=strategy.id,
                    severity="error",
                )
                return False, preview, msg, None

            # Tradier preview semantics (per docs/tradier/trading/preview_order.md
            # example math): `cost` is the total cash debit, equal to
            # `order_cost + commission + fees`. Reserve `cost` so we match the
            # actual deduction. Sandbox returns commission=0/fees=0 → cost ==
            # order_cost there, so we add an explicit fee buffer below to keep
            # dev parity with prod.
            preview_cost = float(preview.get("cost") or preview.get("order_cost") or 0.0)
            fee_buffer = self._estimate_fee_buffer(user, qty, option_symbol)
            required = preview_cost + fee_buffer

            # Subtract in-process pending buys so concurrent signals can't
            # double-spend the same dollars between balance fetch and order
            # placement (Tradier won't reflect our pending order in
            # cash_available until they've registered it server-side).
            active_reservations = self._active_reservations_total(user.id)
            effective_available = settled_cash - active_reservations

            if required > effective_available:
                msg = (
                    f"Insufficient settled cash: required=${required:.2f} "
                    f"(cost=${preview_cost:.2f} + fee_buffer=${fee_buffer:.2f}) "
                    f"> effective_available=${effective_available:.2f} "
                    f"(settled=${settled_cash:.2f} - reserved=${active_reservations:.2f})"
                )
                logger.warning(msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="ORDER_PREVIEW_REJECTED",
                    title=f"Insufficient cash: {symbol}",
                    detail=msg,
                    symbol=symbol,
                    strategy_id=strategy.id,
                    severity="warning",
                    event_data={
                        "preview_cost": preview_cost,
                        "fee_buffer": fee_buffer,
                        "required": required,
                        "settled_cash": settled_cash,
                        "active_reservations": active_reservations,
                        "effective_available": effective_available,
                        "qty": qty,
                    },
                )
                return False, preview, msg, None

            reservation_id = self._acquire_buy_reservation(user.id, required)
            return True, preview, "preview ok", reservation_id

        return True, preview, "preview ok", None

    async def execute_signal(
        self,
        user: User,
        strategy: Strategy,
        signal: Signal,
        qty: int,
        option_symbol: Optional[str] = None,
        estimated_price: Optional[float] = None,
    ) -> OrderResult:
        """
        Execute a trading signal by placing an order

        Note: TradingClientManager automatically routes to paper or live based on user.selected_trading_mode

        Args:
            user: User object
            strategy: Strategy being executed
            signal: Signal object with action and price
            qty: Quantity to trade

        Returns:
            OrderResult with execution details
        """
        symbol = signal.symbol
        side = signal.action  # 'buy' or 'sell'
        order_type = 'market'  # Default to market orders for 0DTE scalping

        logger.info(
            f"Executing {signal.signal_type} signal: {side} {qty} {symbol} @ market "
            f"[Mode: {user.selected_trading_mode}]"
        )

        # Role-based gate: only `user` and `admin` may place new entries.
        # `strategy_author` can build strategies but never trades; `viewer`
        # and `auditor` are read-only. Exits (`side='sell'`) are NOT gated
        # so any existing positions can still be closed even if the user
        # was demoted to a non-trading role mid-session.
        if side == 'buy' and (user.role or 'user') not in ('user', 'admin'):
            msg = (
                f"Entry blocked by role: user.role='{user.role}' is not "
                f"permitted to place orders. Strategy '{strategy.name}' "
                f"({strategy.id}) signal ignored."
            )
            logger.warning(msg)
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="ENTRY_BLOCKED_BY_ROLE",
                title=f"Entry blocked: role={user.role}",
                detail=msg,
                symbol=symbol,
                strategy_id=strategy.id,
                severity="warning",
                event_data={"role": user.role, "side": side},
            )
            return OrderResult(success=False, message=msg)

        try:
            # Lock-out: once a position is open on (user, strategy, symbol),
            # block further entries so we lock in to sell-to-close instead of
            # stacking more contracts. Row-level lock prevents the race where
            # two ticks both see qty=0 and both place orders.
            #
            # DELIBERATELY keyed on the UNDERLYING, not the contract, even though
            # Position rows are now per-contract. This gate asks "do I hold ANY
            # contract on SPY?" — making it per-contract would let the engine hold
            # $745C and buy $750C on the same tick, which breaks three things that
            # assume one position at a time: the worker's single `open_pos` lookup,
            # the cash-reservation ledger's sizing, and max_positions. Finer row
            # identity must not widen a safety gate.
            if signal.signal_type == 'entry':
                existing = self.db.query(Position).filter(
                    Position.user_id == user.id,
                    Position.strategy_id == strategy.id,
                    Position.symbol == symbol,
                ).with_for_update().first()
                if existing and existing.qty > 0:
                    self.db.rollback()  # release the row lock immediately
                    msg = (
                        f"Entry skipped: position already open on {symbol} "
                        f"(qty={existing.qty}, contract={existing.option_symbol}). "
                        "Locked to exit-only."
                    )
                    logger.info(msg)
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ENTRY_SKIPPED",
                        title=f"Entry skipped: {symbol} already open",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="info",
                        event_data={"existing_qty": existing.qty},
                    )
                    return OrderResult(success=False, message=msg)
                self.db.rollback()  # release the lock before the broker call

                # PHASE-2 GATE: never hold both sides of the same underlying.
                #
                # The lockout above is per-STRATEGY. Running a call-side and a
                # put-side strategy on SPY gives each its own lockout, so both
                # could open at once — an unintended straddle that pays two
                # spreads and is directionally flat. This blocks the second one.
                #
                # Scoped to the OPPOSITE side only. Two same-direction
                # strategies on one symbol behaved this way before today and
                # this change must not quietly narrow that; the new risk is the
                # call/put pair, and that is all this closes.
                #
                # Entries only — an exit must never be blocked by this. We are
                # already past the `signal_type == 'entry'` test.
                #
                # Deliberately NOT locked with FOR UPDATE. The race this would
                # have to win is two flat workers evaluating on the same tick,
                # where there is no row yet to lock — a row lock buys nothing
                # and invites a cross-worker deadlock, since each worker already
                # holds a lock on its own strategy's row. Closing it properly
                # needs pg_advisory_xact_lock(user_id, symbol) or SERIALIZABLE.
                #
                # Be honest about the blind window: a Position row is written
                # only after terminal fill confirmation, so this gate cannot see
                # the other strategy's order for the WHOLE round trip (preview →
                # place → await-fill), and _unconfirmed_orders is keyed
                # (user_id, strategy_id) so it cannot see it either. If both
                # sides do open, the per-strategy lockout freezes each into
                # exit-only and the straddle is HELD until both legs exit — up
                # to the EOD floor, paying two spreads and two lots of 0DTE
                # theta. This gate makes that unlikely, not impossible.
                # Derive the side from the CONTRACT WE ARE ABOUT TO BUY, not
                # from params. `option_symbol` is what actually goes to the
                # broker; params are only what the strategy intends. The two can
                # disagree — the worker arms a contract once and re-validates it
                # on expiry/delta/OI, so a direction edit mid-session leaves the
                # old side armed until it disarms. Reading params there would
                # have let a "call" strategy holding an armed put pass a gate
                # checking calls, and open the second side.
                want = resolve_direction(strategy.params_json)
                armed = parse_occ_symbol(option_symbol or "")
                if armed is not None:
                    want = 'call' if armed.right == 'C' else 'put'
                opposed = self.db.query(Position).filter(
                    Position.user_id == user.id,
                    Position.symbol == symbol,
                    Position.strategy_id != strategy.id,
                    Position.qty > 0,
                ).all()
                for other in opposed:
                    parsed = parse_occ_symbol(other.option_symbol or "")
                    if parsed is None:
                        continue  # equity or unparseable — not a side conflict
                    held = 'call' if parsed.right == 'C' else 'put'
                    if held == want:
                        continue
                    msg = (
                        f"Entry skipped: strategy {other.strategy_id} already holds a "
                        f"{held} on {symbol} ({other.option_symbol}, qty={other.qty}) "
                        f"and this strategy trades {want}s. Refusing to hold both sides."
                    )
                    logger.info(msg)
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ENTRY_SKIPPED_OPPOSITE_SIDE",
                        title=f"Entry skipped: {symbol} held on the other side",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="info",
                        event_data={
                            "want": want,
                            "held": held,
                            "held_by_strategy_id": other.strategy_id,
                            "held_contract": other.option_symbol,
                        },
                    )
                    return OrderResult(success=False, message=msg)
                # Close the transaction this SELECT opened. The lockout above
                # rolls back deliberately so the session is not idle-in-
                # transaction across preview + place + await-fill; without this
                # the pass-through path silently undoes that.
                self.db.rollback()

            # An unconfirmed order means we may ALREADY be holding contracts the DB
            # cannot see. Buying again stacks a second position on an invisible first
            # one — and max_positions can't stop it, because there is no Position row
            # to count. Block entries until the reconcile tick resolves the order.
            # Sells fall through deliberately: an exit must never be blocked.
            if side == 'buy' and self.has_unconfirmed_orders(user.id, strategy.id):
                pending = sorted(self._unconfirmed_orders.get((user.id, strategy.id), {}))
                msg = (
                    f"Entry blocked for {symbol}: broker order(s) {', '.join(pending)} "
                    "unconfirmed — we may already hold contracts. Waiting for reconcile."
                )
                logger.warning(msg)
                block_key = (user.id, strategy.id)
                if block_key not in self._unconfirmed_block_logged:
                    self._unconfirmed_block_logged.add(block_key)
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ENTRY_BLOCKED_UNCONFIRMED",
                        title=f"Entry blocked (unconfirmed order): {symbol}",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="warning",
                        event_data={"unconfirmed_order_ids": pending},
                    )
                return OrderResult(success=False, message=msg)

            # Per-(user, symbol) order rate limit. Stops a runaway loop from
            # hammering the broker even if the strategy logic flips state every
            # tick. Independent of the broker rate limit.
            allowed, wait_s = self._check_order_rate_limit(user.id, symbol)
            if not allowed:
                msg = (
                    f"Order rate-limited for {symbol}: last submission was within "
                    f"{MIN_ORDER_INTERVAL_SECONDS:.1f}s ({wait_s:.1f}s remaining)"
                )
                logger.warning(msg)
                if self._should_log_throttle(user.id, symbol):
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ORDER_RATE_LIMITED",
                        title=f"Order throttled: {symbol}",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="warning",
                        event_data={"wait_seconds": round(wait_s, 2)},
                    )
                return OrderResult(success=False, message=msg)

            self._stamp_order_submitted(user.id, symbol)

            # Pre-flight broker preview — validates buying power, contract,
            # surfaces commission/fees. Aborts on any failure (fail-safe).
            # On a buy, this also acquires an in-process cash reservation so
            # concurrent signals can't double-spend; we MUST release it on
            # every exit below (try/finally).
            preview_ok, preview, preview_msg, reservation_id = await self._preview_or_abort(
                user=user,
                strategy=strategy,
                symbol=symbol,
                qty=qty,
                side=side,
                option_symbol=option_symbol,
                order_type=order_type,
                # MUST be the per-contract OPTION price we sized from — `estimated_price`
                # is the option mid ((bid+ask)/2, strategy_executor.py:292). `signal.price`
                # is the UNDERLYING (SPY ~751), and passing it made ORDER_PREVIEW_DRIFT
                # compare a stock price against an option premium: every order logged a
                # "drift" of ~-99.4%, which is just 4.83/751. That silently poisoned the
                # entry-drift dataset TODO B2 has been waiting on. Falls back to
                # signal.price for non-option orders, where they're the same thing.
                signal_price=estimated_price or signal.price,
            )
            if not preview_ok:
                return OrderResult(success=False, message=f"Order aborted: {preview_msg}")

            try:
                # Place order via TradingClientManager (handles paper/live routing)
                order_response = await self.trading_client.place_order(
                    user=user,
                    symbol=symbol,
                    qty=qty,
                    side=side,
                    order_type=order_type,
                    option_symbol=option_symbol,
                )

                if not order_response:
                    return OrderResult(
                        success=False,
                        message=f"Failed to place order for {symbol}"
                    )

                order_id = self._extract_order_id(order_response)

                # Wait for terminal broker status before mutating local position state.
                # Submission "ok"/"pending"/"open" only means the broker accepted the
                # request — we must confirm the fill before writing Trade/Position rows.
                # This makes entries symmetric with close_position()'s behavior and
                # eliminates the divergence where local thinks flat while broker holds
                # contracts (see incident 2026-05-04: 6 TSLA contracts unaccounted for).
                terminal_order = await self._await_terminal_order(order_id, user)
                if terminal_order is None:
                    # Remember it: the broker may still fill this. Until we know, block
                    # further entries for this strategy and re-poll on the reconcile tick
                    # so the Trade row gets backfilled with the real fill price.
                    self._mark_unconfirmed(
                        user.id, strategy.id, order_id,
                        {
                            "side": side,
                            "qty": qty,
                            "symbol": symbol,
                            "option_symbol": option_symbol,
                            "signal_price": estimated_price or signal.price,
                            "signal_type": signal.signal_type,
                            "signal_reason": signal.reason,
                            "placed_at": datetime.utcnow().isoformat(),
                        },
                    )
                    msg = (
                        f"Order {order_id} status not confirmed within timeout — "
                        "leaving local state untouched (next reconcile tick will sync). "
                        "Entries blocked for this strategy until it resolves."
                    )
                    logger.warning(msg)
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ORDER_UNCONFIRMED",
                        title=f"Order unconfirmed: {symbol}",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="warning",
                        event_data={"order_id": order_id, "side": side, "qty": qty},
                    )
                    return OrderResult(success=False, message=msg, order_id=order_id)

                terminal_status = (terminal_order.get("status") or "").lower()
                if terminal_status != "filled":
                    msg = (
                        f"Order {order_id} did not fill (status={terminal_status}). "
                        "Local position left untouched."
                    )
                    logger.error(msg)
                    # Record an audit Trade so the failed attempt shows in history.
                    failed_trade = Trade(
                        user_id=user.id,
                        strategy_id=strategy.id,
                        symbol=symbol,
                        side=side,
                        order_type=order_type,
                        qty=qty,
                        filled_qty=0,
                        price=estimated_price or signal.price or 0.0,
                        status='failed',
                        timestamp=datetime.utcnow(),
                        notes={
                            'signal_type': signal.signal_type,
                            'signal_reason': signal.reason,
                            'order_id': order_id,
                            'terminal_status': terminal_status,
                        },
                    )
                    self.db.add(failed_trade)
                    self.db.commit()
                    log_event(
                        db=self.db,
                        user_id=user.id,
                        event_type="ORDER_FAILED",
                        title=f"Order {terminal_status}: {side.upper()} {qty}x {symbol}",
                        detail=msg,
                        symbol=symbol,
                        strategy_id=strategy.id,
                        severity="error",
                        event_data={"order_id": order_id, "status": terminal_status},
                    )
                    return OrderResult(success=False, message=msg, order_id=order_id)

                # Confirmed filled — use the broker's actual fill data.
                filled_price = self._extract_filled_price(terminal_order, estimated_price or signal.price)
                filled_qty = self._extract_filled_qty(terminal_order, qty)

                # Live-test: the decisive record — estimate vs. broker's real fill.
                _lt_emit_order(
                    "filled",
                    order_id=order_id,
                    side=side,
                    symbol=symbol,
                    option_symbol=option_symbol,
                    signal_price=signal.price,
                    estimated_price=estimated_price,
                    broker_avg_fill_price=(terminal_order.get("avg_fill_price")
                                           if isinstance(terminal_order, dict) else None),
                    filled_price=filled_price,
                    filled_qty=filled_qty,
                    trading_mode=(user.selected_trading_mode or "paper"),
                )

                # Record trade in database
                trade = self._create_trade_record(
                    user=user,
                    strategy=strategy,
                    signal=signal,
                    qty=filled_qty,
                    price=filled_price,
                    order_id=order_id,
                    preview=preview,
                )

                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="ORDER_PLACED",
                    title=f"{side.upper()} {filled_qty}x {symbol}",
                    symbol=symbol,
                    strategy_id=strategy.id,
                    severity="info",
                    event_data={
                        "order_id": order_id,
                        "price": filled_price,
                        "qty": filled_qty,
                        "signal_type": signal.signal_type,
                    },
                )

                # Update or create position
                if signal.signal_type == 'entry':
                    self._update_position_entry(
                        user=user,
                        strategy=strategy,
                        symbol=symbol,
                        qty=filled_qty,
                        price=filled_price,
                        trade=trade,
                        option_symbol=option_symbol,
                    )
                elif signal.signal_type == 'exit':
                    self._update_position_exit(
                        user=user,
                        strategy=strategy,
                        symbol=symbol,
                        qty=filled_qty,
                        price=filled_price,
                        trade=trade,
                        option_symbol=option_symbol,
                    )

                logger.info(
                    f"Order executed successfully: {order_id} - {side} {filled_qty} {symbol} @ ${filled_price:.2f}"
                )

                return OrderResult(
                    success=True,
                    message=f"Order executed: {side} {filled_qty} {symbol} @ ${filled_price:.2f}",
                    order_id=order_id,
                    trade=trade,
                    filled_price=filled_price,
                    filled_qty=filled_qty
                )
            finally:
                # Release the cash reservation regardless of how the inner block
                # exited (success, early return, raised exception). Tradier's
                # cash_available reflects the order at this point — the reservation
                # was only needed to bridge the gap between balance fetch and
                # broker-side registration.
                self._release_buy_reservation(reservation_id)

        except Exception as e:
            logger.error(f"Error executing signal: {str(e)}", exc_info=True)
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="ORDER_FAILED",
                title=f"Order failed: {side.upper()} {qty}x {symbol}",
                detail=str(e),
                symbol=symbol,
                strategy_id=strategy.id,
                severity="error",
            )
            return OrderResult(
                success=False,
                message=f"Order execution failed: {str(e)}"
            )

    async def _await_terminal_order(
        self,
        order_id: Optional[str],
        user: User,
        timeout_s: float = 30.0,
        poll_interval_s: float = 1.5,
    ) -> Optional[Dict]:
        """Poll the broker for an order until it reaches a terminal status.

        Returns the order dict on terminal status, or None if the order id
        is missing, the broker is non-Tradier, or the timeout elapses.

        Terminal statuses per docs/tradier/accounts/order.md: filled,
        rejected, canceled, expired. Any other status (pending, open,
        partially_filled) means we keep waiting.
        """
        if not order_id:
            return None

        # Poll for terminal status on Tradier — for BOTH paper (sandbox) and
        # live. `get_client` returns a TradierClient in both modes, so both
        # support get_order and both MUST be polled: a live market order returns
        # no fill price on the submission response, so without polling we never
        # capture the real avg_fill_price AND execute_signal treats every live
        # order as unconfirmed (no fill recorded, no position update → the
        # engine believes it is flat while holding a live position, risking a
        # duplicate stacked entry on the next tick). If a client without
        # get_order is ever returned (a future non-Tradier broker) we fall through
        # to None and the caller treats the order as unconfirmed.
        try:
            client = self.trading_client.get_client(user)
        except Exception as e:
            logger.warning(f"Cannot poll order status — client unavailable: {e}")
            return None

        if not hasattr(client, "get_order"):
            logger.warning(
                "Trading client has no get_order(); skipping terminal poll "
                "(order will be treated as unconfirmed)"
            )
            return None

        terminal = _TERMINAL_ORDER_STATUSES
        deadline = asyncio.get_event_loop().time() + timeout_s

        # The account event stream pushes order state changes, so a fill is usually
        # known within milliseconds. We sleep on IT rather than on a blind timer: if it
        # reports terminal we wake immediately, and if it says nothing we fall through
        # to the REST poll exactly as before. The stream carries no side/symbol and
        # names its quantity field differently, so it is only a NOTIFICATION — the
        # canonical order still comes from REST below.
        from engine.tradier_account_stream import get_account_stream_manager
        stream = get_account_stream_manager()

        while asyncio.get_event_loop().time() < deadline:
            try:
                order = await asyncio.to_thread(client.get_order, order_id)
            except Exception as e:
                logger.warning(f"get_order({order_id}) failed: {e}")
                await asyncio.sleep(poll_interval_s)
                continue

            status = (order.get("status") or "").lower()
            if status in terminal:
                stream.forget(order_id)
                return order

            # Wake early if the stream reports terminal; otherwise this behaves as the
            # old fixed sleep. A False return means "don't know", never "it died".
            await stream.wait_for_terminal(order_id, timeout=poll_interval_s)

        stream.forget(order_id)
        return None

    def _extract_order_id(self, order_response: Dict) -> Optional[str]:
        """Extract order ID from a Tradier order response: { "id": 123456, "status": "ok" }"""
        if isinstance(order_response, dict) and 'id' in order_response:
            return str(order_response['id'])
        return str(order_response) if order_response else None

    def _extract_filled_price(
        self,
        order_response: Dict,
        estimated_price: Optional[float]
    ) -> float:
        """Extract filled price from a Tradier order.

        Tradier market orders return no fill price immediately — fall back to the
        mid-price estimate from market data so P&L tracking is reasonable.
        """
        if isinstance(order_response, dict) and order_response.get('avg_fill_price'):
            return float(order_response['avg_fill_price'])
        return estimated_price or 0.0

    def _extract_filled_qty(self, order_response: Dict, requested_qty: int) -> int:
        """Extract filled quantity from a Tradier order.

        NOTE: the ACCOUNT EVENT STREAM names this field `executed_quantity`, not
        `exec_quantity` — do not feed a stream event in here. The stream is only a
        notification; the canonical order always comes from REST get_order.
        """
        if isinstance(order_response, dict) and order_response.get('exec_quantity'):
            return int(float(order_response['exec_quantity']))
        # Assume full fill for market orders
        return requested_qty

    def _reconcile_exit_reason(
        self,
        reason: Optional[str],
        pnl: float,
        filled_price: float,
        entry_price: float,
    ) -> Optional[str]:
        """
        Sanity-check the exit signal reason against the realized P&L.

        Exit signals are evaluated on a price snapshot (bid for longs after the
        Fix-A change, but the bid can still pull between signal evaluation and
        fill). When the realized P&L disagrees with the signal — e.g. a "Take
        profit hit" signal but a losing fill — the bare signal reason is
        misleading on the events page. Rewrite to surface the divergence.
        """
        if not reason:
            return reason
        lower = reason.lower()
        if pnl < 0 and "take profit" in lower:
            return (
                f"Take-profit signal triggered, but market fill realized "
                f"P&L {pnl:+.2f} (filled @ {filled_price:.2f}, entry @ "
                f"{entry_price:.2f}). Bid likely pulled between signal and fill."
            )
        if pnl > 0 and "stop loss" in lower:
            return (
                f"Stop-loss signal triggered, but market fill realized "
                f"P&L {pnl:+.2f} (filled @ {filled_price:.2f}, entry @ "
                f"{entry_price:.2f}). Bid likely bounced between signal and fill."
            )
        return reason

    def _create_trade_record(
        self,
        user: User,
        strategy: Strategy,
        signal: Signal,
        qty: int,
        price: float,
        order_id: Optional[str],
        preview: Optional[Dict] = None,
    ) -> Trade:
        """Create a trade record in the database"""
        notes = {
            'signal_type': signal.signal_type,
            'signal_reason': signal.reason,
            'signal_confidence': signal.confidence,
            'indicators': signal.indicators,
            'order_id': order_id,
        }
        if preview:
            notes['preview'] = {
                'order_cost': preview.get('order_cost'),
                'commission': preview.get('commission'),
                'fees': preview.get('fees'),
                'margin_change': preview.get('margin_change'),
                'day_trades': preview.get('day_trades'),
            }

        trade = Trade(
            user_id=user.id,
            strategy_id=strategy.id,
            symbol=signal.symbol,
            side=signal.action,
            order_type='market',
            qty=qty,
            filled_qty=qty,
            price=price,
            status='executed',
            timestamp=datetime.utcnow(),
            notes=notes,
        )

        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)

        logger.info(f"Trade record created: ID={trade.id}, {signal.action} {qty} {signal.symbol}")
        return trade

    def _update_position_entry(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        qty: int,
        price: float,
        trade: Trade,
        option_symbol: Optional[str] = None,
    ):
        """Update or create position for entry trade.

        Uses row-level locking (SELECT FOR UPDATE) to prevent race conditions
        when multiple strategies might update the same position concurrently.
        """
        # Find the row for THIS CONTRACT, with a row-level lock.
        #
        # Keyed on option_symbol as well as the underlying: one row per contract,
        # not one row per ticker. Before 2026-08-25 a single SPY row was reused for
        # every strike ever traded (1,922 trades pointed at one row), so
        # `positions.option_symbol` always named the most recent contract and no
        # historical trade could be attributed to what it actually held.
        position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol,
            Position.option_symbol == option_symbol,
        ).with_for_update().first()  # Lock the row

        is_new = position is None

        if position and position.qty > 0:
            # This branch should be unreachable: execute_signal pre-flights an
            # entry-lockout. If we land here, the broker accepted the order
            # despite an open position (true race). Average so accounting matches
            # the contracts we actually own, but flag loudly.
            total_qty = position.qty + qty
            total_cost = (position.avg_entry_price * position.qty) + (price * qty)
            new_avg_price = total_cost / total_qty

            position.qty = total_qty
            position.avg_entry_price = new_avg_price
            position.current_price = price
            # Options contracts have a 100x multiplier (each contract = 100 shares)
            multiplier = 100 if is_option_symbol(option_symbol or position.option_symbol or symbol) else 1
            position.unrealized_pnl = (price - new_avg_price) * total_qty * multiplier
            if option_symbol and not position.option_symbol:
                position.option_symbol = option_symbol

            logger.critical(
                f"STACKED ENTRY (race condition): {symbol} now qty={total_qty}, "
                f"avg_price=${new_avg_price:.2f} — entry-lockout failed"
            )
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="POSITION_STACKED",
                title=f"Position stacked unexpectedly: {symbol}",
                detail="Entry placed despite open position — investigate race",
                symbol=symbol,
                strategy_id=strategy.id,
                severity="error",
                event_data={"qty": total_qty, "added": qty},
            )
        elif position:
            # Existing position with qty=0 (closed) — reuse the row for the new entry
            position.qty = qty
            position.avg_entry_price = price
            position.current_price = price
            position.unrealized_pnl = 0.0
            position.opened_at = datetime.utcnow()
            position.option_symbol = option_symbol
            position.peak_price = price
            position.trough_price = price
            is_new = True  # treat as a fresh open for event logging

            logger.info(f"Reopened position: {symbol} qty={qty}, price=${price:.2f}")
        else:
            # Create new position
            position = Position(
                user_id=user.id,
                strategy_id=strategy.id,
                symbol=symbol,
                option_symbol=option_symbol,
                qty=qty,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                opened_at=datetime.utcnow(),
                peak_price=price,
                trough_price=price,
            )
            self.db.add(position)
            # FLUSH before reading position.id. Without this the id is still None
            # and `trade.position_id` below silently stays NULL — the trade is
            # orphaned from its contract. This was survivable while a position row
            # was created twice in the app's lifetime (2 orphaned trades of 2,480);
            # with per-contract rows a row is created for every new contract, so
            # it would orphan the FIRST trade of every contract and defeat the
            # attribution this keying exists to provide.
            self.db.flush()

            logger.info(f"Created new position: {symbol} qty={qty}, price=${price:.2f}")

        # Link trade to position
        trade.position_id = position.id

        self.db.commit()
        self.db.refresh(position)

        if is_new:
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="POSITION_OPENED",
                title=f"Opened {symbol}",
                symbol=symbol,
                strategy_id=strategy.id,
                severity="success",
                event_data={"qty": qty, "price": price},
            )
            try:
                notify_position_opened(
                    user_prefs=user.notification_preferences,
                    symbol=symbol,
                    qty=qty,
                    price=price,
                    strategy_name=strategy.name,
                    option_symbol=option_symbol,
                )
            except Exception as e:
                logger.warning(f"Discord notify (open) failed: {e}")

        return position

    def _update_position_exit(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        qty: int,
        price: float,
        trade: Trade,
        option_symbol: Optional[str] = None,
    ):
        """Update position for exit trade.

        Uses row-level locking (SELECT FOR UPDATE) to prevent race conditions
        when multiple strategies might update the same position concurrently.
        """
        # Find the row for the contract being SOLD, with a row-level lock.
        # EXACT match on the contract only — no "closest open row" fallback.
        #
        # An earlier draft fell back to the open row for the underlying, meaning
        # to be lenient about legacy rows. It was not needed and was dangerous:
        # `_update_position_entry` writes `option_symbol` on every entry (both the
        # create and the qty=0 reuse branch), so an open row ALWAYS names the
        # contract it holds and the exact match always finds it. What the fallback
        # actually did was let an exit for a contract we do NOT hold decrement the
        # one we DO — booking the wrong contract's P&L at the wrong price.
        # Failing to find a row and logging is the safe outcome; silently closing
        # the wrong position is not.
        position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol,
            Position.option_symbol == option_symbol,
        ).with_for_update().first()  # Lock the row

        if not position:
            logger.warning(
                f"No position found for exit trade: {symbol} ({option_symbol})"
            )
            return None

        # Calculate P&L for this exit
        entry_price = position.avg_entry_price
        # Options contracts have a 100x multiplier (each contract = 100 shares)
        multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1
        exit_pnl = (price - entry_price) * qty * multiplier

        # Update trade with exit details
        trade.exit_price = price
        trade.exit_timestamp = datetime.utcnow()
        trade.pnl = exit_pnl - (trade.commission or 0.0)
        # Link the closing leg to the contract's row. This path never set it —
        # survivable only because live exits route through close_position (which
        # sets position_id at construction), but an unlinked sell is an
        # unattributable sell, which is the whole point of per-contract rows.
        trade.position_id = position.id

        # Reduce position quantity
        position.qty -= qty
        position.current_price = price

        fully_closed = False

        # If position fully closed, set unrealized P&L to 0
        if position.qty <= 0:
            position.qty = 0
            position.unrealized_pnl = 0.0
            fully_closed = True
            logger.info(f"Position fully closed: {symbol}, P&L=${exit_pnl:.2f}")
        else:
            # Recalculate unrealized P&L for remaining position
            # Options contracts have a 100x multiplier (each contract = 100 shares)
            multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1
            position.unrealized_pnl = (price - position.avg_entry_price) * position.qty * multiplier
            logger.info(
                f"Partial exit: {symbol}, closed {qty}, remaining {position.qty}, P&L=${exit_pnl:.2f}"
            )

        self.db.commit()
        self.db.refresh(position)
        self.db.refresh(trade)

        if fully_closed:
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="POSITION_CLOSED",
                title=f"Closed {symbol}  P&L {exit_pnl:+.2f}",
                symbol=symbol,
                strategy_id=strategy.id,
                severity="success" if exit_pnl >= 0 else "warning",
                event_data={"qty": qty, "exit_price": price, "pnl": exit_pnl},
            )
            try:
                notify_position_closed(
                    user_prefs=user.notification_preferences,
                    symbol=symbol,
                    qty=qty,
                    price=price,
                    pnl=exit_pnl,
                    strategy_name=strategy.name,
                    option_symbol=position.option_symbol,
                    entry_price=entry_price,
                )
            except Exception as e:
                logger.warning(f"Discord notify (close) failed: {e}")

        return position

    async def close_position(
        self,
        user: User,
        strategy: Strategy,
        position: Position,
        reason: str = "Manual close",
        option_symbol: Optional[str] = None,
    ) -> OrderResult:
        """
        Close an entire position

        Args:
            user: User object
            strategy: Strategy object
            position: Position to close
            reason: Reason for closing

        Returns:
            OrderResult with execution details
        """
        if position.qty <= 0:
            return OrderResult(
                success=False,
                message=f"Position {position.symbol} already closed"
            )

        # Determine order side (opposite of position)
        # If we have a long position (positive qty), we sell
        side = 'sell'

        logger.info(f"Closing position: {side} {position.qty} {position.symbol} - {reason}")

        # Per-(user, symbol) rate limit also applies to closes — same belt-and-
        # suspenders against runaway loops. Closes are usually triggered after
        # entries so they should normally pass the throttle.
        allowed, wait_s = self._check_order_rate_limit(user.id, position.symbol)
        if not allowed:
            msg = (
                f"Close rate-limited for {position.symbol}: last order was within "
                f"{MIN_ORDER_INTERVAL_SECONDS:.1f}s ({wait_s:.1f}s remaining)"
            )
            logger.warning(msg)
            if self._should_log_throttle(user.id, position.symbol):
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="ORDER_RATE_LIMITED",
                    title=f"Close throttled: {position.symbol}",
                    detail=msg,
                    symbol=position.symbol,
                    strategy_id=strategy.id,
                    severity="warning",
                    event_data={"wait_seconds": round(wait_s, 2)},
                )
            return OrderResult(success=False, message=msg)

        self._stamp_order_submitted(user.id, position.symbol)

        # Pre-flight preview for closes too — validates the contract is held,
        # surfaces commission/fees for accurate P&L. Sells skip the cash gate
        # and never acquire a reservation, so the 4th return slot is discarded.
        preview_ok, preview, preview_msg, _ = await self._preview_or_abort(
            user=user,
            strategy=strategy,
            symbol=position.symbol,
            qty=position.qty,
            side=side,
            option_symbol=option_symbol,
            order_type='market',
        )
        if not preview_ok:
            return OrderResult(success=False, message=f"Close aborted: {preview_msg}")

        try:
            # Place market order to close (routes via TradingClientManager)
            order_response = await self.trading_client.place_order(
                user=user,
                symbol=position.symbol,
                qty=position.qty,
                side=side,
                order_type='market',
                option_symbol=option_symbol,
            )

            if not order_response:
                return OrderResult(
                    success=False,
                    message=f"Failed to place closing order for {position.symbol}"
                )

            # Re-validate the response body for broker-level errors. Tradier
            # returns 200 with {"errors": ...} for application errors; the
            # client raises on those, but this is a defense-in-depth check
            # for any path that returns a dict with errors without raising.
            if isinstance(order_response, dict) and order_response.get("errors"):
                err = order_response["errors"]
                msg = f"Close rejected by broker: {err}"
                logger.error(msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="CLOSE_REJECTED",
                    title=f"Close rejected: {position.symbol}",
                    detail=str(err),
                    symbol=position.symbol,
                    strategy_id=strategy.id,
                    severity="error",
                )
                return OrderResult(success=False, message=msg)

            order_id = self._extract_order_id(order_response)

            # Poll Tradier for terminal status before mutating local position state.
            # Submission status of "ok"/"pending"/"open" only means accepted —
            # the order can still be rejected, canceled, or expire. We must
            # confirm it filled before zeroing local qty.
            terminal_order = await self._await_terminal_order(order_id, user)
            if terminal_order is None:
                # Could not confirm fill — leave local qty intact so reconciliation
                # can pick this up on the next 60s tick rather than us claiming
                # the position is closed when it may not be
                msg = (
                    f"Close order {order_id} status not confirmed within timeout — "
                    "leaving local position open for reconciliation"
                )
                logger.warning(msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="CLOSE_UNCONFIRMED",
                    title=f"Close unconfirmed: {position.symbol}",
                    detail=msg,
                    symbol=position.symbol,
                    strategy_id=strategy.id,
                    severity="warning",
                    event_data={"order_id": order_id},
                )
                return OrderResult(success=False, message=msg, order_id=order_id)

            terminal_status = (terminal_order.get("status") or "").lower()
            if terminal_status != "filled":
                msg = (
                    f"Close order {order_id} did not fill (status={terminal_status}). "
                    "Local position left open."
                )
                logger.error(msg)
                log_event(
                    db=self.db,
                    user_id=user.id,
                    event_type="CLOSE_FAILED",
                    title=f"Close failed: {position.symbol}",
                    detail=msg,
                    symbol=position.symbol,
                    strategy_id=strategy.id,
                    severity="error",
                    event_data={"order_id": order_id, "status": terminal_status},
                )
                return OrderResult(success=False, message=msg, order_id=order_id)

            filled_price = self._extract_filled_price(terminal_order, position.current_price)
            filled_qty = self._extract_filled_qty(terminal_order, position.qty)

            # Calculate final P&L
            # Options contracts have a 100x multiplier (each contract = 100 shares)
            multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1
            pnl = (filled_price - position.avg_entry_price) * filled_qty * multiplier

            # Create trade record
            close_notes = {
                'signal_type': 'exit',
                'signal_reason': reason,
                'order_id': order_id,
                # WHICH contract this closed. The Position row cannot answer that
                # later: _update_position_entry reuses a qty=0 row for the next
                # entry, overwriting option_symbol. Trade 2408 (2026-07-31) closed
                # SPY260731C00745000 but its position row now reads
                # SPY260825C00764000 — a month-later strike. Reports that label a
                # trade off the position row therefore show the wrong contract.
                'option_symbol': option_symbol or position.option_symbol,
            }
            if preview:
                close_notes['preview'] = {
                    'order_cost': preview.get('order_cost'),
                    'commission': preview.get('commission'),
                    'fees': preview.get('fees'),
                    'margin_change': preview.get('margin_change'),
                    'day_trades': preview.get('day_trades'),
                }
            trade = Trade(
                user_id=user.id,
                strategy_id=strategy.id,
                position_id=position.id,
                symbol=position.symbol,
                side=side,
                order_type='market',
                qty=filled_qty,
                filled_qty=filled_qty,
                price=position.avg_entry_price,  # Entry price for reporting
                exit_price=filled_price,
                exit_timestamp=datetime.utcnow(),
                pnl=pnl,
                status='executed',
                timestamp=datetime.utcnow(),
                notes=close_notes,
            )

            self.db.add(trade)

            # Close position
            position.qty = 0
            position.current_price = filled_price
            position.unrealized_pnl = 0.0

            self.db.commit()

            logger.info(
                f"Position closed: {position.symbol}, P&L=${pnl:.2f}, "
                f"Price=${filled_price:.2f}"
            )

            detail_text = self._reconcile_exit_reason(
                reason, pnl, filled_price, position.avg_entry_price
            )
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="POSITION_CLOSED",
                title=f"Closed {position.symbol}  P&L {pnl:+.2f}",
                detail=detail_text,
                symbol=position.symbol,
                strategy_id=strategy.id,
                severity="success" if pnl >= 0 else "warning",
                event_data={"qty": filled_qty, "exit_price": filled_price, "pnl": pnl, "order_id": order_id},
            )
            try:
                notify_position_closed(
                    user_prefs=user.notification_preferences,
                    symbol=position.symbol,
                    qty=filled_qty,
                    price=filled_price,
                    pnl=pnl,
                    strategy_name=strategy.name,
                    option_symbol=option_symbol or position.option_symbol,
                    entry_price=position.avg_entry_price,
                )
            except Exception as e:
                logger.warning(f"Discord notify (close) failed: {e}")

            return OrderResult(
                success=True,
                message=f"Position closed: {position.symbol} P&L=${pnl:.2f}",
                order_id=order_id,
                trade=trade,
                filled_price=filled_price,
                filled_qty=filled_qty
            )

        except Exception as e:
            logger.error(f"Error closing position: {str(e)}", exc_info=True)
            log_event(
                db=self.db,
                user_id=user.id,
                event_type="ORDER_FAILED",
                title=f"Failed to close {position.symbol}",
                detail=str(e),
                symbol=position.symbol,
                strategy_id=strategy.id,
                severity="error",
            )
            return OrderResult(
                success=False,
                message=f"Failed to close position: {str(e)}"
            )

    def update_position_prices(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        current_price: float,
        option_symbol: Optional[str] = None,
    ):
        """Update current price and unrealized P&L for ONE position.

        `option_symbol` selects which contract to mark. Callers that hold a
        Position already should pass its `option_symbol` — marking "the first row
        for SPY" was safe only while a single row existed per ticker, and would
        now silently mark the wrong contract.

        Uses row-level locking to prevent race conditions during concurrent updates.
        """
        q = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol,
        )
        if option_symbol is not None:
            q = q.filter(Position.option_symbol == option_symbol)
        else:
            # No contract given — only ever mark something actually open, so a
            # closed historical row can never be revived with a stale price.
            q = q.filter(Position.qty > 0)

        position = q.with_for_update().first()  # Lock the row

        if not position or position.qty <= 0:
            return

        # Update current price
        position.current_price = current_price

        # Recalculate unrealized P&L
        # Options contracts have a 100x multiplier (each contract = 100 shares)
        multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1
        position.unrealized_pnl = (current_price - position.avg_entry_price) * position.qty * multiplier

        self.db.commit()

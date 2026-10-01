"""
Risk Manager - Pre-trade validation and risk controls
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from models import User, Strategy, Position, Trade, RiskEvent
from engine import account_state
from config import TradingMode
from notifications.discord import (
    notify_strategy_blocked,
    notify_strategy_bleeding,
    notify_strategy_recovered,
    notify_strategy_unblocked,
)
from utils.market_hours import (
    HALT_MODE_FLATTEN,
    market_day_start_utc,
    trading_halt_state,
    user_day_start_utc,
)

logger = logging.getLogger(__name__)


class RiskCheckResult:
    """Result of a risk check operation"""
    def __init__(
        self,
        approved: bool,
        reason: str = "",
        suggested_qty: Optional[int] = None,
        code: Optional[str] = None,
    ):
        self.approved = approved
        self.reason = reason
        self.suggested_qty = suggested_qty
        # Machine-readable reason, set only on the entry blocks that are NOT
        # self-evident from the screen. Drives the "why has this strategy gone
        # quiet?" notification and the Blocked badge. `None` means "no code
        # assigned to this rejection", never "nothing is wrong".
        self.code = code


class RiskManager:
    """
    Manages all risk-related operations:
    - Position sizing based on account size and risk parameters
    - Pre-trade validation against risk limits
    - Daily loss limit enforcement
    - Maximum drawdown monitoring
    - Position limit enforcement
    """

    # Blocks worth announcing: the strategy still reads as Active, still
    # evaluates, still generates signals — and silently opens nothing, with
    # nothing on screen saying why. Deliberately EXCLUDES the self-evident
    # ones: an inactive strategy, a halt the user pressed themselves, and the
    # position cap (normal operation, fires constantly).
    _NOTIFIABLE_BLOCKS: Dict[str, str] = {
        "mode_mismatch": "Trading mode mismatch",
        "account_daily_loss": "Account daily loss cap",
        "strategy_daily_loss": "Strategy daily loss limit",
        "max_drawdown": "Drawdown limit",
    }

    # (user_id, strategy_id) -> {"code", "since", "suppressed"} while entries
    # are blocked for one of the reasons above. Mirrors
    # OrderManager._cash_block_state: announce the transition IN, count the
    # repeats quietly, announce the recovery. 2026-09-02 produced 321 entry
    # signals in a single day — one alert per rejection is 321 Discord posts.
    _entry_block_state: Dict[Tuple[int, int], Dict] = {}

    # (user_id, strategy_id) -> {"since", "drawdown"} while a strategy is past
    # its drawdown threshold but configured NOT to block. Same announce-once
    # discipline; cleared with hysteresis at 80% of the threshold so a strategy
    # hovering on the line does not alternate alerts.
    _drawdown_bleed_state: Dict[Tuple[int, int], Dict] = {}

    def __init__(self, db: Session):
        self.db = db

    def _note_entry_block(
        self, user: User, strategy: Strategy, result: RiskCheckResult
    ) -> None:
        """Record that entries are blocked; announce only the transition in.

        Best-effort and never raises: a notification problem must not be able
        to change whether a trade is allowed.
        """
        code = result.code
        if code not in self._NOTIFIABLE_BLOCKS:
            return
        key = (user.id, strategy.id)
        state = self._entry_block_state.get(key)
        if state and state.get("code") == code:
            state["suppressed"] += 1
            return

        self._entry_block_state[key] = {
            "code": code,
            "since": datetime.utcnow(),
            "suppressed": 0,
        }
        logger.warning(
            f"Strategy {strategy.id} ({strategy.name}) entries BLOCKED "
            f"[{code}]: {result.reason} — repeats will be counted quietly"
        )
        try:
            notify_strategy_blocked(
                user.notification_preferences,
                strategy_name=strategy.name,
                headline=self._NOTIFIABLE_BLOCKS[code],
                detail=result.reason,
            )
        except Exception as e:  # pragma: no cover - notification is best-effort
            logger.warning(f"Blocked-strategy notification failed: {e}")

    def _note_entry_clear(self, user: User, strategy: Strategy) -> None:
        """Entries are possible again — announce the recovery once."""
        state = self._entry_block_state.pop((user.id, strategy.id), None)
        if not state:
            return
        code = state.get("code")
        suppressed = state.get("suppressed", 0)
        logger.info(
            f"Strategy {strategy.id} ({strategy.name}) entries RESUMED "
            f"[was {code}] — {suppressed} entries were skipped while blocked"
        )
        try:
            notify_strategy_unblocked(
                user.notification_preferences,
                strategy_name=strategy.name,
                headline=self._NOTIFIABLE_BLOCKS.get(code, "Entries blocked"),
                skipped=suppressed,
            )
        except Exception as e:  # pragma: no cover - notification is best-effort
            logger.warning(f"Unblocked-strategy notification failed: {e}")

    def _note_drawdown_bleed(
        self,
        user: User,
        strategy: Strategy,
        drawdown: float,
        limit: float,
        peak: float,
        cumulative: float,
    ) -> None:
        """Alert-only drawdown: the strategy is bleeding but still trading.

        Announced once, on the transition over the threshold. This runs inside
        the entry path, which fired 321 times in a day on 2026-09-02 — one post
        per evaluation would be unusable.
        """
        key = (user.id, strategy.id)
        if self._drawdown_bleed_state.get(key):
            return
        self._drawdown_bleed_state[key] = {
            "since": datetime.utcnow(),
            "drawdown": drawdown,
        }
        logger.warning(
            f"Strategy {strategy.id} ({strategy.name}) BLEEDING: "
            f"${drawdown:.2f} below peak (threshold ${limit:.2f}) — "
            f"alert only, entries continue"
        )
        try:
            notify_strategy_bleeding(
                user.notification_preferences,
                strategy_name=strategy.name,
                drawdown=drawdown,
                limit=limit,
                peak=peak,
                cumulative=cumulative,
            )
        except Exception as e:  # pragma: no cover - notification is best-effort
            logger.warning(f"Drawdown-bleed notification failed: {e}")

    def _clear_drawdown_bleed(
        self, user: User, strategy: Strategy, drawdown: float
    ) -> None:
        """Climbed back clear of the threshold — close the alert out."""
        state = self._drawdown_bleed_state.pop((user.id, strategy.id), None)
        if not state:
            return
        logger.info(
            f"Strategy {strategy.id} ({strategy.name}) drawdown recovered to "
            f"${drawdown:.2f} (was ${state['drawdown']:.2f})"
        )
        try:
            notify_strategy_recovered(
                user.notification_preferences,
                strategy_name=strategy.name,
                drawdown=drawdown,
                was=state["drawdown"],
            )
        except Exception as e:  # pragma: no cover - notification is best-effort
            logger.warning(f"Drawdown-recovered notification failed: {e}")

    def get_entry_block_status(self, user: User, strategy: Strategy) -> Dict:
        """Read-only: would new entries be refused right now, and why?

        Runs the same private checks `validate_pre_trade` runs, in the same
        order, so the badge cannot disagree with the engine. Writes nothing,
        commits nothing, notifies nothing — it is safe to call from a GET.

        Only the non-obvious gates are evaluated. "Inactive" and "you halted
        trading" are already on the screen and are not this function's job.
        """
        if not strategy.is_active:
            return {"blocked": False, "code": None, "reason": None}

        if user.selected_trading_mode == TradingMode.LIVE and strategy.is_paper_trading:
            return {
                "blocked": True,
                "code": "mode_mismatch",
                "reason": "Paper strategy cannot run in live trading mode",
            }

        for check in (
            self._check_user_daily_loss_limit(user, "buy"),
            self._check_daily_loss_limit(user, strategy),
            self._check_max_drawdown(user, strategy),
        ):
            if not check.approved:
                return {
                    "blocked": True,
                    "code": check.code,
                    "reason": check.reason,
                }

        return {"blocked": False, "code": None, "reason": None}

    @staticmethod
    def _account_base(user: User) -> float:
        """The account value that sizing and every loss / drawdown cap are a
        percentage of: the START-OF-DAY value from engine/account_state, one
        figure for every worker all day (docs/sizing-basis-design-2026-09-29.md).

        Falls back to the stored `user.account_size_usd` (the old source, which
        only the dashboard updates) only while today's value is unknown — before
        the first refresh of the ET day, or when the broker can't be read.
        """
        v = account_state.day_start_equity(user.id, account_state.mode_of(user))
        if v is not None and v > 0:
            return v
        return float(user.account_size_usd or 10000)

    def calculate_position_size(
        self,
        user: User,
        strategy: Strategy,
        current_price: float,
        max_loss_per_trade: Optional[float] = None
    ) -> int:
        """
        Calculate appropriate position size based on:
        - User's account size
        - Max trade percentage
        - Strategy's position sizing rules
        - Risk per trade

        Args:
            user: User object with account settings
            strategy: Strategy object with risk parameters
            current_price: Current price of the instrument
            max_loss_per_trade: Optional override for max loss

        Returns:
            int: Number of contracts/shares to trade
        """
        # Get account size
        account_size = self._account_base(user)

        # Get max trade percentage (default 2% if not set)
        max_trade_pct = float(user.max_trade_percentage or 2.0)

        # Calculate max capital to allocate to this trade
        max_capital = account_size * (max_trade_pct / 100.0)

        # Strategy-specific risk percentage
        strategy_risk_pct = float(strategy.params_json.get('risk_per_trade_pct', 1.0))

        # Use the more conservative of user and strategy risk limits
        effective_risk_pct = min(max_trade_pct, strategy_risk_pct)
        effective_capital = account_size * (effective_risk_pct / 100.0)

        # Calculate quantity based on current price
        if current_price <= 0:
            logger.warning(f"Invalid price {current_price} for position sizing")
            return 0

        # For options: more conservative sizing due to theta decay.
        # ONE definition, on the model — see Strategy.trades_options for why.
        _is_options = strategy.trades_options
        if _is_options:
            # Limit to max capital / (price * safety factor)
            safety_factor = 2.0  # More conservative for options
            max_contracts = int(effective_capital / (current_price * 100 * safety_factor))
        else:
            # For stocks: standard calculation
            max_contracts = int(effective_capital / current_price)

        # Apply strategy max positions
        strategy_max = strategy.params_json.get('max_contracts', 3)
        final_qty = min(max_contracts, strategy_max)

        one_unit_cost = current_price * 100 if _is_options else current_price

        # Ensure at least 1 if we have enough capital for one unit
        if final_qty < 1 and effective_capital >= one_unit_cost:
            final_qty = 1

        # Absolute dollar ceiling on the position.
        #
        # APPLIED LAST, ON PURPOSE. The "at least 1" rule above is a floor that
        # ignores cost — it grants one unit whenever `effective_capital` covers
        # it. A cap checked before that floor would be silently overridden by it
        # and enforce nothing. Most-restrictive-bound wins, so the ceiling has to
        # be the final word, and it must be allowed to take the answer to zero.
        #
        # OPT-IN. Absent, None, or non-positive means NO CAP — not "cap at zero".
        # This matters: the key shipped in every template but was read by no code
        # (audited 2026-09-08), so every existing strategy carries a value that
        # has never been enforced. Turning enforcement on with those values live
        # would have silently blocked real trades — on 2026-09-08 the $500
        # template value would have rejected the session's best entry, a single
        # SPY 773 put at $5.72 ($572 > $500). Existing strategies are therefore
        # set to None, and the cap is something you switch on deliberately when
        # the account is large enough for it to bind on purpose.
        max_usd = strategy.params_json.get('max_position_size_usd')
        if max_usd is not None and float(max_usd) > 0:
            affordable = int(float(max_usd) / one_unit_cost)
            if affordable < final_qty:
                logger.info(
                    f"Position capped by max_position_size_usd=${float(max_usd):,.2f}: "
                    f"{final_qty} -> {affordable} "
                    f"(one unit costs ${one_unit_cost:,.2f})"
                )
            final_qty = min(final_qty, affordable)

        logger.info(
            f"Position sizing: account=${account_size}, risk={effective_risk_pct}%, "
            f"price=${current_price}, calculated qty={final_qty}"
        )

        return max(0, final_qty)

    def validate_pre_trade(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        qty: int,
        estimated_price: float,
        side: str
    ) -> RiskCheckResult:
        """
        Comprehensive pre-trade validation:
        - Check if trading mode allows this trade
        - Verify daily loss limits not exceeded
        - Check max positions limit
        - Validate position size is reasonable
        - Check max drawdown limits

        Args:
            user: User object
            strategy: Strategy being executed
            symbol: Trading symbol
            qty: Proposed quantity
            estimated_price: Estimated execution price
            side: 'buy' or 'sell'

        Returns:
            RiskCheckResult with approval status and reason
        """
        # 1. Check if strategy is active
        if not strategy.is_active:
            return RiskCheckResult(False, "Strategy is not active")

        # 2. Check trading mode consistency
        if user.selected_trading_mode == TradingMode.LIVE and strategy.is_paper_trading:
            mode_check = RiskCheckResult(
                False,
                "Cannot execute paper strategy in live trading mode",
                code="mode_mismatch",
            )
            self._note_entry_block(user, strategy, mode_check)
            return mode_check

        # 2.4. Account-wide manual halt ("done trading today"). Checked before
        # the loss caps because it is unconditional — if the user has called it
        # a day we don't need to price anything to know the answer. Same
        # entries-only shape as the loss cap: `side='sell'` is never blocked,
        # so every open position stays closeable through the engine.
        halt_check = self._check_user_trading_halt(user, side)
        if not halt_check.approved:
            self._log_account_risk_event(
                user, strategy, "user_trading_halt",
                halt_check.reason, "trade_rejected"
            )
            return halt_check

        # 2.5. Account-wide daily loss cap (entries-only halt across ALL of
        # the user's strategies). Most-restrictive bound: this gate is
        # checked before per-strategy limits so if the account is halted
        # we don't bother probing strategy-level state. Exits (`side='sell'`)
        # are never blocked here — closing existing positions must always
        # be possible even when the cap is breached.
        account_loss_check = self._check_user_daily_loss_limit(user, side)
        if not account_loss_check.approved:
            self._log_account_risk_event(
                user, strategy, "user_daily_loss_limit",
                account_loss_check.reason, "trade_rejected"
            )
            self._note_entry_block(user, strategy, account_loss_check)
            return account_loss_check

        # 3. Check daily loss limit
        daily_loss_check = self._check_daily_loss_limit(user, strategy, side)
        if not daily_loss_check.approved:
            self._log_risk_event(
                user, strategy, "daily_loss_limit", "critical",
                daily_loss_check.reason, "trade_rejected"
            )
            self._note_entry_block(user, strategy, daily_loss_check)
            return daily_loss_check

        # 4. Check maximum drawdown
        drawdown_check = self._check_max_drawdown(user, strategy, side)
        if not drawdown_check.approved:
            self._log_risk_event(
                user, strategy, "max_drawdown", "critical",
                drawdown_check.reason, "trade_rejected"
            )
            self._note_entry_block(user, strategy, drawdown_check)
            return drawdown_check

        # 5. Check position limits
        position_limit_check = self._check_position_limits(user, strategy, side)
        if not position_limit_check.approved:
            self._log_risk_event(
                user, strategy, "position_limit", "warning",
                position_limit_check.reason, "trade_rejected"
            )
            return position_limit_check

        # 6. Validate position size
        calculated_qty = self.calculate_position_size(user, strategy, estimated_price)
        if qty > calculated_qty * 1.5:  # 50% buffer for minor variations
            return RiskCheckResult(
                False,
                f"Requested quantity {qty} exceeds calculated safe size {calculated_qty}",
                suggested_qty=calculated_qty
            )

        # 7. Check if we have an existing position in this symbol.
        # Underlying-keyed on purpose — concentration is exposure to SPY, not to
        # one strike. But it must select an OPEN row: rows are per-contract now,
        # so a bare .first() could return a closed one and skip the check
        # entirely while a position was genuinely open.
        existing_position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol,
            Position.qty > 0,
        ).first()

        if existing_position and existing_position.qty > 0:
            # Already have a position - validate we're not over-concentrating
            total_qty = existing_position.qty + qty
            if total_qty > calculated_qty * 2:
                return RiskCheckResult(
                    False,
                    f"Total position size {total_qty} would exceed risk limits"
                )

        # All checks passed. If this strategy was in a notifiable blocked
        # state, it has just come back — announce the recovery once.
        self._note_entry_clear(user, strategy)

        logger.info(
            f"Pre-trade validation PASSED: {symbol} {side} {qty} @ ${estimated_price}"
        )
        return RiskCheckResult(True, "All risk checks passed")

    def _check_user_trading_halt(self, user: User, side: str = "buy") -> RiskCheckResult:
        """Account-wide manual halt for the current market day.

        The user pressed "done for the day". Both halt modes reject new
        entries; they differ only in what happens to positions already open,
        and that half is handled where exits are decided
        (`signal_generator.forced_exit_time_et`) — not here. This method's only
        job is the entry side.

        Entries-only, for the same reason the loss cap is: blocking `sell`
        would strand open positions with no engine path out, which is strictly
        worse than whatever made the user stop trading.

        Composes with every other gate by being purely additive — it can only
        reject a buy that would otherwise pass, never approve one that another
        gate rejects."""
        if side != "buy":
            return RiskCheckResult(True)

        halted, mode = trading_halt_state(user)
        if not halted:
            return RiskCheckResult(True)

        detail = (
            "open positions are being closed at market"
            if mode == HALT_MODE_FLATTEN
            else "open positions keep running their stop/target"
        )
        return RiskCheckResult(
            False,
            f"Trading halted for the day by user request ({mode}): {detail}. "
            f"New entries are blocked until the next market day."
        )

    def _check_user_daily_loss_limit(self, user: User, side: str = "buy") -> RiskCheckResult:
        """Account-wide daily loss cap. Sums realized PnL across all the
        user's strategies for today (closing legs that filled today) plus
        the unrealized PnL of every currently open position. Rejects new
        entries once `today_pnl < -(account_size * daily_loss_limit_pct/100)`.

        Entries-only: when `side != 'buy'` we always approve so users can
        still close out existing positions through the engine when the cap
        is breached. Force-closing converts paper drawdown into realized,
        which is usually worse — see TODO #5 decision."""
        if side != "buy":
            return RiskCheckResult(True)

        daily_loss_limit_pct = float(user.daily_loss_limit_pct or 0)
        if daily_loss_limit_pct <= 0:
            return RiskCheckResult(True)

        # Trading gate: anchor "today" to the market (ET) day, not UTC midnight.
        today_start = market_day_start_utc()

        realized = self.db.query(func.sum(Trade.pnl)).filter(
            Trade.user_id == user.id,
            Trade.timestamp >= today_start,
            Trade.status == 'executed',
            Trade.pnl.isnot(None),
        ).scalar() or 0.0

        unrealized = self.db.query(func.sum(Position.unrealized_pnl)).filter(
            Position.user_id == user.id,
            Position.qty > 0,
        ).scalar() or 0.0

        today_pnl = float(realized) + float(unrealized)

        account_size = self._account_base(user)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        if today_pnl < -daily_loss_limit:
            return RiskCheckResult(
                False,
                f"Account daily loss cap reached: ${today_pnl:.2f} "
                f"(limit: ${-daily_loss_limit:.2f}). "
                f"New entries halted; existing positions can still be closed.",
                code="account_daily_loss",
            )

        if today_pnl < -(daily_loss_limit * 0.8):
            logger.warning(
                f"User {user.id} approaching account daily loss cap: "
                f"${today_pnl:.2f} / ${-daily_loss_limit:.2f}"
            )

        return RiskCheckResult(True)

    def _log_account_risk_event(
        self,
        user: User,
        strategy: Strategy,
        event_type: str,
        reason: str,
        action_taken: str,
    ) -> None:
        """Account-cap-specific risk-event writer that uses `details` JSON
        rather than the legacy `_log_risk_event` (which references a `message`
        column that doesn't exist on the model). Wrapped in try/except so a
        logging hiccup never blocks the actual trade-rejection return."""
        try:
            risk_event = RiskEvent(
                user_id=user.id,
                strategy_id=strategy.id if strategy is not None else None,
                event_type=event_type,
                severity="critical",
                action_taken=action_taken,
                details={"reason": reason},
            )
            self.db.add(risk_event)
            self.db.commit()
        except Exception as exc:  # pragma: no cover - logging must never crash trade flow
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"Failed to persist {event_type} risk event: {exc}")
        logger.warning(f"User {user.id} entry rejected ({event_type}): {reason}")

    def _check_daily_loss_limit(
        self, user: User, strategy: Strategy, side: str = "buy"
    ) -> RiskCheckResult:
        """Check if daily loss limit has been exceeded.

        Entries-only, matching `_check_user_daily_loss_limit` and
        `_check_user_trading_halt`: a sell is never blocked, so a breached cap
        can never strand an open position. Unreachable today — exits run
        through `close_position`, which does not call `validate_pre_trade` —
        but a risk gate that can refuse an exit is a landmine, not a feature.
        """
        if side != "buy":
            return RiskCheckResult(True)

        # Trading gate: anchor "today" to the market (ET) day, not UTC midnight.
        today_start = market_day_start_utc()

        today_pnl = self.db.query(func.sum(Trade.pnl)).filter(
            Trade.user_id == user.id,
            Trade.strategy_id == strategy.id,
            Trade.timestamp >= today_start,
            Trade.status == 'executed'
        ).scalar() or 0.0

        # Default daily loss limit: 5% of account size
        account_size = self._account_base(user)
        daily_loss_limit_pct = strategy.params_json.get('daily_loss_limit_pct', 5.0)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        if today_pnl < -daily_loss_limit:
            return RiskCheckResult(
                False,
                f"Daily loss limit exceeded: ${today_pnl:.2f} (limit: ${-daily_loss_limit:.2f})",
                code="strategy_daily_loss",
            )

        # Warning if approaching limit (80%)
        if today_pnl < -(daily_loss_limit * 0.8):
            logger.warning(
                f"Approaching daily loss limit: ${today_pnl:.2f} / ${-daily_loss_limit:.2f}"
            )

        return RiskCheckResult(True)

    def _check_max_drawdown(
        self, user: User, strategy: Strategy, side: str = "buy"
    ) -> RiskCheckResult:
        """Block new entries while the strategy sits too far below its own
        high-water mark.

        Entries-only — a sell is never blocked. See `_check_daily_loss_limit`.

        Measures the CURRENT drawdown — how far under its peak the cumulative
        P&L is right now — and not, as this did before, the worst drawdown ever
        recorded. That distinction is the whole fix. `max_drawdown` was a
        running maximum: it only ever rose, nothing reset it, and the query has
        no date filter, so a single bad stretch retired the strategy for the
        rest of its life even after it recovered to new all-time highs. Nothing
        surfaced that anywhere — the strategy stayed "Active" and silently
        stopped opening positions.

        Measured 2026-09-05: strategy 3 carried $119.00 of worst-ever drawdown
        against a $121.43 limit. One $3 loser from being permanently retired,
        with no warning and no way to clear it short of editing the database.

        Recovery is the point. Win the drawdown back and entries resume.

        Deliberate consequence: this gate is now strictly more permissive than
        before (current drawdown can never exceed worst-ever). That is the
        intent — the old bound was not a risk control, it was a latch.

        Two settings, because warning and blocking are different decisions:

          `max_drawdown_pct`    the threshold, as a % of account size.
                                <= 0 turns the whole thing off — no alert,
                                no block, and no database query.
          `max_drawdown_block`  whether crossing the threshold STOPS entries
                                (True, the default) or only raises an alert
                                (False).

        Alert-only is the useful mode on a small account. Blocking has a trap:
        the drawdown can only shrink when a trade CLOSES, a trade can only
        close if it was OPENED, and opening is exactly what the block prevents
        — so a blocked strategy with nothing open cannot recover by trading.
        With `max_drawdown_block=False` the strategy keeps trading, so it can
        climb out on its own and the alert is genuinely self-clearing.
        """
        if side != "buy":
            return RiskCheckResult(True)

        # Read the settings BEFORE the query: a disabled gate must cost nothing.
        # This loads the strategy's entire trade history, and it runs on every
        # entry attempt — 321 of them on 2026-09-02 alone.
        params = strategy.params_json or {}
        max_drawdown_limit_pct = float(params.get('max_drawdown_pct', 10.0) or 0)
        if max_drawdown_limit_pct <= 0:
            return RiskCheckResult(True)  # gate switched off entirely

        # Ordered explicitly. A cumulative running total is meaningless if the
        # rows arrive in whatever order the database felt like returning them,
        # and the previous form relied on exactly that.
        all_trades = self.db.query(Trade).filter(
            Trade.user_id == user.id,
            Trade.strategy_id == strategy.id,
            Trade.status == 'executed'
        ).order_by(Trade.timestamp).all()

        if not all_trades:
            return RiskCheckResult(True)  # No trade history yet

        cumulative_pnl = 0.0
        peak_pnl = 0.0
        for trade in all_trades:
            cumulative_pnl += float(trade.pnl or 0.0)
            if cumulative_pnl > peak_pnl:
                peak_pnl = cumulative_pnl

        # Distance below the high-water mark as of the last closed trade.
        # Zero whenever the strategy is at a new peak.
        current_drawdown = peak_pnl - cumulative_pnl

        account_size = self._account_base(user)
        max_drawdown_limit = account_size * (max_drawdown_limit_pct / 100.0)

        # Defaults to True so any strategy that has not opted out keeps the
        # behaviour it has today. Turning enforcement off is always explicit.
        blocks = bool(params.get('max_drawdown_block', True))

        if current_drawdown > max_drawdown_limit:
            if blocks:
                return RiskCheckResult(
                    False,
                    f"Drawdown limit reached: ${current_drawdown:.2f} below peak "
                    f"(limit: ${max_drawdown_limit:.2f}). New entries paused until the "
                    f"strategy recovers; open positions are unaffected.",
                    code="max_drawdown",
                )
            # Alert-only: say so once, then let the strategy carry on trading.
            self._note_drawdown_bleed(
                user, strategy, current_drawdown, max_drawdown_limit, peak_pnl, cumulative_pnl
            )
            return RiskCheckResult(True)

        # Hysteresis. Recovering to exactly the threshold would re-alert on the
        # next tick that dips back over it; the bleed is only "cleared" once the
        # strategy has climbed meaningfully clear of it.
        if current_drawdown < (max_drawdown_limit * 0.8):
            self._clear_drawdown_bleed(user, strategy, current_drawdown)
        elif current_drawdown > (max_drawdown_limit * 0.8):
            logger.warning(
                f"Strategy {strategy.id} approaching drawdown limit: "
                f"${current_drawdown:.2f} / ${max_drawdown_limit:.2f}"
            )

        return RiskCheckResult(True)

    def _check_position_limits(
        self, user: User, strategy: Strategy, side: str = "buy"
    ) -> RiskCheckResult:
        """Check if we're at maximum number of open positions.

        Entries-only. Blocking a sell here would be the worst of the three:
        being AT the position cap is precisely when you most need to close
        something.
        """
        if side != "buy":
            return RiskCheckResult(True)

        open_positions = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.qty > 0
        ).count()

        max_positions = strategy.max_positions or 3

        if open_positions >= max_positions:
            return RiskCheckResult(
                False,
                f"Maximum positions limit reached: {open_positions}/{max_positions}"
            )

        return RiskCheckResult(True)

    def _log_risk_event(
        self,
        user: User,
        strategy: Strategy,
        event_type: str,
        severity: str,
        message: str,
        action_taken: str
    ):
        """Log a risk event to the database.

        `RiskEvent` has no `message` column — it carries `details` JSON. This
        passed `message=` anyway, which raised

            TypeError: 'message' is an invalid keyword argument for RiskEvent

        on every call, and there was no try/except to contain it. Three gates
        route through here (per-strategy daily loss, max drawdown, position
        cap), so a clean rejection became an exception, `strategy_executor`
        counted it as a tick error, and at 20 consecutive errors the strategy
        DEACTIVATED itself (`strategy_executor.py:238`) — turning "stop for
        today" into "off until someone notices". The per-strategy daily cap
        defaults to 5% of account, about two losing trades, so this was
        reachable on any ordinary session.

        Now mirrors `_log_account_risk_event`: writes `details`, and wraps the
        write so a logging failure can never decide whether a trade happens.
        """
        try:
            risk_event = RiskEvent(
                user_id=user.id,
                strategy_id=strategy.id if strategy is not None else None,
                event_type=event_type,
                severity=severity,
                action_taken=action_taken,
                details={"reason": message},
            )
            self.db.add(risk_event)
            self.db.commit()
        except Exception as exc:  # pragma: no cover - logging must never crash trade flow
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"Failed to persist {event_type} risk event: {exc}")

        logger.warning(
            f"Risk event: {event_type} ({severity}) - {message} - Action: {action_taken}"
        )

    def get_account_risk_status(self, user: User) -> Dict:
        """User-level (account-wide) risk snapshot for the dashboard
        session-status tile. Sums realized PnL across all the user's
        strategies for today plus unrealized PnL on open positions.

        Status thresholds match `_check_user_daily_loss_limit`:
        - HALTED at 100% of cap consumed (entries blocked)
        - WARNING at 80% of cap consumed
        - OK otherwise

        `pct_consumed` is clamped to [0, 100+] so the UI progress bar
        can render a meaningful overflow if the cap is breached past
        100% (e.g. between checks)."""
        # Display surface: bucket "today" by the viewer's own timezone so the
        # tile matches the day they perceive (falls back to ET when unset).
        today_start = user_day_start_utc(user.timezone)

        realized = self.db.query(func.sum(Trade.pnl)).filter(
            Trade.user_id == user.id,
            Trade.timestamp >= today_start,
            Trade.status == 'executed',
            Trade.pnl.isnot(None),
        ).scalar() or 0.0

        unrealized = self.db.query(func.sum(Position.unrealized_pnl)).filter(
            Position.user_id == user.id,
            Position.qty > 0,
        ).scalar() or 0.0

        realized = float(realized)
        unrealized = float(unrealized)
        today_pnl = realized + unrealized

        account_size = self._account_base(user)
        daily_loss_limit_pct = float(user.daily_loss_limit_pct or 5.0)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        # `loss_consumed` is positive when underwater. If we're net-positive
        # the bar should read 0% — losses are what consume the cap, not gains.
        loss_consumed = max(0.0, -today_pnl)
        pct_consumed = (loss_consumed / daily_loss_limit * 100.0) if daily_loss_limit > 0 else 0.0
        daily_loss_remaining = max(0.0, daily_loss_limit - loss_consumed)

        if pct_consumed >= 100.0:
            risk_status = "HALTED"
        elif pct_consumed >= 80.0:
            risk_status = "WARNING"
        else:
            risk_status = "OK"

        # The manual halt is reported alongside `risk_status`, not folded into
        # it. They are different facts — "the cap stopped you" and "you stopped
        # yourself" — and the tile says something different for each. Folding
        # the manual halt into risk_status would make a deliberate, healthy
        # decision render as a risk breach.
        halted, halt_mode = trading_halt_state(user)

        return {
            "today_pnl": today_pnl,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "account_size": account_size,
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "daily_loss_limit": daily_loss_limit,
            "daily_loss_remaining": daily_loss_remaining,
            "pct_consumed": pct_consumed,
            "risk_status": risk_status,
            "trading_halted": halted,
            "trading_halt_mode": halt_mode,
            # Either reason blocks entries, so this stays the one field a
            # caller can ask "can we open anything right now".
            "entries_halted": risk_status == "HALTED" or halted,
        }

    def check_live_trading_safeguards(self, user: User) -> Tuple[bool, str]:
        """
        Additional safeguards specifically for live trading mode

        Returns:
            Tuple[bool, str]: (approved, message)
        """
        if user.selected_trading_mode != TradingMode.LIVE:
            return (True, "Not in live trading mode")

        # 1. Verify account size is set
        if not user.account_size_usd or user.account_size_usd <= 0:
            return (False, "Account size must be set for live trading")

        # 2. Check for recent activity (prevent stale execution)
        # This could check last login time, last trade, etc.

        # 3. Additional live-only validations could go here
        # - Market hours check
        # - Account balance verification
        # - Rate limiting

        return (True, "Live trading safeguards passed")

    def get_risk_metrics_summary(self, user: User, strategy: Strategy) -> Dict:
        """
        Get current risk metrics for monitoring

        Returns:
            Dict with current risk status
        """
        # Calculate current metrics
        # Monitoring readout: bucket "today" by the viewer's own timezone.
        today_start = user_day_start_utc(user.timezone)

        # Today's P&L
        today_pnl = self.db.query(func.sum(Trade.pnl)).filter(
            Trade.user_id == user.id,
            Trade.strategy_id == strategy.id,
            Trade.timestamp >= today_start,
            Trade.status == 'executed'
        ).scalar() or 0.0

        # Open positions count
        open_positions = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.qty > 0
        ).count()

        # Total unrealized P&L
        unrealized_pnl = self.db.query(func.sum(Position.unrealized_pnl)).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id
        ).scalar() or 0.0

        # Limits
        account_size = self._account_base(user)
        daily_loss_limit_pct = strategy.params_json.get('daily_loss_limit_pct', 5.0)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        return {
            "today_pnl": float(today_pnl),
            "today_pnl_pct": (float(today_pnl) / account_size * 100) if account_size > 0 else 0,
            "daily_loss_limit": float(daily_loss_limit),
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "daily_loss_remaining": float(daily_loss_limit + today_pnl),
            "open_positions": open_positions,
            "max_positions": strategy.max_positions or 3,
            "unrealized_pnl": float(unrealized_pnl),
            "account_size": account_size,
            "risk_status": "OK" if today_pnl > -(daily_loss_limit * 0.8) else "WARNING"
        }

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
from config import TradingMode

logger = logging.getLogger(__name__)


class RiskCheckResult:
    """Result of a risk check operation"""
    def __init__(self, approved: bool, reason: str = "", suggested_qty: Optional[int] = None):
        self.approved = approved
        self.reason = reason
        self.suggested_qty = suggested_qty


class RiskManager:
    """
    Manages all risk-related operations:
    - Position sizing based on account size and risk parameters
    - Pre-trade validation against risk limits
    - Daily loss limit enforcement
    - Maximum drawdown monitoring
    - Position limit enforcement
    """

    def __init__(self, db: Session):
        self.db = db

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
        account_size = float(user.account_size_usd or 10000)

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

        # For options: more conservative sizing due to theta decay
        _is_options = any(k in strategy.strategy_type.lower() for k in ('option', '0dte', 'scalping'))
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

        # Ensure at least 1 if we have enough capital for one unit
        if final_qty < 1:
            one_unit_cost = current_price * 100 if _is_options else current_price
            if effective_capital >= one_unit_cost:
                final_qty = 1

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
            return RiskCheckResult(
                False,
                "Cannot execute paper strategy in live trading mode"
            )

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
            return account_loss_check

        # 3. Check daily loss limit
        daily_loss_check = self._check_daily_loss_limit(user, strategy)
        if not daily_loss_check.approved:
            self._log_risk_event(
                user, strategy, "daily_loss_limit", "critical",
                daily_loss_check.reason, "trade_rejected"
            )
            return daily_loss_check

        # 4. Check maximum drawdown
        drawdown_check = self._check_max_drawdown(user, strategy)
        if not drawdown_check.approved:
            self._log_risk_event(
                user, strategy, "max_drawdown", "critical",
                drawdown_check.reason, "trade_rejected"
            )
            return drawdown_check

        # 5. Check position limits
        position_limit_check = self._check_position_limits(user, strategy)
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

        # 7. Check if we have an existing position in this symbol
        existing_position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol
        ).first()

        if existing_position and existing_position.qty > 0:
            # Already have a position - validate we're not over-concentrating
            total_qty = existing_position.qty + qty
            if total_qty > calculated_qty * 2:
                return RiskCheckResult(
                    False,
                    f"Total position size {total_qty} would exceed risk limits"
                )

        # All checks passed
        logger.info(
            f"Pre-trade validation PASSED: {symbol} {side} {qty} @ ${estimated_price}"
        )
        return RiskCheckResult(True, "All risk checks passed")

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

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

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

        account_size = float(user.account_size_usd or 10000)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        if today_pnl < -daily_loss_limit:
            return RiskCheckResult(
                False,
                f"Account daily loss cap reached: ${today_pnl:.2f} "
                f"(limit: ${-daily_loss_limit:.2f}). "
                f"New entries halted; existing positions can still be closed."
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

    def _check_daily_loss_limit(self, user: User, strategy: Strategy) -> RiskCheckResult:
        """Check if daily loss limit has been exceeded"""
        # Get today's trades for this strategy
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        today_pnl = self.db.query(func.sum(Trade.pnl)).filter(
            Trade.user_id == user.id,
            Trade.strategy_id == strategy.id,
            Trade.timestamp >= today_start,
            Trade.status == 'executed'
        ).scalar() or 0.0

        # Default daily loss limit: 5% of account size
        account_size = float(user.account_size_usd or 10000)
        daily_loss_limit_pct = strategy.params_json.get('daily_loss_limit_pct', 5.0)
        daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)

        if today_pnl < -daily_loss_limit:
            return RiskCheckResult(
                False,
                f"Daily loss limit exceeded: ${today_pnl:.2f} (limit: ${-daily_loss_limit:.2f})"
            )

        # Warning if approaching limit (80%)
        if today_pnl < -(daily_loss_limit * 0.8):
            logger.warning(
                f"Approaching daily loss limit: ${today_pnl:.2f} / ${-daily_loss_limit:.2f}"
            )

        return RiskCheckResult(True)

    def _check_max_drawdown(self, user: User, strategy: Strategy) -> RiskCheckResult:
        """Check if maximum drawdown limit has been exceeded"""
        # Get all-time high watermark for this strategy
        all_trades = self.db.query(Trade).filter(
            Trade.user_id == user.id,
            Trade.strategy_id == strategy.id,
            Trade.status == 'executed'
        ).all()

        if not all_trades:
            return RiskCheckResult(True)  # No trade history yet

        # Calculate cumulative P&L over time
        cumulative_pnl = 0.0
        peak_pnl = 0.0
        max_drawdown = 0.0

        for trade in all_trades:
            cumulative_pnl += float(trade.pnl or 0.0)
            if cumulative_pnl > peak_pnl:
                peak_pnl = cumulative_pnl

            current_drawdown = peak_pnl - cumulative_pnl
            if current_drawdown > max_drawdown:
                max_drawdown = current_drawdown

        # Default max drawdown limit: 10% of account
        account_size = float(user.account_size_usd or 10000)
        max_drawdown_limit_pct = strategy.params_json.get('max_drawdown_pct', 10.0)
        max_drawdown_limit = account_size * (max_drawdown_limit_pct / 100.0)

        if max_drawdown > max_drawdown_limit:
            return RiskCheckResult(
                False,
                f"Maximum drawdown exceeded: ${max_drawdown:.2f} (limit: ${max_drawdown_limit:.2f})"
            )

        # Warning if approaching limit (80%)
        if max_drawdown > (max_drawdown_limit * 0.8):
            logger.warning(
                f"Approaching max drawdown limit: ${max_drawdown:.2f} / ${max_drawdown_limit:.2f}"
            )

        return RiskCheckResult(True)

    def _check_position_limits(self, user: User, strategy: Strategy) -> RiskCheckResult:
        """Check if we're at maximum number of open positions"""
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
        """Log a risk event to the database"""
        risk_event = RiskEvent(
            user_id=user.id,
            strategy_id=strategy.id,
            event_type=event_type,
            severity=severity,
            message=message,
            action_taken=action_taken
        )
        self.db.add(risk_event)
        self.db.commit()

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
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

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

        account_size = float(user.account_size_usd or 10000)
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
            "entries_halted": risk_status == "HALTED",
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
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

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
        account_size = float(user.account_size_usd or 10000)
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

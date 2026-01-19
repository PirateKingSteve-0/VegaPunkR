"""
Trading Safeguards - Additional safety checks for paper and live trading

Paper Trading Safeguards:
  - Validate strategy parameters before execution
  - Simulated slippage and commission
  - Warning messages for unrealistic expectations

Live Trading Safeguards:
  - Multi-level confirmations required
  - Daily loss limits (already in RiskManager)
  - Rate limiting on order submission
  - Account balance verification
  - Market hours checking
  - Emergency stop mechanisms
"""
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, time
from sqlalchemy.orm import Session

from models import User, Strategy
from config import TradingMode

logger = logging.getLogger(__name__)


class PaperTradingSafeguards:
    """Safeguards specific to paper trading mode"""

    @staticmethod
    def validate_strategy_params(strategy: Strategy) -> Tuple[bool, str]:
        """
        Validate strategy parameters are reasonable for paper trading

        Args:
            strategy: Strategy object

        Returns:
            Tuple[bool, str]: (is_valid, message)
        """
        params = strategy.params_json

        # 1. Check position sizing is reasonable
        max_contracts = params.get('max_contracts', 0)
        if max_contracts > 10:
            return (
                False,
                f"max_contracts={max_contracts} is very high for 0DTE. Consider 1-3 contracts."
            )

        # 2. Check stop loss is set
        stop_loss_pct = params.get('stop_loss_pct', 0)
        if not stop_loss_pct or stop_loss_pct < 10:
            return (
                False,
                "Stop loss must be set and at least 10% for 0DTE options safety"
            )

        # 3. Check take profit is reasonable
        take_profit_pct = params.get('take_profit_pct', 0)
        if take_profit_pct > 100:
            return (
                False,
                f"Take profit of {take_profit_pct}% is unrealistic for 0DTE scalping"
            )

        # 4. Warn if no time-based exit
        max_hold_minutes = params.get('max_hold_time_minutes', 0)
        exit_before_close = params.get('exit_before_close_minutes', 0)
        if not max_hold_minutes and not exit_before_close:
            logger.warning(
                f"Strategy {strategy.id} has no time-based exit rules - "
                "consider setting max_hold_time_minutes"
            )

        # 5. Check delta range for options
        if 'option' in strategy.strategy_type.lower():
            delta_min = params.get('delta_min', 0)
            delta_max = params.get('delta_max', 1.0)

            if delta_min < 0.30 or delta_max > 0.90:
                return (
                    False,
                    f"Delta range [{delta_min}, {delta_max}] is outside safe range [0.30, 0.90]"
                )

        return (True, "Strategy parameters validated")

    @staticmethod
    def apply_simulated_slippage(price: float, side: str) -> float:
        """
        Apply simulated slippage for paper trading

        Args:
            price: Ideal execution price
            side: 'buy' or 'sell'

        Returns:
            float: Price with slippage applied
        """
        # Simulate 0.1% slippage
        slippage_pct = 0.001

        if side == 'buy':
            # Buy at slightly higher price
            return price * (1 + slippage_pct)
        else:
            # Sell at slightly lower price
            return price * (1 - slippage_pct)

    @staticmethod
    def calculate_simulated_commission(qty: int, is_options: bool = True) -> float:
        """
        Calculate simulated commission for paper trading

        Args:
            qty: Quantity traded
            is_options: Whether trading options (vs stocks)

        Returns:
            float: Commission amount
        """
        if is_options:
            # Typical options commission: $0.65 per contract
            return 0.65 * qty
        else:
            # Stock commission (usually $0 but simulate small SEC fees)
            return 0.01 * qty

    @staticmethod
    def get_paper_trading_disclaimer() -> str:
        """Get disclaimer message for paper trading"""
        return (
            "⚠️ PAPER TRADING MODE: Results are simulated and may not reflect real market conditions. "
            "Slippage, commissions, and market impact are approximated. "
            "Test thoroughly before switching to live trading."
        )


class LiveTradingSafeguards:
    """Safeguards specific to live trading mode"""

    # Track order submission for rate limiting
    _order_timestamps: Dict[int, list] = {}  # user_id -> list of timestamps

    @staticmethod
    def require_confirmations(user: User, strategy: Strategy) -> Dict:
        """
        Generate confirmation prompts for live trading

        Args:
            user: User object
            strategy: Strategy to execute

        Returns:
            Dict with confirmation details
        """
        return {
            "requires_confirmation": True,
            "warnings": [
                "⚠️ LIVE TRADING MODE - Real money at risk",
                f"Strategy: {strategy.name} ({strategy.strategy_type})",
                f"Account size: ${user.account_size_usd:,.2f}",
                f"Max risk per trade: {user.max_trade_percentage}%",
                f"Max positions: {strategy.max_positions}",
                "Losses can exceed initial risk in fast-moving markets"
            ],
            "checklist": [
                "I understand this is real money trading",
                "I have tested this strategy in paper mode",
                "I am aware of the risks involved",
                "I have set appropriate stop losses",
                "I am monitoring positions actively"
            ],
            "message": "Type 'CONFIRM LIVE TRADING' to proceed"
        }

    @staticmethod
    def check_market_hours() -> Tuple[bool, str]:
        """
        Check if market is currently open

        Returns:
            Tuple[bool, str]: (is_open, message)
        """
        now = datetime.utcnow()

        # US market hours: 9:30 AM - 4:00 PM ET
        # Convert to UTC (approximate - doesn't handle DST perfectly)
        # During standard time: ET = UTC - 5
        # During daylight time: ET = UTC - 4

        # Simplified: market hours in UTC (adjust based on DST)
        # Standard time: 14:30 - 21:00 UTC
        # Daylight time: 13:30 - 20:00 UTC

        # For now, use standard time approximation
        market_open_utc = time(14, 30)
        market_close_utc = time(21, 0)

        current_time = now.time()

        # Check if weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return (False, "Market is closed (weekend)")

        # Check if within trading hours
        if current_time < market_open_utc:
            return (False, f"Market opens at {market_open_utc} UTC")

        if current_time > market_close_utc:
            return (False, f"Market closed at {market_close_utc} UTC")

        return (True, "Market is open")

    @staticmethod
    def check_rate_limit(user_id: int, max_orders_per_minute: int = 10) -> Tuple[bool, str]:
        """
        Check if user is within order rate limits

        Args:
            user_id: User ID
            max_orders_per_minute: Maximum orders allowed per minute

        Returns:
            Tuple[bool, str]: (within_limit, message)
        """
        now = datetime.utcnow()
        one_minute_ago = now.timestamp() - 60

        # Get or create order history for user
        if user_id not in LiveTradingSafeguards._order_timestamps:
            LiveTradingSafeguards._order_timestamps[user_id] = []

        # Clean up old timestamps
        LiveTradingSafeguards._order_timestamps[user_id] = [
            ts for ts in LiveTradingSafeguards._order_timestamps[user_id]
            if ts > one_minute_ago
        ]

        # Check limit
        recent_orders = len(LiveTradingSafeguards._order_timestamps[user_id])

        if recent_orders >= max_orders_per_minute:
            return (
                False,
                f"Rate limit exceeded: {recent_orders} orders in last minute (max {max_orders_per_minute})"
            )

        # Add current timestamp
        LiveTradingSafeguards._order_timestamps[user_id].append(now.timestamp())

        return (True, f"Rate limit OK: {recent_orders + 1}/{max_orders_per_minute}")

    @staticmethod
    def verify_account_balance(user: User, required_capital: float) -> Tuple[bool, str]:
        """
        Verify user has sufficient account balance

        Note: In production, this should query the actual broker API
        For now, we rely on user.account_size_usd

        Args:
            user: User object
            required_capital: Required capital for trade

        Returns:
            Tuple[bool, str]: (has_balance, message)
        """
        account_size = float(user.account_size_usd or 0)

        if account_size <= 0:
            return (False, "Account size not set - update in settings")

        if required_capital > account_size:
            return (
                False,
                f"Insufficient capital: need ${required_capital:.2f}, have ${account_size:.2f}"
            )

        # Warn if using >20% of account on single trade
        if required_capital > account_size * 0.2:
            logger.warning(
                f"Large position size: ${required_capital:.2f} is "
                f"{(required_capital/account_size*100):.1f}% of account"
            )

        return (True, "Account balance sufficient")

    @staticmethod
    def get_emergency_stop_status(user_id: int) -> Dict:
        """
        Check if emergency stop is active for user

        This would integrate with a persistent store in production
        For now, returns basic status

        Args:
            user_id: User ID

        Returns:
            Dict with emergency stop status
        """
        # In production, check Redis or database
        return {
            "emergency_stop_active": False,
            "reason": None,
            "activated_at": None
        }

    @staticmethod
    def activate_emergency_stop(user_id: int, reason: str):
        """
        Activate emergency stop for a user

        This would:
        1. Stop all active strategies
        2. Close all open positions (optional)
        3. Prevent new orders

        Args:
            user_id: User ID
            reason: Reason for emergency stop
        """
        logger.critical(
            f"EMERGENCY STOP ACTIVATED - User {user_id}: {reason}"
        )

        # In production:
        # 1. Set flag in Redis/database
        # 2. Notify background worker to stop strategies
        # 3. Optionally close positions
        # 4. Send alerts (Discord, email, SMS)

    @staticmethod
    def get_live_trading_disclaimer() -> str:
        """Get disclaimer message for live trading"""
        return (
            "⚠️ LIVE TRADING MODE - REAL MONEY AT RISK ⚠️\n\n"
            "Trading involves substantial risk of loss and is not suitable for all investors. "
            "Past performance is not indicative of future results. "
            "You are solely responsible for your trading decisions. "
            "The platform providers are not liable for any losses."
        )


class TradingSafeguardsValidator:
    """Main validator that combines paper and live safeguards"""

    def __init__(self, db: Session):
        self.db = db
        self.paper_guards = PaperTradingSafeguards()
        self.live_guards = LiveTradingSafeguards()

    def validate_before_execution(
        self,
        user: User,
        strategy: Strategy,
        estimated_capital: Optional[float] = None
    ) -> Tuple[bool, list]:
        """
        Run all applicable safeguards before strategy execution

        Args:
            user: User object
            strategy: Strategy to validate
            estimated_capital: Estimated capital needed (optional)

        Returns:
            Tuple[bool, list]: (approved, list of messages/warnings)
        """
        messages = []
        trading_mode = user.selected_trading_mode or TradingMode.PAPER

        # Common validations
        # 1. Strategy parameter validation
        valid, msg = self.paper_guards.validate_strategy_params(strategy)
        if not valid:
            return (False, [msg])
        messages.append(msg)

        # Mode-specific validations
        if trading_mode == TradingMode.PAPER:
            messages.append(self.paper_guards.get_paper_trading_disclaimer())

        elif trading_mode == TradingMode.LIVE:
            # 1. Market hours check
            market_open, msg = self.live_guards.check_market_hours()
            if not market_open:
                return (False, [msg])
            messages.append(msg)

            # 2. Rate limit check
            within_limit, msg = self.live_guards.check_rate_limit(user.id)
            if not within_limit:
                return (False, [msg])
            messages.append(msg)

            # 3. Account balance check (if capital provided)
            if estimated_capital:
                has_balance, msg = self.live_guards.verify_account_balance(
                    user, estimated_capital
                )
                if not has_balance:
                    return (False, [msg])
                messages.append(msg)

            # 4. Emergency stop check
            estop = self.live_guards.get_emergency_stop_status(user.id)
            if estop['emergency_stop_active']:
                return (False, [f"Emergency stop active: {estop['reason']}"])

            messages.append(self.live_guards.get_live_trading_disclaimer())

        return (True, messages)

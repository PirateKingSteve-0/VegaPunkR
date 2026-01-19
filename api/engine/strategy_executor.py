"""
Strategy Executor - Core execution engine that orchestrates:
- Risk checking
- Signal generation
- Order execution
- Position monitoring

This is the main engine that brings together all components:
  RiskManager → SignalGenerator → OrderManager → TradingClientManager

Paper vs Live trading is handled automatically:
  - RiskManager checks if paper strategy is being run in live mode (prevents this)
  - OrderManager routes to TradingClientManager
  - TradingClientManager checks user.selected_trading_mode and routes to:
    * Paper mode → Alpaca Paper API
    * Live mode → Schwab Live API
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from models import User, Strategy, Position
from engine.risk_manager import RiskManager, RiskCheckResult
from engine.signal_generator import SignalGenerator, Signal
from engine.order_manager import OrderManager, OrderResult

logger = logging.getLogger(__name__)


class ExecutionState:
    """Tracks the execution state of a strategy"""
    def __init__(self, strategy_id: int):
        self.strategy_id = strategy_id
        self.is_running = False
        self.started_at: Optional[datetime] = None
        self.last_check_at: Optional[datetime] = None
        self.error_count = 0
        self.last_error: Optional[str] = None


class StrategyExecutor:
    """
    Main strategy execution engine.

    Orchestrates the complete trade lifecycle:
    1. Monitor market data for active strategies
    2. Generate signals based on strategy parameters
    3. Run risk checks before placing orders
    4. Execute orders via OrderManager
    5. Monitor positions for exit signals
    6. Handle errors and safeguards
    """

    def __init__(self, db: Session):
        self.db = db
        self.risk_manager = RiskManager(db)
        self.signal_generator = SignalGenerator()
        self.order_manager = OrderManager(db)

        # Track execution state for each strategy
        self.execution_states: Dict[int, ExecutionState] = {}

    async def execute_strategy_tick(
        self,
        user: User,
        strategy: Strategy,
        market_data: Dict
    ) -> Dict:
        """
        Execute one "tick" of strategy logic - check for signals and manage positions

        This is called periodically (e.g., every minute) by the background worker

        Args:
            user: User object
            strategy: Strategy to execute
            market_data: Current market data dict with:
                {
                    'symbol': str,
                    'price': float,
                    'volume': int,
                    'bid': float,
                    'ask': float,
                    'delta': float (for options),
                    'open_interest': int (for options),
                    'tick_value': int (optional $TICK indicator)
                }

        Returns:
            Dict with execution results
        """
        state = self._get_or_create_state(strategy.id)
        state.last_check_at = datetime.utcnow()

        results = {
            'strategy_id': strategy.id,
            'timestamp': datetime.utcnow().isoformat(),
            'signals_generated': [],
            'orders_placed': [],
            'positions_closed': [],
            'errors': []
        }

        try:
            # 1. Check if strategy is active
            if not strategy.is_active:
                results['errors'].append("Strategy is not active")
                return results

            symbol = market_data.get('symbol')
            current_price = market_data.get('price', 0.0)
            current_volume = market_data.get('volume', 0)

            if not symbol or current_price <= 0:
                results['errors'].append("Invalid market data")
                return results

            # 2. Check for entry signals (if we have room for more positions)
            await self._check_entry_signals(
                user, strategy, symbol, current_price, current_volume,
                market_data, results
            )

            # 3. Check open positions for exit signals
            await self._check_exit_signals(
                user, strategy, symbol, current_price, market_data, results
            )

            # 4. Update position prices for P&L tracking
            self.order_manager.update_position_prices(
                user, strategy, symbol, current_price
            )

            state.error_count = 0  # Reset error count on successful tick
            state.last_error = None

        except Exception as e:
            error_msg = f"Strategy execution error: {str(e)}"
            logger.error(error_msg, exc_info=True)
            results['errors'].append(error_msg)

            state.error_count += 1
            state.last_error = error_msg

            # Stop strategy if too many consecutive errors
            if state.error_count >= 5:
                strategy.is_active = False
                self.db.commit()
                logger.critical(
                    f"Strategy {strategy.id} auto-stopped after {state.error_count} consecutive errors"
                )

        return results

    async def _check_entry_signals(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        current_price: float,
        current_volume: int,
        market_data: Dict,
        results: Dict
    ):
        """Check for entry signals and execute if conditions are met"""
        # Check if we have room for more positions
        open_positions_count = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.qty > 0
        ).count()

        max_positions = strategy.max_positions or 3
        if open_positions_count >= max_positions:
            logger.debug(f"Max positions ({max_positions}) reached for strategy {strategy.id}")
            return

        # Generate entry signal
        entry_signal = self.signal_generator.check_entry_signal(
            strategy=strategy,
            symbol=symbol,
            current_price=current_price,
            current_volume=current_volume,
            additional_data=market_data
        )

        if not entry_signal:
            return  # No signal

        results['signals_generated'].append({
            'type': 'entry',
            'symbol': symbol,
            'action': entry_signal.action,
            'confidence': entry_signal.confidence,
            'reason': entry_signal.reason
        })

        # Calculate position size
        qty = self.risk_manager.calculate_position_size(
            user=user,
            strategy=strategy,
            current_price=current_price
        )

        if qty <= 0:
            results['errors'].append(f"Invalid position size calculated: {qty}")
            return

        # Run pre-trade risk checks
        risk_check = self.risk_manager.validate_pre_trade(
            user=user,
            strategy=strategy,
            symbol=symbol,
            qty=qty,
            estimated_price=current_price,
            side=entry_signal.action
        )

        if not risk_check.approved:
            results['errors'].append(f"Risk check failed: {risk_check.reason}")
            logger.warning(f"Trade rejected: {risk_check.reason}")
            return

        # Execute the signal
        order_result = await self.order_manager.execute_signal(
            user=user,
            strategy=strategy,
            signal=entry_signal,
            qty=qty
        )

        if order_result.success:
            results['orders_placed'].append({
                'symbol': symbol,
                'side': entry_signal.action,
                'qty': order_result.filled_qty,
                'price': order_result.filled_price,
                'order_id': order_result.order_id
            })
            logger.info(f"Entry order executed: {order_result.message}")
        else:
            results['errors'].append(f"Order execution failed: {order_result.message}")

    async def _check_exit_signals(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        current_price: float,
        market_data: Dict,
        results: Dict
    ):
        """Check open positions for exit signals"""
        # Get all open positions for this strategy and symbol
        positions = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol,
            Position.qty > 0
        ).all()

        for position in positions:
            # Determine position side
            position_side = 'long'  # Currently only supporting long positions

            # Get current high/low for trailing stops (simplified - use current price)
            current_high = market_data.get('high', current_price)
            current_low = market_data.get('low', current_price)

            # Check for exit signal
            exit_signal = self.signal_generator.check_exit_signal(
                strategy=strategy,
                symbol=symbol,
                entry_price=position.avg_entry_price,
                current_price=current_price,
                entry_timestamp=position.opened_at,
                position_side=position_side,
                current_high=current_high,
                current_low=current_low
            )

            if not exit_signal:
                continue  # No exit signal

            results['signals_generated'].append({
                'type': 'exit',
                'symbol': symbol,
                'action': exit_signal.action,
                'confidence': exit_signal.confidence,
                'reason': exit_signal.reason
            })

            # Close the position
            order_result = await self.order_manager.close_position(
                user=user,
                strategy=strategy,
                position=position,
                reason=exit_signal.reason
            )

            if order_result.success:
                results['positions_closed'].append({
                    'symbol': symbol,
                    'qty': order_result.filled_qty,
                    'entry_price': position.avg_entry_price,
                    'exit_price': order_result.filled_price,
                    'pnl': (order_result.filled_price - position.avg_entry_price) * order_result.filled_qty,
                    'reason': exit_signal.reason
                })
                logger.info(f"Exit order executed: {order_result.message}")
            else:
                results['errors'].append(f"Exit order failed: {order_result.message}")

    def start_strategy(self, strategy_id: int) -> Dict:
        """
        Start executing a strategy

        Args:
            strategy_id: Strategy ID to start

        Returns:
            Dict with status
        """
        state = self._get_or_create_state(strategy_id)

        if state.is_running:
            return {
                'success': False,
                'message': 'Strategy is already running'
            }

        state.is_running = True
        state.started_at = datetime.utcnow()
        state.error_count = 0

        logger.info(f"Strategy {strategy_id} started")

        return {
            'success': True,
            'message': f'Strategy {strategy_id} started',
            'started_at': state.started_at.isoformat()
        }

    def stop_strategy(self, strategy_id: int) -> Dict:
        """
        Stop executing a strategy

        Args:
            strategy_id: Strategy ID to stop

        Returns:
            Dict with status
        """
        state = self.execution_states.get(strategy_id)

        if not state or not state.is_running:
            return {
                'success': False,
                'message': 'Strategy is not running'
            }

        state.is_running = False

        logger.info(f"Strategy {strategy_id} stopped")

        return {
            'success': True,
            'message': f'Strategy {strategy_id} stopped'
        }

    def get_strategy_status(self, strategy_id: int) -> Dict:
        """
        Get current execution status of a strategy

        Args:
            strategy_id: Strategy ID

        Returns:
            Dict with status information
        """
        state = self.execution_states.get(strategy_id)

        if not state:
            return {
                'strategy_id': strategy_id,
                'is_running': False,
                'message': 'Strategy not initialized'
            }

        return {
            'strategy_id': strategy_id,
            'is_running': state.is_running,
            'started_at': state.started_at.isoformat() if state.started_at else None,
            'last_check_at': state.last_check_at.isoformat() if state.last_check_at else None,
            'error_count': state.error_count,
            'last_error': state.last_error
        }

    def _get_or_create_state(self, strategy_id: int) -> ExecutionState:
        """Get or create execution state for a strategy"""
        if strategy_id not in self.execution_states:
            self.execution_states[strategy_id] = ExecutionState(strategy_id)
        return self.execution_states[strategy_id]

    def get_risk_summary(self, user: User, strategy: Strategy) -> Dict:
        """Get risk metrics summary for a strategy"""
        return self.risk_manager.get_risk_metrics_summary(user, strategy)

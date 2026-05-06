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
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from models import User, Strategy, Position
from engine.risk_manager import RiskManager, RiskCheckResult
from engine.signal_generator import SignalGenerator, Signal
from engine.order_manager import OrderManager, OrderResult
from utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

# Minimum time after a position closes before the same (strategy, symbol) is
# allowed to re-enter. Stops the buy/sell flip-flop seen in 2026-05-04 incident.
REENTRY_COOLDOWN_SECONDS = 30.0


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

    # Class-level so the cooldown survives executor re-instantiation within
    # the same process. Keyed by (strategy_id, symbol).
    _last_closed_at: Dict[Tuple[int, str], datetime] = {}

    def __init__(self, db: Session):
        self.db = db
        self.risk_manager = RiskManager(db)
        self.signal_generator = SignalGenerator()
        self.order_manager = OrderManager(db)

        # Track execution state for each strategy
        self.execution_states: Dict[int, ExecutionState] = {}

    @classmethod
    def _check_reentry_cooldown(cls, strategy_id: int, symbol: str) -> Tuple[bool, float]:
        """Return (allowed, seconds_until_allowed) for a fresh entry."""
        last = cls._last_closed_at.get((strategy_id, symbol))
        if last is None:
            return True, 0.0
        elapsed = (datetime.utcnow() - last).total_seconds()
        if elapsed >= REENTRY_COOLDOWN_SECONDS:
            return True, 0.0
        return False, REENTRY_COOLDOWN_SECONDS - elapsed

    @classmethod
    def _stamp_position_closed(cls, strategy_id: int, symbol: str) -> None:
        cls._last_closed_at[(strategy_id, symbol)] = datetime.utcnow()

    async def execute_exit_tick(
        self,
        user: User,
        strategy: Strategy,
        market_data: Dict,
    ) -> Dict:
        """Exit-only tick — called when a position is already open. Skips entry evaluation."""
        state = self._get_or_create_state(strategy.id)
        state.last_check_at = datetime.utcnow()

        results: Dict = {
            'strategy_id': strategy.id,
            'timestamp': datetime.utcnow().isoformat(),
            'signals_generated': [],
            'orders_placed': [],
            'positions_closed': [],
            'errors': [],
        }

        if not is_market_open():
            return results

        symbol = market_data.get('symbol')
        current_price = market_data.get('price', 0.0)
        if not symbol or current_price <= 0:
            return results

        # Use option mid price for P&L on options positions
        bid = market_data.get('bid', 0) or 0
        ask = market_data.get('ask', 0) or 0
        if market_data.get('option_symbol') and ask > 0:
            current_price = (bid + ask) / 2

        try:
            await self._check_exit_signals(user, strategy, symbol, current_price, market_data, results)
            self.order_manager.update_position_prices(user, strategy, symbol, current_price)
        except Exception as e:
            results['errors'].append(str(e))
            logger.error(f"Exit tick error strategy {strategy.id}: {e}", exc_info=True)

        return results

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
            # 1. Hard gate — no orders outside market hours
            if not is_market_open():
                logger.debug(f"Strategy {strategy.id}: market closed, skipping tick")
                return results

            # 2. Check if strategy is active
            if not strategy.is_active:
                results['errors'].append("Strategy is not active")
                return results

            symbol = market_data.get('symbol')
            current_price = market_data.get('price', 0.0)
            current_volume = market_data.get('volume', 0)

            if not symbol or current_price <= 0:
                results['errors'].append("Invalid market data")
                return results

            # 3. Check for entry signals (if we have room for more positions)
            await self._check_entry_signals(
                user, strategy, symbol, current_price, current_volume,
                market_data, results
            )

            # 4. Check open positions for exit signals — but NOT on the same tick we
            # just entered, so we don't immediately exit a freshly opened position
            if not results['orders_placed']:
                await self._check_exit_signals(
                    user, strategy, symbol, current_price, market_data, results
                )

            # 5. Update position prices for P&L tracking
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

            # Stop strategy after too many consecutive errors
            if state.error_count >= 20:
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
        # Re-entry cooldown — block fresh entries on (strategy, symbol) for a
        # short window after the most recent close. Prevents the buy/sell
        # flip-flop loop where a fresh signal fires the moment qty hits 0.
        allowed, wait_s = self._check_reentry_cooldown(strategy.id, symbol)
        if not allowed:
            logger.debug(
                f"Re-entry cooldown active for {symbol} "
                f"(strategy {strategy.id}): {wait_s:.1f}s remaining"
            )
            return

        # Check if we have room for more positions
        open_positions_count = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.qty > 0
        ).count()

        max_positions = strategy.max_positions or 1
        if open_positions_count >= max_positions:
            logger.debug(f"Max positions ({max_positions}) reached for strategy {strategy.id}")
            return

        # Generate entry signal
        entry_signal = self.signal_generator.check_entry_signal(
            strategy=strategy,
            symbol=symbol,
            current_price=current_price,
            current_volume=current_volume,
            additional_data=market_data,
            user=user
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

        # For options strategies use the option premium for sizing, not the underlying price
        _is_options = any(k in strategy.strategy_type.lower() for k in ('option', '0dte', 'scalping'))
        if _is_options:
            bid = market_data.get('bid', 0) or 0
            ask = market_data.get('ask', 0) or 0
            if ask <= 0:
                logger.debug(f"{symbol}: Option price not yet available, skipping entry")
                return
            sizing_price = (bid + ask) / 2
            logger.info(
                f"ENTRY SIGNAL: {symbol} option={market_data.get('option_symbol')} "
                f"mid=${sizing_price:.2f} reason={entry_signal.reason}"
            )
        else:
            sizing_price = current_price
            logger.info(f"ENTRY SIGNAL: {symbol} price=${sizing_price:.2f} reason={entry_signal.reason}")

        qty = self.risk_manager.calculate_position_size(
            user=user,
            strategy=strategy,
            current_price=sizing_price
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
            estimated_price=sizing_price,
            side=entry_signal.action
        )

        if not risk_check.approved:
            results['errors'].append(f"Risk check failed: {risk_check.reason}")
            logger.warning(f"Trade rejected: {risk_check.reason}")
            return

        # Execute the signal — pass sizing_price so the DB stores the option premium,
        # not the underlying price that signal.price carries
        order_result = await self.order_manager.execute_signal(
            user=user,
            strategy=strategy,
            signal=entry_signal,
            qty=qty,
            option_symbol=market_data.get('option_symbol'),
            estimated_price=sizing_price,
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

            # For long option positions evaluate exits at the bid — that's the
            # realistic fill price for a market sell. Using mid overstates what
            # we can actually realize; with wide spreads it can fire take-profit
            # while the bid-side fill is a loss. Entry price is the option premium,
            # so comparing against the underlying produces nonsensical %s anyway.
            exit_price = current_price
            bid = market_data.get('bid', 0) or 0
            ask = market_data.get('ask', 0) or 0
            option_symbol = position.option_symbol or market_data.get('option_symbol')
            if option_symbol:
                if bid > 0:
                    exit_price = bid
                elif ask > 0:
                    # One-sided book — fall back to mid (which is just ask/2 here)
                    exit_price = (bid + ask) / 2
                else:
                    # Stream hasn't delivered a quote yet — fall back to Tradier REST
                    rest_price = await self._fetch_option_price(option_symbol)
                    if rest_price > 0:
                        exit_price = rest_price
                    else:
                        continue  # Truly no price available, skip this tick

            # Update the option's high-water-mark since open. Trailing stops
            # MUST compare against the option price's peak/trough, not the
            # underlying's daily high/low — otherwise the stop fires the
            # instant activation is reached (e.g. $3.67 vs $651.30).
            if position.peak_price is None or exit_price > position.peak_price:
                position.peak_price = exit_price
            if position.trough_price is None or exit_price < position.trough_price:
                position.trough_price = exit_price

            # Check for exit signal
            exit_signal = self.signal_generator.check_exit_signal(
                strategy=strategy,
                symbol=symbol,
                entry_price=position.avg_entry_price,
                current_price=exit_price,
                entry_timestamp=position.opened_at,
                position_side=position_side,
                current_high=position.peak_price,
                current_low=position.trough_price,
                user=user
            )

            if not exit_signal:
                logger.debug(
                    f"No exit: {symbol} entry=${position.avg_entry_price:.4f} "
                    f"current=${exit_price:.4f} pnl={(exit_price - position.avg_entry_price) / position.avg_entry_price * 100:.2f}%"
                )
                continue  # No exit signal

            logger.info(
                f"EXIT SIGNAL: {symbol} entry=${position.avg_entry_price:.4f} "
                f"current=${exit_price:.4f} pnl={(exit_price - position.avg_entry_price) / position.avg_entry_price * 100:.2f}% "
                f"reason={exit_signal.reason}"
            )
            results['signals_generated'].append({
                'type': 'exit',
                'symbol': symbol,
                'action': exit_signal.action,
                'confidence': exit_signal.confidence,
                'reason': exit_signal.reason
            })

            # Use the stored option_symbol from the position (not the currently-selected contract)
            close_option_symbol = position.option_symbol or market_data.get('option_symbol')

            # Close the position
            order_result = await self.order_manager.close_position(
                user=user,
                strategy=strategy,
                position=position,
                reason=exit_signal.reason,
                option_symbol=close_option_symbol,
            )

            if order_result.success:
                # Stamp the close so the re-entry cooldown gate kicks in on the
                # next entry signal for this (strategy, symbol).
                self._stamp_position_closed(strategy.id, symbol)
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

    async def _fetch_option_price(self, option_symbol: str) -> float:
        """Fetch option mid price from Tradier REST when stream quote is unavailable."""
        try:
            import asyncio as _asyncio
            from tradier_integration.client import get_tradier_client
            client = get_tradier_client()

            def _get_quote():
                live_url = client._base_url if 'live' in getattr(client, '_base_url', '') else None
                from config import settings
                url = f"{settings.TRADIER_LIVE_BASE_URL.rstrip('/')}/v1/markets/quotes"
                import requests
                resp = requests.get(
                    url,
                    params={"symbols": option_symbol, "greeks": "false"},
                    headers={
                        "Authorization": f"Bearer {settings.TRADIER_LIVE_API_KEY}",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                quotes = resp.json().get("quotes", {}).get("quote", {})
                if isinstance(quotes, list):
                    quotes = quotes[0] if quotes else {}
                bid = float(quotes.get("bid") or 0)
                ask = float(quotes.get("ask") or 0)
                if ask > 0:
                    return (bid + ask) / 2
                return float(quotes.get("last") or 0)

            price = await _asyncio.to_thread(_get_quote)
            if price > 0:
                logger.debug(f"REST fallback price for {option_symbol}: ${price:.2f}")
            return price
        except Exception as e:
            logger.warning(f"REST option price fetch failed for {option_symbol}: {e}")
            return 0.0

    def get_risk_summary(self, user: User, strategy: Strategy) -> Dict:
        """Get risk metrics summary for a strategy"""
        return self.risk_manager.get_risk_metrics_summary(user, strategy)

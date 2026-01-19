"""
Order Manager - Order lifecycle management and execution tracking

The Order Manager uses TradingClientManager which automatically routes orders
to the correct trading API based on user.selected_trading_mode:
  - Paper mode: Alpaca Paper Trading API
  - Live mode: Schwab Live Trading API
"""
import logging
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from models import User, Strategy, Trade, Position
from engine.trading_client_manager import TradingClientManager
from engine.signal_generator import Signal

logger = logging.getLogger(__name__)


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

    def __init__(self, db: Session):
        self.db = db
        self.trading_client = TradingClientManager()

    async def execute_signal(
        self,
        user: User,
        strategy: Strategy,
        signal: Signal,
        qty: int
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

        try:
            # Place order via TradingClientManager (handles paper/live routing)
            order_response = await self.trading_client.place_order(
                user=user,
                symbol=symbol,
                qty=qty,
                side=side,
                order_type=order_type
            )

            if not order_response:
                return OrderResult(
                    success=False,
                    message=f"Failed to place order for {symbol}"
                )

            # Extract order details
            order_id = self._extract_order_id(order_response)
            filled_price = self._extract_filled_price(order_response, signal.price)
            filled_qty = self._extract_filled_qty(order_response, qty)

            # Record trade in database
            trade = self._create_trade_record(
                user=user,
                strategy=strategy,
                signal=signal,
                qty=filled_qty,
                price=filled_price,
                order_id=order_id
            )

            # Update or create position
            if signal.signal_type == 'entry':
                self._update_position_entry(
                    user=user,
                    strategy=strategy,
                    symbol=symbol,
                    qty=filled_qty,
                    price=filled_price,
                    trade=trade
                )
            elif signal.signal_type == 'exit':
                self._update_position_exit(
                    user=user,
                    strategy=strategy,
                    symbol=symbol,
                    qty=filled_qty,
                    price=filled_price,
                    trade=trade
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

        except Exception as e:
            logger.error(f"Error executing signal: {str(e)}", exc_info=True)
            return OrderResult(
                success=False,
                message=f"Order execution failed: {str(e)}"
            )

    def _extract_order_id(self, order_response: Dict) -> Optional[str]:
        """Extract order ID from API response"""
        # Alpaca format
        if hasattr(order_response, 'id'):
            return str(order_response.id)

        # Schwab format
        if isinstance(order_response, dict) and 'orderId' in order_response:
            return str(order_response['orderId'])

        # Fallback
        return str(order_response) if order_response else None

    def _extract_filled_price(
        self,
        order_response: Dict,
        estimated_price: Optional[float]
    ) -> float:
        """Extract filled price from API response"""
        # Alpaca format
        if hasattr(order_response, 'filled_avg_price') and order_response.filled_avg_price:
            return float(order_response.filled_avg_price)

        # Schwab format
        if isinstance(order_response, dict) and 'price' in order_response:
            return float(order_response['price'])

        # Fallback to estimated price
        return estimated_price or 0.0

    def _extract_filled_qty(self, order_response: Dict, requested_qty: int) -> int:
        """Extract filled quantity from API response"""
        # Alpaca format
        if hasattr(order_response, 'filled_qty') and order_response.filled_qty:
            return int(order_response.filled_qty)

        # Schwab format
        if isinstance(order_response, dict) and 'quantity' in order_response:
            return int(order_response['quantity'])

        # Fallback to requested quantity (assume full fill)
        return requested_qty

    def _create_trade_record(
        self,
        user: User,
        strategy: Strategy,
        signal: Signal,
        qty: int,
        price: float,
        order_id: Optional[str]
    ) -> Trade:
        """Create a trade record in the database"""
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
            notes={
                'signal_type': signal.signal_type,
                'signal_reason': signal.reason,
                'signal_confidence': signal.confidence,
                'indicators': signal.indicators,
                'order_id': order_id
            }
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
        trade: Trade
    ):
        """Update or create position for entry trade.

        Uses row-level locking (SELECT FOR UPDATE) to prevent race conditions
        when multiple strategies might update the same position concurrently.
        """
        # Check if position exists with row-level lock
        position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol
        ).with_for_update().first()  # Lock the row

        if position:
            # Add to existing position
            total_qty = position.qty + qty
            total_cost = (position.avg_entry_price * position.qty) + (price * qty)
            new_avg_price = total_cost / total_qty

            position.qty = total_qty
            position.avg_entry_price = new_avg_price
            position.current_price = price
            position.unrealized_pnl = (price - new_avg_price) * total_qty

            logger.info(
                f"Updated position: {symbol} qty={total_qty}, avg_price=${new_avg_price:.2f}"
            )
        else:
            # Create new position
            position = Position(
                user_id=user.id,
                strategy_id=strategy.id,
                symbol=symbol,
                qty=qty,
                avg_entry_price=price,
                current_price=price,
                unrealized_pnl=0.0,
                opened_at=datetime.utcnow()
            )
            self.db.add(position)

            logger.info(f"Created new position: {symbol} qty={qty}, price=${price:.2f}")

        # Link trade to position
        trade.position_id = position.id

        self.db.commit()
        self.db.refresh(position)

        return position

    def _update_position_exit(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        qty: int,
        price: float,
        trade: Trade
    ):
        """Update position for exit trade.

        Uses row-level locking (SELECT FOR UPDATE) to prevent race conditions
        when multiple strategies might update the same position concurrently.
        """
        # Find existing position with row-level lock
        position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol
        ).with_for_update().first()  # Lock the row

        if not position:
            logger.warning(f"No position found for exit trade: {symbol}")
            return None

        # Calculate P&L for this exit
        entry_price = position.avg_entry_price
        exit_pnl = (price - entry_price) * qty

        # Update trade with exit details
        trade.exit_price = price
        trade.exit_timestamp = datetime.utcnow()
        trade.pnl = exit_pnl - (trade.commission or 0.0)

        # Reduce position quantity
        position.qty -= qty
        position.current_price = price

        # If position fully closed, set unrealized P&L to 0
        if position.qty <= 0:
            position.qty = 0
            position.unrealized_pnl = 0.0
            logger.info(f"Position fully closed: {symbol}, P&L=${exit_pnl:.2f}")
        else:
            # Recalculate unrealized P&L for remaining position
            position.unrealized_pnl = (price - position.avg_entry_price) * position.qty
            logger.info(
                f"Partial exit: {symbol}, closed {qty}, remaining {position.qty}, P&L=${exit_pnl:.2f}"
            )

        self.db.commit()
        self.db.refresh(position)
        self.db.refresh(trade)

        return position

    async def close_position(
        self,
        user: User,
        strategy: Strategy,
        position: Position,
        reason: str = "Manual close"
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

        try:
            # Place market order to close (routes via TradingClientManager)
            order_response = await self.trading_client.place_order(
                user=user,
                symbol=position.symbol,
                qty=position.qty,
                side=side,
                order_type='market'
            )

            if not order_response:
                return OrderResult(
                    success=False,
                    message=f"Failed to place closing order for {position.symbol}"
                )

            # Extract order details
            order_id = self._extract_order_id(order_response)
            filled_price = self._extract_filled_price(order_response, position.current_price)
            filled_qty = self._extract_filled_qty(order_response, position.qty)

            # Calculate final P&L
            pnl = (filled_price - position.avg_entry_price) * filled_qty

            # Create trade record
            trade = Trade(
                user_id=user.id,
                strategy_id=strategy.id,
                position_id=position.id,
                symbol=position.symbol,
                side=side,
                order_type='market',
                qty=filled_qty,
                filled_qty=filled_qty,
                price=filled_price,
                exit_price=filled_price,
                exit_timestamp=datetime.utcnow(),
                pnl=pnl,
                status='executed',
                timestamp=datetime.utcnow(),
                notes={
                    'signal_type': 'exit',
                    'signal_reason': reason,
                    'order_id': order_id
                }
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
            return OrderResult(
                success=False,
                message=f"Failed to close position: {str(e)}"
            )

    def update_position_prices(
        self,
        user: User,
        strategy: Strategy,
        symbol: str,
        current_price: float
    ):
        """Update current price and unrealized P&L for a position.

        Uses row-level locking to prevent race conditions during concurrent updates.
        """
        position = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == symbol
        ).with_for_update().first()  # Lock the row

        if not position or position.qty <= 0:
            return

        # Update current price
        position.current_price = current_price

        # Recalculate unrealized P&L
        position.unrealized_pnl = (current_price - position.avg_entry_price) * position.qty

        self.db.commit()

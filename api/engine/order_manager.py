"""
Order Manager - Order lifecycle management and execution tracking

The Order Manager uses TradingClientManager which automatically routes orders
to the correct trading API based on user.selected_trading_mode:
  - Paper mode: Alpaca Paper Trading API
  - Live mode: Schwab Live Trading API
"""
import asyncio
import logging
from typing import Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from models import User, Strategy, Trade, Position
from engine.trading_client_manager import TradingClientManager
from engine.signal_generator import Signal
from engine.event_logger import log_event

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

        try:
            # Lock-out: once a position is open on (user, strategy, symbol),
            # block further entries so we lock in to sell-to-close instead of
            # stacking more contracts. Row-level lock prevents the race where
            # two ticks both see qty=0 and both place orders.
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

            # Extract order details
            order_id = self._extract_order_id(order_response)
            filled_price = self._extract_filled_price(order_response, estimated_price or signal.price)
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

        # Only Tradier is wired up for status polling today. Schwab path
        # falls through and the caller treats the original response as the
        # source of truth (existing behavior pre-change).
        trading_mode = user.selected_trading_mode or "paper"
        if trading_mode != "paper":
            return None

        try:
            client = self.trading_client.get_client(user)
        except Exception as e:
            logger.warning(f"Cannot poll order status — client unavailable: {e}")
            return None

        terminal = {"filled", "rejected", "canceled", "expired"}
        deadline = asyncio.get_event_loop().time() + timeout_s

        while asyncio.get_event_loop().time() < deadline:
            try:
                order = await asyncio.to_thread(client.get_order, order_id)
            except Exception as e:
                logger.warning(f"get_order({order_id}) failed: {e}")
                await asyncio.sleep(poll_interval_s)
                continue

            status = (order.get("status") or "").lower()
            if status in terminal:
                return order

            await asyncio.sleep(poll_interval_s)

        return None

    def _extract_order_id(self, order_response: Dict) -> Optional[str]:
        """Extract order ID from API response"""
        # Tradier format: { "id": 123456, "status": "ok" }
        if isinstance(order_response, dict) and 'id' in order_response:
            return str(order_response['id'])

        # Alpaca SDK object
        if hasattr(order_response, 'id'):
            return str(order_response.id)

        # Schwab format
        if isinstance(order_response, dict) and 'orderId' in order_response:
            return str(order_response['orderId'])

        return str(order_response) if order_response else None

    def _extract_filled_price(
        self,
        order_response: Dict,
        estimated_price: Optional[float]
    ) -> float:
        """Extract filled price from API response.

        Tradier market orders return no fill price immediately — fall back to
        the mid-price estimate from market data so P&L tracking is reasonable.
        """
        # Tradier: avg_fill_price populated once filled
        if isinstance(order_response, dict) and order_response.get('avg_fill_price'):
            return float(order_response['avg_fill_price'])

        # Alpaca SDK object
        if hasattr(order_response, 'filled_avg_price') and order_response.filled_avg_price:
            return float(order_response.filled_avg_price)

        # Schwab format
        if isinstance(order_response, dict) and 'price' in order_response:
            return float(order_response['price'])

        # Fallback to bid/ask mid estimate
        return estimated_price or 0.0

    def _extract_filled_qty(self, order_response: Dict, requested_qty: int) -> int:
        """Extract filled quantity from API response"""
        # Tradier: exec_quantity field
        if isinstance(order_response, dict) and order_response.get('exec_quantity'):
            return int(float(order_response['exec_quantity']))

        # Alpaca SDK object
        if hasattr(order_response, 'filled_qty') and order_response.filled_qty:
            return int(order_response.filled_qty)

        # Schwab format
        if isinstance(order_response, dict) and 'quantity' in order_response:
            return int(order_response['quantity'])

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
        trade: Trade,
        option_symbol: Optional[str] = None,
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
            position.unrealized_pnl = (price - new_avg_price) * total_qty
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
                opened_at=datetime.utcnow()
            )
            self.db.add(position)

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

        fully_closed = False

        # If position fully closed, set unrealized P&L to 0
        if position.qty <= 0:
            position.qty = 0
            position.unrealized_pnl = 0.0
            fully_closed = True
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

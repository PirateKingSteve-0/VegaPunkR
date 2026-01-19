"""
Trading Client Manager for hot-swapping between paper and live trading APIs.

This module manages the trading API clients (Alpaca Paper and Schwab Live)
and provides seamless switching between them without server restart.

The manager maintains client instances and routes order execution to the
appropriate API based on the user's selected trading mode.
"""
import logging
import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path to allow imports
sys.path.append(str(Path(__file__).parent.parent))

from config import settings, TradingMode
from models import User

logger = logging.getLogger(__name__)


class TradingClientManager:
    """
    Singleton manager for trading API clients.

    Maintains instances of both Alpaca Paper and Schwab Live clients
    and routes requests based on user's selected trading mode.
    """

    _instance = None
    _clients: Dict[TradingMode, Any] = {}

    def __new__(cls):
        """Ensure only one instance exists (Singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the trading client manager."""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("Trading Client Manager initialized")

    def get_client(self, user: User):
        """
        Get the appropriate trading client based on user's trading mode.

        Args:
            user: User object with selected_trading_mode

        Returns:
            Trading client instance (Alpaca or Schwab)

        Raises:
            ValueError: If trading mode is invalid
        """
        trading_mode = user.selected_trading_mode or "paper"

        if trading_mode not in ["paper", "live"]:
            raise ValueError(f"Invalid trading mode: {trading_mode}")

        # Get or create client for this mode
        if trading_mode == "paper":
            return self._get_alpaca_client()
        else:
            return self._get_schwab_client()

    def _get_alpaca_client(self):
        """
        Get or create Alpaca Paper Trading client.

        Returns:
            Alpaca TradingClient instance
        """
        if TradingMode.PAPER not in self._clients:
            try:
                from alpaca.trading.client import TradingClient

                self._clients[TradingMode.PAPER] = TradingClient(
                    api_key=settings.ALPACA_PAPER_API_KEY,
                    secret_key=settings.ALPACA_PAPER_SECRET_KEY,
                    paper=True
                )
                logger.info("✅ Alpaca Paper Trading client initialized")
            except ImportError as e:
                logger.error(f"Failed to import Alpaca client: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Alpaca client: {e}")
                raise

        return self._clients[TradingMode.PAPER]

    def _get_schwab_client(self):
        """
        Get or create Schwab Live Trading client.

        Returns:
            SchwabClient instance
        """
        if TradingMode.LIVE not in self._clients:
            try:
                from schwab_integration.client import SchwabClient

                self._clients[TradingMode.LIVE] = SchwabClient()
                logger.info("✅ Schwab Live Trading client initialized")
            except ImportError as e:
                logger.error(f"Failed to import Schwab client: {e}")
                raise
            except Exception as e:
                logger.error(f"Failed to initialize Schwab client: {e}")
                raise

        return self._clients[TradingMode.LIVE]

    async def place_order(self, user: User, symbol: str, qty: int, side: str, order_type: str = "market", **kwargs):
        """
        Place an order using the appropriate trading API.

        Args:
            user: User object with selected_trading_mode
            symbol: Stock/option symbol
            qty: Quantity to trade
            side: "buy" or "sell"
            order_type: "market", "limit", etc.
            **kwargs: Additional order parameters (limit_price, stop_price, etc.)

        Returns:
            Order response from the trading API

        Example:
            order = await manager.place_order(
                user=current_user,
                symbol="SPY",
                qty=1,
                side="buy",
                order_type="market"
            )
        """
        client = self.get_client(user)
        trading_mode = user.selected_trading_mode or "paper"

        logger.info(f"Placing {side} order for {qty} {symbol} via {trading_mode} trading")

        try:
            if trading_mode == "paper":
                # Alpaca API
                from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
                from alpaca.trading.enums import OrderSide, TimeInForce

                if order_type == "market":
                    order_data = MarketOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                        time_in_force=TimeInForce.DAY
                    )
                elif order_type == "limit":
                    order_data = LimitOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                        limit_price=kwargs.get("limit_price")
                    )
                else:
                    raise ValueError(f"Unsupported order type: {order_type}")

                order = client.submit_order(order_data)
                logger.info(f"✅ Alpaca order placed: {order.id}")
                return order

            else:
                # Schwab API
                order_payload = {
                    "symbol": symbol,
                    "quantity": qty,
                    "side": side,
                    "order_type": order_type,
                }

                if order_type == "limit":
                    order_payload["limit_price"] = kwargs.get("limit_price")

                order = await client.place_order(**order_payload)
                logger.info(f"✅ Schwab order placed: {order.get('orderId')}")
                return order

        except Exception as e:
            logger.error(f"❌ Failed to place order: {e}")
            raise

    async def get_account(self, user: User):
        """
        Get account information from the appropriate trading API.

        Args:
            user: User object with selected_trading_mode

        Returns:
            Account information dictionary
        """
        client = self.get_client(user)
        trading_mode = user.selected_trading_mode or "paper"

        try:
            if trading_mode == "paper":
                # Alpaca API
                account = client.get_account()
                return {
                    "account_number": account.account_number,
                    "cash": float(account.cash),
                    "buying_power": float(account.buying_power),
                    "portfolio_value": float(account.portfolio_value),
                    "equity": float(account.equity),
                    "api": "Alpaca Paper"
                }
            else:
                # Schwab API (sync methods)
                account = client.get_account_info()
                if not account:
                    raise Exception("Failed to get Schwab account info")
                balances = account.get("securitiesAccount", {}).get("currentBalances", {})
                return {
                    "account_number": account.get("securitiesAccount", {}).get("accountNumber"),
                    "cash": balances.get("cashBalance", 0),
                    "buying_power": balances.get("buyingPower", 0),
                    "portfolio_value": balances.get("liquidationValue", 0),
                    "equity": balances.get("equity", 0),
                    "api": "Schwab Live"
                }
        except Exception as e:
            logger.error(f"❌ Failed to get account info: {e}")
            raise

    async def get_positions(self, user: User):
        """
        Get current positions from the appropriate trading API.

        Args:
            user: User object with selected_trading_mode

        Returns:
            List of positions
        """
        client = self.get_client(user)
        trading_mode = user.selected_trading_mode or "paper"

        try:
            if trading_mode == "paper":
                # Alpaca API
                positions = client.get_all_positions()
                return [
                    {
                        "symbol": pos.symbol,
                        "qty": int(pos.qty),
                        "avg_entry_price": float(pos.avg_entry_price),
                        "current_price": float(pos.current_price),
                        "unrealized_pl": float(pos.unrealized_pl),
                        "unrealized_plpc": float(pos.unrealized_plpc),
                        "api": "Alpaca Paper"
                    }
                    for pos in positions
                ]
            else:
                # Schwab API (sync methods, returns simplified format)
                positions = client.get_positions()
                if positions is None:
                    raise Exception("Failed to get Schwab positions")
                return [
                    {
                        "symbol": pos.get("symbol"),
                        "qty": pos.get("quantity", 0),
                        "avg_entry_price": pos.get("average_price", 0),
                        "current_price": pos.get("current_price", 0),
                        "unrealized_pl": pos.get("unrealized_pnl", 0),
                        "unrealized_plpc": pos.get("day_pnl_percent", 0),
                        "api": "Schwab Live"
                    }
                    for pos in positions
                ]
        except Exception as e:
            logger.error(f"❌ Failed to get positions: {e}")
            raise

    def close_all_clients(self):
        """
        Close all client connections.

        Useful for cleanup during shutdown.
        """
        for mode, client in self._clients.items():
            try:
                if hasattr(client, 'close'):
                    client.close()
                logger.info(f"Closed {mode} trading client")
            except Exception as e:
                logger.error(f"Error closing {mode} client: {e}")

        self._clients.clear()


# Global singleton instance
trading_manager = TradingClientManager()

"""
Trading Client Manager for hot-swapping between paper and live trading APIs.

This module manages the trading API clients (Tradier Sandbox and Tradier Live)
and provides seamless switching between them without server restart.

The manager maintains client instances and routes order execution to the
appropriate API based on the user's selected trading mode.
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path to allow imports
sys.path.append(str(Path(__file__).parent.parent))

from config import TradingMode
from models import User

logger = logging.getLogger(__name__)


class TradingClientManager:
    """
    Singleton manager for trading API clients.

    Maintains instances of both Tradier Sandbox and Tradier Live clients
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
            Trading client instance (Tradier sandbox for paper, Tradier live for live)

        Raises:
            ValueError: If trading mode is invalid
        """
        trading_mode = user.selected_trading_mode or "paper"

        if trading_mode not in ["paper", "live"]:
            raise ValueError(f"Invalid trading mode: {trading_mode}")

        # Get or create client for this mode
        if trading_mode == "paper":
            return self._get_tradier_client(env="sandbox")
        else:
            return self._get_tradier_client(env="live")

    def _get_tradier_client(self, env: str = "sandbox"):
        """
        Get or create Tradier client for the specified environment.

        Args:
            env: "sandbox" for paper trading, "live" for live trading

        Returns:
            TradierClient instance
        """
        # Use the env type to key the cache
        cache_key = TradingMode.PAPER if env == "sandbox" else TradingMode.LIVE

        if cache_key not in self._clients:
            try:
                from tradier_integration.client import TradierClient

                self._clients[cache_key] = TradierClient(env=env)
                logger.info(f"✅ Tradier {env} client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Tradier {env} client: {e}")
                raise

        return self._clients[cache_key]

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

        logger.info(f"Placing {side} order for {qty} {symbol} via {trading_mode} trading (Tradier)")

        try:
            # Both paper and live modes use Tradier (sandbox vs live)
            option_symbol = kwargs.get("option_symbol")
            if not option_symbol:
                raise ValueError(
                    f"option_symbol is required for option orders (underlying: {symbol}). "
                    "Ensure the strategy has a valid option contract selected."
                )

            # Map generic buy/sell to Tradier option sides
            # Only long positions supported — buy_to_open on entry, sell_to_close on exit
            side_map = {
                "buy":  "buy_to_open",
                "sell": "sell_to_close",
            }
            tradier_side = side_map.get(side)
            if not tradier_side:
                raise ValueError(f"Unsupported option side: {side}")

            # For limit orders pass the midpoint price; market is default
            limit_price = kwargs.get("limit_price")

            order = await asyncio.to_thread(
                client.place_option_order,
                symbol=symbol,
                option_symbol=option_symbol,
                side=tradier_side,
                quantity=qty,
                order_type=order_type,
                duration="day",
                price=limit_price,
            )

            logger.info(
                f"Tradier {trading_mode} order placed: id={order.get('id')} "
                f"status={order.get('status')} "
                f"{tradier_side} {qty}x {option_symbol}"
            )
            return order

        except Exception as e:
            logger.error(f"❌ Failed to place order: {e}")
            raise

    async def preview_order(self, user: User, symbol: str, qty: int, side: str, order_type: str = "market", **kwargs):
        """
        Preview an order via the broker without submitting it.

        Returns the broker's preview dict (commission, fees, order_cost,
        margin_change, day_trades, etc.) on success. Raises on rejection.

        Works for both Tradier sandbox (paper) and Tradier live modes.
        """
        client = self.get_client(user)
        trading_mode = user.selected_trading_mode or "paper"

        option_symbol = kwargs.get("option_symbol")
        if not option_symbol:
            raise ValueError(
                f"option_symbol is required for option preview (underlying: {symbol})"
            )

        side_map = {"buy": "buy_to_open", "sell": "sell_to_close"}
        tradier_side = side_map.get(side)
        if not tradier_side:
            raise ValueError(f"Unsupported option side for preview: {side}")

        limit_price = kwargs.get("limit_price")

        preview = await asyncio.to_thread(
            client.preview_option_order,
            symbol=symbol,
            option_symbol=option_symbol,
            side=tradier_side,
            quantity=qty,
            order_type=order_type,
            duration="day",
            price=limit_price,
        )
        logger.info(
            f"Tradier {trading_mode} option preview: {tradier_side} {qty}x {option_symbol} "
            f"cost=${preview.get('order_cost')} commission=${preview.get('commission')} "
            f"fees=${preview.get('fees')}"
        )
        return preview

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
            # Both paper and live use Tradier (sandbox vs live)
            balances = client.get_balances()
            margin = balances.get("margin") or balances.get("cash") or {}
            buying_power = (
                margin.get("stock_buying_power")
                or margin.get("cash_available_for_trading")
                or balances.get("total_cash", 0)
            )
            api_label = f"Tradier {'Sandbox' if trading_mode == 'paper' else 'Live'}"
            return {
                "account_number": balances.get("account_number", ""),
                "cash": float(balances.get("total_cash", 0)),
                "buying_power": float(buying_power),
                "portfolio_value": float(balances.get("total_equity", 0)),
                "equity": float(balances.get("total_equity", 0)),
                "open_pl": float(balances.get("open_pl", 0)),
                "api": api_label
            }
        except Exception as e:
            logger.error(f"❌ Failed to get account info: {e}")
            raise

    async def get_history(
        self,
        user: User,
        page: int = 1,
        limit: int = 25,
        symbol: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ):
        """
        Get transaction history from the appropriate trading API.
        Note: Tradier detailed history is only available for live accounts.
        """
        client = self.get_client(user)
        trading_mode = user.selected_trading_mode or "paper"

        try:
            # Both paper and live use Tradier (sandbox vs live)
            events = client.get_history(
                page=page,
                limit=limit,
                symbol=symbol,
                start=start,
                end=end,
            )
            result = []
            for e in events:
                desc = (e.get("description") or "").lower()
                side = "BUY" if "bought" in desc else ("SELL" if "sold" in desc else "")
                result.append({
                    "date": e.get("date"),
                    "type": e.get("type"),
                    "symbol": e.get("symbol"),
                    "side": side,
                    "quantity": e.get("quantity"),
                    "price": e.get("price"),
                    "amount": e.get("amount"),
                    "description": e.get("description"),
                    "commission": e.get("commission"),
                })
            return result
        except Exception as e:
            logger.error(f"❌ Failed to get history: {e}")
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
            # Both paper and live use Tradier (sandbox vs live)
            positions = client.get_positions()
            api_label = f"Tradier {'Sandbox' if trading_mode == 'paper' else 'Live'}"
            return [
                {
                    "symbol": pos.get("symbol", ""),
                    "qty": float(pos.get("quantity", 0)),
                    "avg_entry_price": float(pos.get("cost_basis", 0)) / max(float(pos.get("quantity", 1)), 1),
                    "current_price": 0.0,  # Tradier positions endpoint doesn't include live price
                    "unrealized_pl": 0.0,
                    "unrealized_plpc": 0.0,
                    "cost_basis": float(pos.get("cost_basis", 0)),
                    "date_acquired": pos.get("date_acquired", ""),
                    "api": api_label
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

"""
Schwab API Client for account info and trade execution.

Uses schwab-py library for OAuth authentication and API calls.
Data retrieval (market data, quotes, bars) will be handled by Alpaca.
"""
import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime

try:
    from schwab import auth, client
    from schwab.auth import easy_client
    from schwab.client import Client
    SCHWAB_AVAILABLE = True
except ImportError:
    SCHWAB_AVAILABLE = False
    print("Warning: schwab-py not installed. Install with: pip install schwab-py")

from config import settings


class SchwabClient:
    """
    Schwab API client for account operations and trade execution.

    This client handles:
    - OAuth authentication
    - Account information (balances, buying power)
    - Position retrieval
    - Order placement and management

    Market data (quotes, bars, real-time) is handled separately by Alpaca.
    """

    def __init__(self):
        """Initialize Schwab client with OAuth credentials."""
        if not SCHWAB_AVAILABLE:
            raise ImportError("schwab-py library not installed")

        self.app_key = settings.SCHWAB_APP_KEY
        self.app_secret = settings.SCHWAB_APP_SECRET
        self.callback_url = settings.SCHWAB_CALLBACK_URL
        self.token_path = settings.SCHWAB_TOKEN_PATH

        self._client: Optional[Client] = None
        self._account_hash: Optional[str] = None

    def authenticate(self, interactive: bool = False) -> bool:
        """
        Authenticate with Schwab API.

        Args:
            interactive: If True, will open browser for OAuth flow.
                        If False, will try to use existing token only.

        Returns:
            True if authentication successful, False otherwise.

        Note:
            Token expires every 7 days. The schwab-py library automatically
            refreshes the access token (which expires hourly) using the refresh token.

            For initial setup or when token expires, run:
            python3 schwab_auth_setup.py
        """
        try:
            print(f"Authenticating with Schwab API...")

            # Check if token file exists
            if not os.path.exists(self.token_path):
                print(f"❌ No token file found at {self.token_path}")
                print("💡 Run: python3 schwab_auth_setup.py to authenticate")
                return False

            self._check_token_expiry()

            # Use client_from_token_file for non-interactive loading
            # This will automatically refresh the access token if needed
            self._client = auth.client_from_token_file(
                token_path=self.token_path,
                api_key=self.app_key,
                app_secret=self.app_secret
            )

            print("✅ Schwab authentication successful")
            return self._client is not None

        except Exception as e:
            print(f"❌ Schwab authentication failed: {e}")
            print("💡 Tip: Token may have expired. Run: python3 schwab_auth_setup.py")
            return False

    def _check_token_expiry(self):
        """Check token expiration and log warning if close to expiry."""
        try:
            if not os.path.exists(self.token_path):
                return

            with open(self.token_path, 'r') as f:
                token_data = json.load(f)

            if 'expires_at' in token_data:
                from datetime import datetime, timedelta
                expires_at = datetime.fromtimestamp(token_data['expires_at'])
                now = datetime.now()
                time_remaining = expires_at - now

                if time_remaining < timedelta(days=1):
                    print(f"⚠️  Warning: Schwab token expires in {time_remaining}")
                    print("💡 Token will auto-refresh on next API call")
                elif time_remaining < timedelta(days=2):
                    print(f"ℹ️  Schwab token expires in {time_remaining.days} days")
        except Exception as e:
            # Don't fail authentication if we can't check expiry
            print(f"Could not check token expiry: {e}")

    def get_account_info(self, account_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get account information including balances and buying power.

        Args:
            account_hash: Schwab account hash. If None, uses first account.

        Returns:
            Dict with account info or None if error.
        """
        if not self._client:
            if not self.authenticate():
                return None

        try:
            # Get all accounts if hash not provided
            if not account_hash:
                print("Getting Schwab account numbers...")
                accounts_response = self._client.get_account_numbers()
                print(f"Account numbers response status: {accounts_response.status_code}")

                if accounts_response.status_code != 200:
                    print(f"Failed to get account numbers: {accounts_response.status_code}")
                    print(f"Response: {accounts_response.text}")
                    return None

                accounts = accounts_response.json()
                print(f"Found {len(accounts) if accounts else 0} accounts")

                if not accounts or len(accounts) == 0:
                    print("No Schwab accounts found")
                    return None

                # Use first account
                account_hash = accounts[0]['hashValue']
                self._account_hash = account_hash
                print(f"Using account hash: {account_hash[:8]}...")

            # Get detailed account info
            print(f"Getting account details for hash: {account_hash[:8] if account_hash else 'None'}...")
            account_response = self._client.get_account(
                account_hash,
                fields=client.Client.Account.Fields.POSITIONS
            )

            print(f"Account details response status: {account_response.status_code}")
            if account_response.status_code != 200:
                print(f"Failed to get account details: {account_response.text}")
                return None

            return account_response.json()
        except Exception as e:
            import traceback
            print(f"Error fetching Schwab account info: {type(e).__name__}: {e}")
            print(traceback.format_exc())
            return None

    def get_account_balances(self, account_hash: Optional[str] = None) -> Optional[Dict[str, float]]:
        """
        Get account balances in simplified format.

        Returns:
            Dict with balance info: {
                'cash': float,
                'buying_power': float,
                'equity': float,
                'market_value': float
            }
        """
        account_data = self.get_account_info(account_hash)

        if not account_data:
            return None

        try:
            balances = account_data['securitiesAccount']['currentBalances']

            return {
                'cash': balances.get('cashBalance', 0.0),
                'buying_power': balances.get('buyingPower', 0.0),
                'equity': balances.get('equity', 0.0),
                'market_value': balances.get('longMarketValue', 0.0) + balances.get('shortMarketValue', 0.0),
                'cash_available_for_trading': balances.get('cashAvailableForTrading', 0.0),
                'day_trading_buying_power': balances.get('dayTradingBuyingPower', 0.0),
            }
        except KeyError as e:
            print(f"Error parsing Schwab balances: {e}")
            return None

    def get_positions(self, account_hash: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Get current positions from Schwab account.

        Returns:
            List of position dicts with symbol, quantity, cost basis, market value, etc.
        """
        account_data = self.get_account_info(account_hash)

        if not account_data:
            return None

        try:
            positions = account_data['securitiesAccount'].get('positions', [])

            simplified_positions = []
            for pos in positions:
                instrument = pos['instrument']

                simplified_positions.append({
                    'symbol': instrument['symbol'],
                    'asset_type': instrument['assetType'],
                    'quantity': pos.get('longQuantity', 0) - pos.get('shortQuantity', 0),
                    'average_price': pos.get('averagePrice', 0.0),
                    'market_value': pos.get('marketValue', 0.0),
                    'current_price': pos.get('currentDayProfitLoss', 0.0) / pos.get('longQuantity', 1) if pos.get('longQuantity', 0) > 0 else 0.0,
                    'unrealized_pnl': pos.get('currentDayProfitLoss', 0.0),
                    'day_pnl_percent': pos.get('currentDayProfitLossPercentage', 0.0),
                })

            return simplified_positions
        except KeyError as e:
            print(f"Error parsing Schwab positions: {e}")
            return None

    def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,  # 'BUY' or 'SELL'
        order_type: str = 'MARKET',  # 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        account_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Place an order on Schwab.

        Args:
            symbol: Stock/option symbol
            quantity: Number of shares/contracts
            side: 'BUY' or 'SELL'
            order_type: 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
            limit_price: Required for LIMIT and STOP_LIMIT orders
            stop_price: Required for STOP and STOP_LIMIT orders
            account_hash: Schwab account hash

        Returns:
            Order response dict or None if error
        """
        if not self._client:
            if not self.authenticate():
                return None

        if not account_hash:
            account_hash = self._account_hash
            if not account_hash:
                # Get first account
                accounts_response = self._client.get_account_numbers()
                accounts = accounts_response.json()
                if accounts and len(accounts) > 0:
                    account_hash = accounts[0]['hashValue']
                    self._account_hash = account_hash
                else:
                    print("No Schwab account found for order placement")
                    return None

        try:
            # Build order spec
            from schwab.orders.equities import equity_buy_market, equity_sell_market, equity_buy_limit, equity_sell_limit

            # TODO: Implement full order builder with all order types
            # For now, support basic market orders

            if order_type == 'MARKET':
                if side.upper() == 'BUY':
                    order_spec = equity_buy_market(symbol, quantity)
                else:
                    order_spec = equity_sell_market(symbol, quantity)
            elif order_type == 'LIMIT' and limit_price:
                if side.upper() == 'BUY':
                    order_spec = equity_buy_limit(symbol, quantity, limit_price)
                else:
                    order_spec = equity_sell_limit(symbol, quantity, limit_price)
            else:
                print(f"Order type {order_type} not yet implemented")
                return None

            # Place order
            response = self._client.place_order(account_hash, order_spec)

            # Get order ID from response headers
            order_id = response.headers.get('location', '').split('/')[-1]

            return {
                'order_id': order_id,
                'status': 'SUBMITTED',
                'symbol': symbol,
                'quantity': quantity,
                'side': side,
                'order_type': order_type,
                'submitted_at': datetime.utcnow().isoformat()
            }
        except Exception as e:
            print(f"Error placing Schwab order: {e}")
            return None

    def get_order_status(self, order_id: str, account_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get status of a specific order."""
        if not self._client:
            if not self.authenticate():
                return None

        if not account_hash:
            account_hash = self._account_hash

        try:
            response = self._client.get_order(order_id, account_hash)
            return response.json()
        except Exception as e:
            print(f"Error fetching order status: {e}")
            return None

    def cancel_order(self, order_id: str, account_hash: Optional[str] = None) -> bool:
        """Cancel a pending order."""
        if not self._client:
            if not self.authenticate():
                return False

        if not account_hash:
            account_hash = self._account_hash

        try:
            self._client.cancel_order(order_id, account_hash)
            return True
        except Exception as e:
            print(f"Error canceling order: {e}")
            return False


# Singleton instance
_schwab_client: Optional[SchwabClient] = None


def get_schwab_client() -> SchwabClient:
    """Get singleton Schwab client instance."""
    global _schwab_client
    if _schwab_client is None:
        _schwab_client = SchwabClient()
    return _schwab_client

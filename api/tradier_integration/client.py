"""
Tradier Brokerage API client.

Covers the account endpoints described in the Tradier Account Details guide:
  - User profile (account IDs)
  - Account balances
  - Account positions
  - Account orders (today)
  - Account history (transactions)
  - Account gain/loss (realized P&L)
  - Historical account balances (portfolio chart data)
"""
import logging
from typing import Any, Dict, List, Optional, Union

import requests

from config import settings

logger = logging.getLogger(__name__)


class TradierClient:
    """
    HTTP client for Tradier Brokerage Account API.

    Automatically selects sandbox vs. production based on TRADIER_ENV config.
    All methods return parsed JSON or raise on HTTP errors.
    """

    def __init__(self):
        env = settings.TRADIER_ENV.lower()
        if env == "sandbox":
            self._base_url = settings.TRADIER_SANDBOX_BASE_URL.rstrip("/")
            self._token = settings.TRADIER_SANDBOX_API_KEY
            self._account_id = settings.TRADIER_SANDBOX_ACCOUNT_NUMBER
        else:
            self._base_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
            self._token = settings.TRADIER_LIVE_API_KEY
            self._account_id: Optional[str] = None  # fetched from profile on first use

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        url = f"{self._base_url}{path}"
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, data: Optional[Dict] = None) -> Any:
        url = f"{self._base_url}{path}"
        response = self._session.post(url, data=data)
        response.raise_for_status()
        return response.json()

    def _put(self, path: str, data: Optional[Dict] = None) -> Any:
        url = f"{self._base_url}{path}"
        response = self._session.put(url, data=data)
        response.raise_for_status()
        return response.json()

    def _delete(self, path: str) -> Any:
        url = f"{self._base_url}{path}"
        response = self._session.delete(url)
        response.raise_for_status()
        return response.json()

    def _resolve_account_id(self) -> str:
        """Return stored account ID, fetching from profile if not yet known."""
        if self._account_id:
            return self._account_id
        profile = self.get_profile()
        accounts = profile.get("profile", {}).get("account", [])
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not accounts:
            raise RuntimeError("No accounts found in Tradier profile")
        self._account_id = accounts[0]["account_number"]
        return self._account_id

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_profile(self) -> Dict[str, Any]:
        """GET /v1/user/profile — user info and list of account numbers."""
        return self._get("/v1/user/profile")

    def get_balances(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        GET /v1/accounts/{account_id}/balances

        Returns balance dict with keys: total_equity, total_cash, open_pl,
        stock_buying_power, option_buying_power, etc.
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(f"/v1/accounts/{acct}/balances")
        return data.get("balances", data)

    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        GET /v1/accounts/{account_id}/positions

        Returns list of open positions (symbol, quantity, cost_basis, date_acquired).
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(f"/v1/accounts/{acct}/positions")
        positions_wrap = data.get("positions", {})
        if not positions_wrap or positions_wrap == "null":
            return []
        raw = positions_wrap.get("position", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_order(
        self, order_id: Union[str, int], account_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        GET /v1/accounts/{account_id}/orders/{id}

        Fetch a single order by ID. Used to poll order status until terminal
        (filled / rejected / canceled / expired) after submission.
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(f"/v1/accounts/{acct}/orders/{order_id}")
        order_wrap = data.get("order", {})
        if isinstance(order_wrap, list):
            return order_wrap[0] if order_wrap else {}
        return order_wrap or {}

    def get_orders(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        GET /v1/accounts/{account_id}/orders

        Returns today's orders. Single order comes back as dict; normalised to list.
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(f"/v1/accounts/{acct}/orders")
        orders_wrap = data.get("orders", {})
        if not orders_wrap or orders_wrap == "null":
            return []
        raw = orders_wrap.get("order", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_history(
        self,
        account_id: Optional[str] = None,
        period: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
        type: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        symbol: Optional[str] = None,
        exact_match: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        GET /v1/accounts/{account_id}/history

        Without a `period` this returns detailed transaction history (trades,
        dividends, ACH, fees, etc.).  With `period` it returns historical
        balance snapshots (date, value, delta, delta_percent) — useful for
        portfolio performance charts.

        Note: detailed history is not available for sandbox accounts.
        """
        acct = account_id or self._resolve_account_id()
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if period:
            params["period"] = period
        if type:
            params["type"] = type
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        if symbol:
            params["symbol"] = symbol
        if exact_match:
            params["exact_match"] = "true"

        data = self._get(f"/v1/accounts/{acct}/history", params=params)
        history_wrap = data.get("history", {})
        if not history_wrap or history_wrap == "null":
            return []
        # Detailed history uses "event"; balance history uses "day"
        raw = history_wrap.get("event") or history_wrap.get("day", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def create_stream_session(self) -> Dict[str, str]:
        """
        POST /v1/markets/events/session

        Creates a Tradier streaming session. Returns sessionid and WebSocket URL.
        Session is valid for 5 minutes before the WebSocket must be connected.

        Always uses the live endpoint — sandbox does not support market data streaming.
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        url = f"{live_url}/v1/markets/events/session"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        stream = resp.json().get("stream", {})
        return {
            "sessionid": stream.get("sessionid", ""),
            "url": stream.get("url", "wss://ws.tradier.com/v1/markets/events"),
        }

    def place_option_order(
        self,
        symbol: str,
        option_symbol: str,
        side: str,
        quantity: int,
        order_type: str = "market",
        duration: str = "day",
        price: Optional[float] = None,
        account_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /v1/accounts/{account_id}/orders — place a single-leg option order.

        Args:
            symbol:        Underlying symbol (e.g. "TSLA")
            option_symbol: OCC option symbol (e.g. "TSLA250423C00270000")
            side:          buy_to_open | buy_to_close | sell_to_open | sell_to_close
            quantity:      Number of contracts
            order_type:    market | limit | stop | stop_limit
            duration:      day | gtc | pre | post
            price:         Required for limit / stop_limit orders
            account_id:    Optional override; resolved from profile if omitted
        """
        acct = account_id or self._resolve_account_id()
        data: Dict[str, Any] = {
            "class": "option",
            "symbol": symbol,
            "option_symbol": option_symbol,
            "side": side,
            "quantity": str(quantity),
            "type": order_type,
            "duration": duration,
        }
        if price is not None:
            data["price"] = str(price)

        response = self._post(f"/v1/accounts/{acct}/orders", data=data)

        # Tradier returns 200 even for application-level errors
        if "errors" in response:
            errors = response["errors"]
            msg = errors.get("error", errors)
            if isinstance(msg, list):
                msg = "; ".join(msg)
            raise ValueError(f"Tradier order rejected: {msg}")

        order = response.get("order", response)

        # Reject statuses that indicate the order was not accepted
        status = order.get("status", "")
        if status not in ("ok", "pending", "open", "partially_filled", "filled", ""):
            raise ValueError(f"Tradier order not accepted (status={status!r}): {order}")

        return order

    def get_market_clock(self) -> Dict[str, Any]:
        """
        GET /v1/markets/clock — intraday market state.

        Returns dict with keys: date, description, state (pre/open/post/closed),
        timestamp, next_change (time string e.g. "16:00"), next_state.

        Always uses the live endpoint — sandbox does not carry real market data.
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        resp = requests.get(
            f"{live_url}/v1/markets/clock",
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json().get("clock", {})

    def get_history_pricing(
        self,
        symbol: str,
        interval: str = "daily",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        GET /v1/markets/history — historical OHLCV bars for a symbol (or OCC option symbol).

        Always uses the live endpoint — sandbox does not carry real market data.
        Returns the list of day bars (date, open, high, low, close, volume).
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        params: Dict[str, Any] = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = requests.get(
            f"{live_url}/v1/markets/history",
            params=params,
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        history_wrap = data.get("history", {})
        if not history_wrap or history_wrap == "null":
            return []
        raw = history_wrap.get("day", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_timesales(
        self,
        symbol: str,
        interval: str = "5min",
        start: Optional[str] = None,
        end: Optional[str] = None,
        session_filter: str = "all",
    ) -> List[Dict[str, Any]]:
        """
        GET /v1/markets/timesales — intraday OHLCV bars (1min/5min/15min/tick).

        Always uses the live endpoint — sandbox doesn't carry intraday data.
        start/end format: 'YYYY-MM-DD HH:MM'.
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "session_filter": session_filter,
        }
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        resp = requests.get(
            f"{live_url}/v1/markets/timesales",
            params=params,
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        series_wrap = data.get("series") or {}
        if not series_wrap or series_wrap == "null":
            return []
        raw = series_wrap.get("data", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_quotes(self, symbols: List[str]) -> List[Dict[str, Any]]:
        """
        GET /v1/markets/quotes — quotes (last, change, change_percentage, etc.)
        for one or more symbols. Always uses the live endpoint (sandbox lacks
        real market data).
        """
        if not symbols:
            return []
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        resp = requests.get(
            f"{live_url}/v1/markets/quotes",
            params={"symbols": ",".join(symbols)},
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        wrap = data.get("quotes", {})
        if not wrap or wrap == "null":
            return []
        raw = wrap.get("quote", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_option_expirations(self, symbol: str) -> List[str]:
        """
        GET /v1/markets/options/expirations

        Returns sorted list of expiration date strings (YYYY-MM-DD) for the symbol.
        Always uses the live endpoint for market data.
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        resp = requests.get(
            f"{live_url}/v1/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "true", "strikes": "false"},
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        expirations = data.get("expirations", {})
        if not expirations or expirations == "null":
            return []
        dates = expirations.get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        return sorted(dates)

    def get_option_chain(
        self,
        symbol: str,
        expiration: str,
        greeks: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        GET /v1/markets/options/chains

        Returns all option contracts for the given symbol and expiration date.
        Each contract dict includes bid, ask, volume, open_interest, and greeks
        (delta, gamma, theta, vega) when greeks=True.

        Always uses the live endpoint for market data.
        """
        live_url = settings.TRADIER_LIVE_BASE_URL.rstrip("/")
        live_token = settings.TRADIER_LIVE_API_KEY
        resp = requests.get(
            f"{live_url}/v1/markets/options/chains",
            params={"symbol": symbol, "expiration": expiration, "greeks": str(greeks).lower()},
            headers={"Authorization": f"Bearer {live_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        options_wrap = data.get("options", {})
        if not options_wrap or options_wrap == "null":
            return []
        raw = options_wrap.get("option", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_historical_balances(
        self,
        account_id: Optional[str] = None,
        period: str = "MONTH",
    ) -> Dict[str, Any]:
        """
        GET /v1/accounts/{account_id}/historical-balances

        Returns daily account value snapshots for charting an equity curve.
        Period is one of WEEK | MONTH | YTD | YEAR | YEAR_3 | YEAR_5 | ALL.

        Response shape: {"balances": [{"date": ..., "value": ...}, ...],
                        "delta": ..., "deltaPercent": ...}
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(
            f"/v1/accounts/{acct}/historical-balances",
            params={"period": period.upper()},
        )
        balances = data.get("balances", [])
        if balances is None or balances == "null":
            balances = []
        if isinstance(balances, dict):
            balances = [balances]
        return {
            "balances": balances,
            "delta": data.get("delta", 0.0),
            "deltaPercent": data.get("deltaPercent", 0.0),
        }

    def get_gainloss(
        self,
        account_id: Optional[str] = None,
        page: int = 1,
        limit: int = 25,
    ) -> List[Dict[str, Any]]:
        """
        GET /v1/accounts/{account_id}/gainloss

        Returns realized gain/loss for closed positions (updated nightly).
        """
        acct = account_id or self._resolve_account_id()
        data = self._get(
            f"/v1/accounts/{acct}/gainloss",
            params={"page": page, "limit": limit},
        )
        gl_wrap = data.get("gainloss", {})
        if not gl_wrap or gl_wrap == "null":
            return []
        raw = gl_wrap.get("closed_position", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw


    # ------------------------------------------------------------------
    # Watchlists
    # ------------------------------------------------------------------

    def get_watchlists(self) -> List[Dict[str, Any]]:
        """
        GET /v1/watchlists — list all of the user's watchlists.

        Each entry is {name, id, public_id}.
        """
        data = self._get("/v1/watchlists")
        wrap = data.get("watchlists", {})
        if not wrap or wrap == "null":
            return []
        raw = wrap.get("watchlist", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def get_watchlist(self, watchlist_id: str) -> Dict[str, Any]:
        """
        GET /v1/watchlists/{watchlist_id} — fetch a single watchlist.

        Returns dict with {name, id, public_id, items: [{symbol, id}, ...]}.
        """
        data = self._get(f"/v1/watchlists/{watchlist_id}")
        return self._normalize_watchlist(data.get("watchlist", {}))

    def create_watchlist(self, name: str, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        POST /v1/watchlists — create a new watchlist.

        `symbols` may be omitted or empty; Tradier requires the field but
        accepts empty input.
        """
        payload = {
            "name": name,
            "symbols": ",".join(symbols) if symbols else "",
        }
        data = self._post("/v1/watchlists", data=payload)
        return self._normalize_watchlist(data.get("watchlist", {}))

    def update_watchlist(
        self,
        watchlist_id: str,
        name: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        PUT /v1/watchlists/{watchlist_id} — overwrite an existing watchlist.

        Renames the watchlist and replaces the symbol list.
        """
        payload: Dict[str, Any] = {"name": name}
        if symbols is not None:
            payload["symbols"] = ",".join(symbols)
        data = self._put(f"/v1/watchlists/{watchlist_id}", data=payload)
        return self._normalize_watchlist(data.get("watchlist", {}))

    def delete_watchlist(self, watchlist_id: str) -> List[Dict[str, Any]]:
        """
        DELETE /v1/watchlists/{watchlist_id} — delete a watchlist.

        Returns the remaining list of watchlists.
        """
        data = self._delete(f"/v1/watchlists/{watchlist_id}")
        wrap = data.get("watchlists", {})
        if not wrap or wrap == "null":
            return []
        raw = wrap.get("watchlist", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    def add_watchlist_symbols(self, watchlist_id: str, symbols: List[str]) -> Dict[str, Any]:
        """
        POST /v1/watchlists/{watchlist_id}/symbols — add symbols to an existing watchlist.
        """
        payload = {"symbols": ",".join(symbols)}
        data = self._post(f"/v1/watchlists/{watchlist_id}/symbols", data=payload)
        return self._normalize_watchlist(data.get("watchlist", {}))

    def remove_watchlist_symbol(self, watchlist_id: str, symbol: str) -> Dict[str, Any]:
        """
        DELETE /v1/watchlists/{watchlist_id}/symbols/{symbol}
        """
        data = self._delete(f"/v1/watchlists/{watchlist_id}/symbols/{symbol}")
        return self._normalize_watchlist(data.get("watchlist", {}))

    @staticmethod
    def _normalize_watchlist(watchlist: Any) -> Dict[str, Any]:
        """Flatten the nested {items:{item:[...]}} wrapper into a plain symbols list."""
        if not watchlist or watchlist == "null":
            return {}
        items_wrap = watchlist.get("items") or {}
        raw = items_wrap.get("item", []) if isinstance(items_wrap, dict) else []
        if isinstance(raw, dict):
            raw = [raw]
        return {
            "name": watchlist.get("name"),
            "id": watchlist.get("id"),
            "public_id": watchlist.get("public_id"),
            "items": raw,
        }


# Module-level singleton
_client: Optional[TradierClient] = None


def get_tradier_client() -> TradierClient:
    global _client
    if _client is None:
        _client = TradierClient()
    return _client

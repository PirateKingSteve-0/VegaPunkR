"""
Options Market Data Service

Provides market data for OPTIONS strategy execution using Alpaca SDK:
- OptionHistoricalDataClient: Bars, snapshots (with greeks), option chain
- OptionDataStream: Real-time quotes/trades (via MultiStreamManager)

Used by strategy_worker.py to fetch real market data for SignalGenerator.
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque

from config import settings
from models import Strategy

# Alpaca SDK imports
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    OptionBarsRequest,
    OptionChainRequest,
    OptionSnapshotRequest,
    OptionLatestQuoteRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

logger = logging.getLogger(__name__)


class OptionsMarketDataService:
    """
    Provides OPTIONS market data for strategy execution.

    Key Methods:
    - get_market_data(): Full market data for SignalGenerator
    - select_contract(): Choose best contract from chain based on strategy params
    - get_snapshot(): Get greeks, IV, bid/ask for a contract
    - get_bars(): Get historical bars for indicator calculations
    """

    def __init__(self):
        self._client: Optional[OptionHistoricalDataClient] = None

        # Price history cache for indicator calculations
        self._price_cache: Dict[str, deque] = {}
        self._volume_cache: Dict[str, deque] = {}
        self._cache_max_length = 100

        # Selected contracts cache (underlying -> contract symbol)
        self._selected_contracts: Dict[str, Dict] = {}
        self._contract_cache_ttl_minutes = 5

    @property
    def client(self) -> OptionHistoricalDataClient:
        """Lazy initialization of option data client"""
        if self._client is None:
            self._client = OptionHistoricalDataClient(
                api_key=settings.ALPACA_PAPER_API_KEY,
                secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            )
            logger.info("OptionHistoricalDataClient initialized")
        return self._client

    async def get_market_data(
        self,
        strategy: Strategy,
        underlying: str
    ) -> Optional[Dict]:
        """
        Get complete market data for an options strategy.

        Flow:
        1. Select appropriate contract based on strategy params (delta, OI, spread)
        2. Get snapshot with greeks
        3. Return data formatted for SignalGenerator

        Args:
            strategy: Strategy object with params_json (delta_min, delta_max, etc.)
            underlying: Underlying symbol from strategy.instruments (e.g., "SPY")

        Returns:
            Dict with: symbol, price, volume, bid, ask, delta, open_interest, etc.
            Returns None if no suitable contract or data unavailable.
        """
        params = strategy.params_json

        # 1. Select or get cached contract
        contract_symbol = await self.select_contract(underlying, params)

        if not contract_symbol:
            logger.warning(f"No suitable contract found for {underlying}")
            return None

        logger.debug(f"Using contract: {contract_symbol}")

        # 2. Get snapshot with greeks
        snapshot_data = await self.get_snapshot(contract_symbol)

        if not snapshot_data:
            return None

        # Add underlying reference
        snapshot_data['underlying'] = underlying

        # Update price cache for indicator calculations
        self._update_cache(
            contract_symbol,
            snapshot_data.get('price', 0),
            snapshot_data.get('volume', 0)
        )

        return snapshot_data

    async def get_snapshot(self, contract_symbol: str) -> Optional[Dict]:
        """
        Get snapshot with greeks for a specific contract.

        Args:
            contract_symbol: Option contract symbol (e.g., "SPY250120C00450000")

        Returns:
            Dict with price, bid, ask, delta, gamma, theta, vega, IV, open_interest
        """
        try:
            snapshot_request = OptionSnapshotRequest(
                symbol_or_symbols=contract_symbol
            )
            snapshots = self.client.get_option_snapshot(snapshot_request)

            if contract_symbol not in snapshots:
                logger.warning(f"No snapshot data for {contract_symbol}")
                return None

            snapshot = snapshots[contract_symbol]

            # Extract data from snapshot
            latest_quote = snapshot.latest_quote
            latest_trade = snapshot.latest_trade
            greeks = snapshot.greeks

            # Build market data dict
            market_data = {
                'symbol': contract_symbol,
                'price': float(latest_trade.price) if latest_trade else 0.0,
                'volume': int(latest_trade.size) if latest_trade else 0,
                'bid': float(latest_quote.bid_price) if latest_quote else 0.0,
                'ask': float(latest_quote.ask_price) if latest_quote else 0.0,
                'bid_size': int(latest_quote.bid_size) if latest_quote else 0,
                'ask_size': int(latest_quote.ask_size) if latest_quote else 0,
                'open_interest': int(snapshot.open_interest) if snapshot.open_interest else 0,
                'implied_volatility': float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0,
                'timestamp': datetime.utcnow().isoformat()
            }

            # Add greeks if available
            if greeks:
                market_data['delta'] = float(greeks.delta) if greeks.delta else 0.0
                market_data['gamma'] = float(greeks.gamma) if greeks.gamma else 0.0
                market_data['theta'] = float(greeks.theta) if greeks.theta else 0.0
                market_data['vega'] = float(greeks.vega) if greeks.vega else 0.0

            return market_data

        except Exception as e:
            logger.error(f"Error getting option snapshot for {contract_symbol}: {str(e)}")
            return None

    async def select_contract(
        self,
        underlying: str,
        params: Dict
    ) -> Optional[str]:
        """
        Select the best option contract based on strategy parameters.

        Selection Criteria (from params):
        - delta_min / delta_max: Delta range (e.g., 0.60-0.85)
        - min_open_interest: Minimum open interest (e.g., 3000)
        - max_bid_ask_spread: Maximum spread as decimal (e.g., 0.20)
        - option_type: "0DTE" for same-day expiration

        Args:
            underlying: Underlying symbol (e.g., "SPY")
            params: Strategy params_json

        Returns:
            Option contract symbol (e.g., "SPY250120C00450000") or None
        """
        # Check cache first
        cache_key = f"{underlying}_{params.get('option_type', '0DTE')}"

        if cache_key in self._selected_contracts:
            cached = self._selected_contracts[cache_key]
            cache_age = datetime.utcnow() - cached['timestamp']

            if cache_age.total_seconds() < self._contract_cache_ttl_minutes * 60:
                return cached['contract']

        try:
            # Get option chain for underlying
            chain_request = OptionChainRequest(underlying_symbol=underlying)
            chain = self.client.get_option_chain(chain_request)

            if not chain:
                logger.warning(f"No option chain available for {underlying}")
                return None

            # Filter parameters from strategy
            delta_min = params.get('delta_min', 0.50)
            delta_max = params.get('delta_max', 0.85)
            min_open_interest = params.get('min_open_interest', 1000)
            max_bid_ask_spread = params.get('max_bid_ask_spread', 0.30)

            best_contract = None
            best_score = -1

            for contract_symbol, snapshot in chain.items():
                # Check greeks are available
                if not snapshot.greeks:
                    continue

                delta = abs(float(snapshot.greeks.delta or 0))

                # Delta filter
                if not (delta_min <= delta <= delta_max):
                    continue

                # Open interest filter
                oi = int(snapshot.open_interest or 0)
                if oi < min_open_interest:
                    continue

                # Bid-ask spread filter
                if snapshot.latest_quote:
                    bid = float(snapshot.latest_quote.bid_price or 0)
                    ask = float(snapshot.latest_quote.ask_price or 0)
                    if ask > 0:
                        spread = (ask - bid) / ask
                        if spread > max_bid_ask_spread:
                            continue

                # Score: prefer delta closer to target (midpoint of range)
                target_delta = (delta_min + delta_max) / 2
                score = 1.0 - abs(delta - target_delta)

                # Boost score for higher open interest (more liquidity)
                score += min(oi / 10000, 0.5)  # Max 0.5 bonus

                if score > best_score:
                    best_score = score
                    best_contract = contract_symbol

            if best_contract:
                # Cache the selection
                self._selected_contracts[cache_key] = {
                    'contract': best_contract,
                    'timestamp': datetime.utcnow()
                }
                logger.info(
                    f"Selected contract for {underlying}: {best_contract} "
                    f"(score: {best_score:.2f})"
                )
            else:
                logger.warning(f"No contract meets criteria for {underlying}")

            return best_contract

        except Exception as e:
            logger.error(f"Error selecting option contract for {underlying}: {str(e)}")
            return None

    def get_bars(
        self,
        symbol: str,
        timeframe_minutes: int = 1,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get historical bars for indicator calculations (EMA, VWAP).

        Args:
            symbol: Option contract symbol
            timeframe_minutes: Bar timeframe (1, 5, 15, etc.)
            limit: Number of bars to fetch

        Returns:
            List of bar dicts with open, high, low, close, volume
        """
        try:
            request = OptionBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame(timeframe_minutes, TimeFrameUnit.Minute),
                start=datetime.utcnow() - timedelta(minutes=timeframe_minutes * limit * 2),
                limit=limit
            )
            bars = self.client.get_option_bars(request)

            if symbol not in bars.data:
                return []

            return [
                {
                    'timestamp': bar.timestamp,
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': int(bar.volume)
                }
                for bar in bars.data[symbol]
            ]

        except Exception as e:
            logger.error(f"Error fetching bars for {symbol}: {str(e)}")
            return []

    def get_latest_quote(self, contract_symbol: str) -> Optional[Dict]:
        """
        Get latest quote (bid/ask) for a contract.

        Args:
            contract_symbol: Option contract symbol

        Returns:
            Dict with bid, ask, bid_size, ask_size
        """
        try:
            request = OptionLatestQuoteRequest(symbol_or_symbols=contract_symbol)
            quotes = self.client.get_option_latest_quote(request)

            if contract_symbol not in quotes:
                return None

            quote = quotes[contract_symbol]
            return {
                'symbol': contract_symbol,
                'bid': float(quote.bid_price),
                'ask': float(quote.ask_price),
                'bid_size': int(quote.bid_size),
                'ask_size': int(quote.ask_size),
                'timestamp': quote.timestamp.isoformat() if quote.timestamp else None
            }

        except Exception as e:
            logger.error(f"Error getting quote for {contract_symbol}: {str(e)}")
            return None

    def _update_cache(self, symbol: str, price: float, volume: int):
        """Update price and volume cache for indicator calculations"""
        if symbol not in self._price_cache:
            self._price_cache[symbol] = deque(maxlen=self._cache_max_length)
            self._volume_cache[symbol] = deque(maxlen=self._cache_max_length)

        self._price_cache[symbol].append(price)
        self._volume_cache[symbol].append(volume)

    def clear_contract_cache(self, underlying: Optional[str] = None):
        """Clear cached contract selections"""
        if underlying:
            keys_to_remove = [
                k for k in self._selected_contracts
                if k.startswith(underlying)
            ]
            for key in keys_to_remove:
                del self._selected_contracts[key]
        else:
            self._selected_contracts.clear()


# Singleton instance
_service_instance: Optional[OptionsMarketDataService] = None


def get_options_market_data_service() -> OptionsMarketDataService:
    """Get or create the options market data service singleton"""
    global _service_instance
    if _service_instance is None:
        _service_instance = OptionsMarketDataService()
    return _service_instance

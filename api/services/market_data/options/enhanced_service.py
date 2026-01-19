"""
Enhanced Options Market Data Service

Combines the best of both worlds:
1. Existing REST API polling (reliable, tested)
2. New real-time websocket streaming (faster updates)
3. Enhanced chain fetcher (better contract selection)

This service can be used as a drop-in replacement for the existing
OptionsMarketDataService with added real-time capabilities.
"""

import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import deque

from config import settings
from models import Strategy

# Enhanced components
from services.market_data.options.chain_fetcher import (
    OptionChainFetcher,
    OptionType,
    StrikeFilter
)
from services.market_data.options.realtime_aggregator import (
    RealtimeOptionsAggregator,
    RealtimeOptionData
)

# Existing components (for snapshot fallback)
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest

logger = logging.getLogger(__name__)


class EnhancedOptionsService:
    """
    Enhanced options market data service with real-time capabilities.

    Features:
    - Uses enhanced chain_fetcher for better contract selection
    - Optional real-time streaming via websocket
    - Falls back to REST API if streaming unavailable
    - Maintains backward compatibility with existing code
    """

    def __init__(
        self,
        enable_realtime: bool = False,
        cache_ttl_seconds: int = 300
    ):
        """
        Initialize the enhanced options service.

        Args:
            enable_realtime: Enable real-time websocket streaming
            cache_ttl_seconds: Cache TTL for contract selection
        """
        # Enhanced chain fetcher
        self.chain_fetcher = OptionChainFetcher(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            cache_ttl_seconds=cache_ttl_seconds
        )

        # REST API client (for snapshots)
        self._rest_client: Optional[OptionHistoricalDataClient] = None

        # Real-time streaming (optional)
        self.enable_realtime = enable_realtime
        self._realtime_aggregator: Optional[RealtimeOptionsAggregator] = None
        self._streaming_symbols: set = set()

        # Price/volume cache for indicators
        self._price_cache: Dict[str, deque] = {}
        self._volume_cache: Dict[str, deque] = {}
        self._cache_max_length = 100

    @property
    def rest_client(self) -> OptionHistoricalDataClient:
        """Lazy initialization of REST client."""
        if self._rest_client is None:
            self._rest_client = OptionHistoricalDataClient(
                api_key=settings.ALPACA_PAPER_API_KEY,
                secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            )
        return self._rest_client

    async def start_realtime(self):
        """Start real-time streaming (if enabled)."""
        if not self.enable_realtime:
            logger.info("Real-time streaming is disabled")
            return

        if self._realtime_aggregator is None:
            logger.info("Starting real-time options aggregator...")
            self._realtime_aggregator = RealtimeOptionsAggregator(
                api_key=settings.ALPACA_PAPER_API_KEY,
                secret_key=settings.ALPACA_PAPER_SECRET_KEY,
                feed="indicative"
            )
            await self._realtime_aggregator.start()
            logger.info("✅ Real-time aggregator started")

    async def stop_realtime(self):
        """Stop real-time streaming."""
        if self._realtime_aggregator:
            await self._realtime_aggregator.stop()
            self._realtime_aggregator = None
            self._streaming_symbols.clear()
            logger.info("Real-time aggregator stopped")

    async def get_market_data(
        self,
        strategy: Strategy,
        underlying: str,
        use_realtime: bool = None
    ) -> Optional[Dict]:
        """
        Get complete market data for an options strategy.

        This is the main entry point - compatible with existing code.

        Flow:
        1. Select best contract using enhanced chain fetcher
        2. Get data from real-time stream OR REST API
        3. Return formatted data for SignalGenerator

        Args:
            strategy: Strategy object with params_json
            underlying: Underlying symbol (e.g., "SPY")
            use_realtime: Override to force real-time or REST
                         None = use class setting

        Returns:
            Dict with: symbol, price, volume, bid, ask, delta, gamma, etc.
        """
        params = strategy.params_json

        # 1. Select best contract
        contract_symbol = await self.select_best_contract(underlying, params)

        if not contract_symbol:
            logger.warning(f"No suitable contract found for {underlying}")
            return None

        logger.debug(f"Selected contract: {contract_symbol}")

        # 2. Determine data source
        should_use_realtime = (
            use_realtime if use_realtime is not None else self.enable_realtime
        )

        # 3. Get market data
        if should_use_realtime and self._realtime_aggregator:
            market_data = await self._get_realtime_data(contract_symbol)
        else:
            market_data = await self._get_rest_data(contract_symbol)

        if not market_data:
            return None

        # Add metadata
        market_data['underlying'] = underlying
        market_data['strategy_id'] = strategy.id

        # Update cache for indicators
        self._update_cache(
            contract_symbol,
            market_data.get('price', 0),
            market_data.get('volume', 0)
        )

        return market_data

    async def select_best_contract(
        self,
        underlying: str,
        params: Dict
    ) -> Optional[str]:
        """
        Select the best option contract using enhanced chain fetcher.

        This method is backward-compatible with the existing interface
        but uses the new enhanced chain fetcher.

        Args:
            underlying: Underlying symbol
            params: Strategy params_json with:
                - delta_min, delta_max
                - min_open_interest
                - max_bid_ask_spread
                - option_type ("0DTE" or expiration date)

        Returns:
            Option contract symbol or None
        """
        try:
            # Parse parameters (with paper-trading friendly defaults)
            delta_min = params.get('delta_min', 0.40)  # Relaxed for paper trading
            delta_max = params.get('delta_max', 0.90)  # Relaxed for paper trading
            min_oi = params.get('min_open_interest', 0)  # 0 for paper (no OI data)
            max_spread = params.get('max_bid_ask_spread', 1.0)  # Relaxed for paper
            option_type_param = params.get('option_type', '0DTE')

            # Determine expiration
            from datetime import date
            expiration_date = None
            if option_type_param == '0DTE':
                expiration_date = date.today()

            # Select contract
            contract = self.chain_fetcher.select_best_contract(
                underlying=underlying,
                expiration_date=expiration_date,
                delta_min=delta_min,
                delta_max=delta_max,
                min_open_interest=min_oi,
                max_bid_ask_spread_pct=max_spread,
                option_type=OptionType.CALL  # TODO: Support puts from params
            )

            if contract:
                logger.info(
                    f"Selected {contract.symbol}: "
                    f"Delta={contract.delta:.3f}, "
                    f"OI={contract.open_interest}, "
                    f"Score={contract.score:.2f}"
                )
                return contract.symbol

            return None

        except Exception as e:
            logger.error(f"Error selecting contract for {underlying}: {e}")
            return None

    async def _get_realtime_data(self, contract_symbol: str) -> Optional[Dict]:
        """
        Get data from real-time stream.

        If not subscribed, subscribes automatically.
        Falls back to REST if no data available.
        """
        if not self._realtime_aggregator:
            return await self._get_rest_data(contract_symbol)

        # Subscribe if not already streaming
        if contract_symbol not in self._streaming_symbols:
            await self._realtime_aggregator.subscribe(contract_symbol)
            self._streaming_symbols.add(contract_symbol)
            logger.info(f"Subscribed to real-time data: {contract_symbol}")

            # Wait a moment for initial data
            await asyncio.sleep(0.5)

        # Get aggregated data
        data = await self._realtime_aggregator.get_data(contract_symbol)

        if not data:
            logger.warning(f"No real-time data for {contract_symbol}, falling back to REST")
            return await self._get_rest_data(contract_symbol)

        # Format for SignalGenerator
        return self._format_realtime_data(data)

    async def _get_rest_data(self, contract_symbol: str) -> Optional[Dict]:
        """Get data from REST API (existing method)."""
        try:
            request = OptionSnapshotRequest(symbol_or_symbols=contract_symbol)
            snapshots = self.rest_client.get_option_snapshot(request)

            if contract_symbol not in snapshots:
                return None

            snapshot = snapshots[contract_symbol]
            return self._format_snapshot_data(snapshot)

        except Exception as e:
            logger.error(f"Error fetching REST data for {contract_symbol}: {e}")
            return None

    def _format_realtime_data(self, data: RealtimeOptionData) -> Dict:
        """Format real-time data for SignalGenerator."""
        return {
            'symbol': data.symbol,
            'price': data.last_price or data.mid or 0.0,
            'bid': data.bid,
            'ask': data.ask,
            'volume': data.volume,
            'trade_count': data.trade_count,
            'delta': data.delta,
            'gamma': data.gamma,
            'theta': data.theta,
            'vega': data.vega,
            'open_interest': data.open_interest,
            'implied_volatility': data.implied_volatility,
            'timestamp': data.timestamp.isoformat(),
            'data_source': 'realtime'
        }

    def _format_snapshot_data(self, snapshot) -> Dict:
        """Format REST snapshot data for SignalGenerator."""
        data = {
            'symbol': snapshot.symbol,
            'price': 0.0,
            'bid': None,
            'ask': None,
            'volume': 0,
            'delta': None,
            'gamma': None,
            'theta': None,
            'vega': None,
            'open_interest': snapshot.open_interest,
            'implied_volatility': snapshot.implied_volatility,
            'data_source': 'rest'
        }

        # Latest trade
        if snapshot.latest_trade:
            data['price'] = float(snapshot.latest_trade.price)

        # Latest quote
        if snapshot.latest_quote:
            data['bid'] = float(snapshot.latest_quote.bid_price or 0)
            data['ask'] = float(snapshot.latest_quote.ask_price or 0)
            if not data['price'] and data['bid'] and data['ask']:
                data['price'] = (data['bid'] + data['ask']) / 2

        # Greeks
        if snapshot.greeks:
            data['delta'] = float(snapshot.greeks.delta) if snapshot.greeks.delta else None
            data['gamma'] = float(snapshot.greeks.gamma) if snapshot.greeks.gamma else None
            data['theta'] = float(snapshot.greeks.theta) if snapshot.greeks.theta else None
            data['vega'] = float(snapshot.greeks.vega) if snapshot.greeks.vega else None

        return data

    def _update_cache(self, symbol: str, price: float, volume: int):
        """Update price/volume cache for indicator calculations."""
        if symbol not in self._price_cache:
            self._price_cache[symbol] = deque(maxlen=self._cache_max_length)
            self._volume_cache[symbol] = deque(maxlen=self._cache_max_length)

        self._price_cache[symbol].append(price)
        self._volume_cache[symbol].append(volume)

    def get_price_history(self, symbol: str, limit: int = 50) -> List[float]:
        """Get cached price history for indicator calculations."""
        if symbol in self._price_cache:
            return list(self._price_cache[symbol])[-limit:]
        return []

    def get_volume_history(self, symbol: str, limit: int = 50) -> List[int]:
        """Get cached volume history."""
        if symbol in self._volume_cache:
            return list(self._volume_cache[symbol])[-limit:]
        return []


# Singleton instance
_enhanced_service_instance: Optional[EnhancedOptionsService] = None


def get_enhanced_options_service(
    enable_realtime: bool = False
) -> EnhancedOptionsService:
    """
    Get singleton instance of enhanced options service.

    Args:
        enable_realtime: Enable real-time streaming

    Returns:
        EnhancedOptionsService instance
    """
    global _enhanced_service_instance

    if _enhanced_service_instance is None:
        _enhanced_service_instance = EnhancedOptionsService(
            enable_realtime=enable_realtime
        )

    return _enhanced_service_instance

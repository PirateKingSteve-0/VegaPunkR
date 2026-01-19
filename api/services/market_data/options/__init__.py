"""
Options Market Data Service

Uses Alpaca SDK:
- OptionHistoricalDataClient for REST calls (bars, snapshots, chain)
- OptionDataStream for WebSocket streaming (real-time quotes/trades)
"""
from .service import OptionsMarketDataService, get_options_market_data_service

__all__ = ['OptionsMarketDataService', 'get_options_market_data_service']

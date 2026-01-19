"""
Market Data Services

Organized by asset type:
- options/  - Options market data (OptionHistoricalDataClient, OptionDataStream)
- stocks/   - Stock market data (StockHistoricalDataClient, StockDataStream)
- crypto/   - Crypto market data (CryptoDataStream)
"""
from .options.service import OptionsMarketDataService, get_options_market_data_service

__all__ = [
    'OptionsMarketDataService',
    'get_options_market_data_service',
]

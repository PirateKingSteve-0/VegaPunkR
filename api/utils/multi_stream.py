"""
Multi-Stream Manager for Alpaca Data
Simultaneously streams data from multiple Alpaca WebSocket endpoints
Uses async/await with the official Alpaca SDK
"""

import asyncio
from typing import Dict, List, Optional, Set, Union, Callable, Any
from datetime import datetime
from alpaca.data.live import StockDataStream, CryptoDataStream, NewsDataStream, OptionDataStream
from alpaca.data.enums import OptionsFeed
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.models.news import News
from .market_hours import get_market_status, is_market_open


class MultiStreamManager:
    """
    Manages multiple simultaneous Alpaca WebSocket connections
    Uses the official async SDK for clean, efficient streaming
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        options_feed: OptionsFeed = OptionsFeed.INDICATIVE
    ):
        """
        Initialize multi-stream manager

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            options_feed: Options feed type (INDICATIVE or OPRA)
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.options_feed = options_feed

        # Stream instances
        self.stock_stream: Optional[StockDataStream] = None
        self.crypto_stream: Optional[CryptoDataStream] = None
        self.news_stream: Optional[NewsDataStream] = None
        self.option_stream: Optional[OptionDataStream] = None

        # Data tracking
        self.data_received: Dict[str, bool] = {
            'stocks': False,
            'crypto': False,
            'news': False,
            'options': False
        }
        self.latest_prices: Dict[str, float] = {}
        self.message_counts: Dict[str, int] = {
            'stocks': 0,
            'crypto': 0,
            'news': 0,
            'options': 0
        }

        # Control
        self.active_streams: Set[str] = set()
        self.stop_event = asyncio.Event()

    async def start_streams(
        self,
        stock_symbols: Optional[List[str]] = None,
        crypto_symbols: Optional[List[str]] = None,
        news_symbols: Optional[List[str]] = None,
        option_symbols: Optional[List[str]] = None,
        auto_stop_on_data: bool = True
    ):
        """
        Start intelligent multi-streaming based on market hours

        Args:
            stock_symbols: Stock symbols to stream (e.g., ["AAPL", "MSFT"])
            crypto_symbols: Crypto symbols to stream (e.g., ["BTC/USD", "ETH/USD"])
            news_symbols: News symbols to stream (e.g., ["*"] for all)
            option_symbols: Option symbols to stream (e.g., ["AAPL251219C00230000"])
            auto_stop_on_data: Stop after receiving data from all available streams
        """
        print("\nSTARTING MULTI-STREAM MANAGER")
        print("="*60)

        # Check market status
        market_status = get_market_status()
        available = market_status['available_streams']

        print(f"Current time: {market_status['current_time_et']}")
        print(f"Status: {market_status['message']}")
        print(f"\nAvailable streams: {', '.join([k for k, v in available.items() if v])}")
        print()

        # Prepare streams
        tasks = []

        # Crypto stream (24/7)
        if crypto_symbols and available['crypto']:
            print(f"Subscribing to CRYPTO: {', '.join(crypto_symbols)}")
            self.active_streams.add('crypto')
            tasks.append(self._run_crypto_stream(crypto_symbols))

        # News stream (24/7)
        if news_symbols and available['news']:
            print(f"Subscribing to NEWS: {', '.join(news_symbols)}")
            self.active_streams.add('news')
            tasks.append(self._run_news_stream(news_symbols))

        # Stock stream (market hours only)
        if stock_symbols and available['stocks']:
            print(f"Subscribing to STOCKS: {', '.join(stock_symbols)}")
            self.active_streams.add('stocks')
            tasks.append(self._run_stock_stream(stock_symbols))
        elif stock_symbols and not available['stocks']:
            print(f"STOCKS unavailable (market closed)")

        # Options stream (market hours only)
        if option_symbols and available['options']:
            print(f"Subscribing to OPTIONS: {', '.join(option_symbols)}")
            self.active_streams.add('options')
            tasks.append(self._run_option_stream(option_symbols))
        elif option_symbols and not available['options']:
            print(f"OPTIONS unavailable (market closed)")

        if not tasks:
            print("No streams to start!")
            return

        print(f"\nStarting {len(tasks)} stream(s)...")
        print("Press Ctrl+C to stop\n")

        # Run all streams concurrently
        try:
            if auto_stop_on_data:
                # Also run monitor task
                tasks.append(self._monitor_streams())

            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            print("\n\nUser interrupted - stopping all streams...")
        except Exception as e:
            print(f"\nError in streams: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.stop_all_streams()
            self.print_summary()

    async def _run_stock_stream(self, symbols: List[str]):
        """Run stock data stream"""
        self.stock_stream = StockDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            raw_data=False
        )

        # Create async handlers
        async def trade_handler(trade):
            await self._handle_trade(trade, 'stocks')

        async def quote_handler(quote):
            await self._handle_quote(quote, 'stocks')

        # Subscribe to trades and quotes
        self.stock_stream.subscribe_trades(trade_handler, *symbols)
        self.stock_stream.subscribe_quotes(quote_handler, *symbols)

        print("STOCK stream connected")
        await self.stock_stream._run_forever()

    async def _run_crypto_stream(self, symbols: List[str]):
        """Run crypto data stream"""
        self.crypto_stream = CryptoDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            raw_data=False
        )

        # Create async handlers
        async def trade_handler(trade):
            await self._handle_trade(trade, 'crypto')

        async def quote_handler(quote):
            await self._handle_quote(quote, 'crypto')

        # Subscribe to trades and quotes
        self.crypto_stream.subscribe_trades(trade_handler, *symbols)
        self.crypto_stream.subscribe_quotes(quote_handler, *symbols)

        print("CRYPTO stream connected")
        await self.crypto_stream._run_forever()

    async def _run_news_stream(self, symbols: List[str]):
        """Run news data stream"""
        self.news_stream = NewsDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            raw_data=False
        )

        # Create async handler
        async def news_handler(news):
            await self._handle_news(news, 'news')

        # Subscribe to news
        self.news_stream.subscribe_news(news_handler, *symbols)

        print("NEWS stream connected")
        await self.news_stream._run_forever()

    async def _run_option_stream(self, symbols: List[str]):
        """Run options data stream"""
        self.option_stream = OptionDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            feed=self.options_feed,
            raw_data=False
        )

        # Create async handlers
        async def trade_handler(trade):
            await self._handle_trade(trade, 'options')

        async def quote_handler(quote):
            await self._handle_quote(quote, 'options')

        # Subscribe to trades and quotes
        self.option_stream.subscribe_trades(trade_handler, *symbols)
        self.option_stream.subscribe_quotes(quote_handler, *symbols)

        print("OPTIONS stream connected")
        await self.option_stream._run_forever()

    async def _handle_trade(self, trade: Union[Trade, Dict], stream_type: str):
        """Handle trade data from any stream"""
        self.data_received[stream_type] = True
        self.message_counts[stream_type] += 1

        timestamp = datetime.now().strftime("%H:%M:%S")

        if isinstance(trade, Trade):
            symbol = trade.symbol
            price = float(trade.price)
            size = float(trade.size)
        else:
            symbol = trade.get('symbol', 'Unknown')
            price = float(trade.get('price', 0))
            size = float(trade.get('size', 0))

        self.latest_prices[symbol] = price
        print(f"[{timestamp}] {stream_type.upper()} TRADE: {symbol} @ ${price:,.2f} (size: {size:.4f})")

    async def _handle_quote(self, quote: Union[Quote, Dict], stream_type: str):
        """Handle quote data from any stream"""
        self.data_received[stream_type] = True
        self.message_counts[stream_type] += 1

        timestamp = datetime.now().strftime("%H:%M:%S")

        if isinstance(quote, Quote):
            symbol = quote.symbol
            bid = float(quote.bid_price)
            ask = float(quote.ask_price)
            bid_size = float(quote.bid_size)
            ask_size = float(quote.ask_size)
        else:
            symbol = quote.get('symbol', 'Unknown')
            bid = float(quote.get('bid_price', 0))
            ask = float(quote.get('ask_price', 0))
            bid_size = float(quote.get('bid_size', 0))
            ask_size = float(quote.get('ask_size', 0))

        mid_price = (bid + ask) / 2 if bid and ask else 0
        if mid_price > 0:
            self.latest_prices[symbol] = mid_price

        spread = ((ask - bid) / mid_price * 100) if mid_price > 0 else 0
        print(f"[{timestamp}] {stream_type.upper()} QUOTE: {symbol} ${bid:,.2f} x {bid_size} / ${ask:,.2f} x {ask_size} (spread: {spread:.3f}%)")

    async def _handle_news(self, news: Union[News, Dict], stream_type: str):
        """Handle news data"""
        self.data_received[stream_type] = True
        self.message_counts[stream_type] += 1

        timestamp = datetime.now().strftime("%H:%M:%S")

        if isinstance(news, News):
            headline = news.headline
            symbols = news.symbols if hasattr(news, 'symbols') else []
        else:
            headline = news.get('headline', 'No headline')
            symbols = news.get('symbols', [])

        symbols_str = ', '.join(symbols[:3]) if symbols else 'General'
        print(f"[{timestamp}] NEWS: {headline[:80]}... [{symbols_str}]")

    async def _monitor_streams(self):
        """Monitor streams and stop when all have received data"""
        while not self.stop_event.is_set():
            await asyncio.sleep(2)

            # Check if all active streams have received data
            all_received = all(
                self.data_received[stream_type]
                for stream_type in self.active_streams
            )

            if all_received:
                print("\nData received from all active streams!")
                self.stop_event.set()
                break

    async def stop_all_streams(self):
        """Stop all active streams"""
        print("\nStopping all streams...")
        self.stop_event.set()

        if self.stock_stream:
            await self.stock_stream.close()
        if self.crypto_stream:
            await self.crypto_stream.close()
        if self.news_stream:
            await self.news_stream.close()
        if self.option_stream:
            await self.option_stream.close()

    def print_summary(self):
        """Print streaming session summary"""
        print("\n" + "="*60)
        print("MULTI-STREAM SUMMARY")
        print("="*60)

        total_messages = sum(self.message_counts.values())
        print(f"Total messages: {total_messages}")
        print(f"Active streams: {len(self.active_streams)}")

        print("\nMessages per stream:")
        for stream_type in self.active_streams:
            count = self.message_counts[stream_type]
            status = "Data received" if self.data_received[stream_type] else "No data"
            print(f"  {stream_type.capitalize()}: {count} messages ({status})")

        if self.latest_prices:
            print("\nLatest prices:")
            for symbol, price in sorted(self.latest_prices.items()):
                print(f"  {symbol}: ${price:,.2f}")

        print("\nSession completed")


async def stream_all_markets(
    api_key: str,
    secret_key: str,
    stock_symbols: Optional[List[str]] = None,
    crypto_symbols: Optional[List[str]] = None,
    news_symbols: Optional[List[str]] = None,
    option_symbols: Optional[List[str]] = None,
    auto_stop: bool = True
):
    """
    Convenience function to stream all markets

    Example:
        await stream_all_markets(
            api_key="...",
            secret_key="...",
            stock_symbols=["AAPL", "MSFT"],
            crypto_symbols=["BTC/USD", "ETH/USD"],
            news_symbols=["*"],
            option_symbols=["AAPL251219C00230000"]
        )
    """
    manager = MultiStreamManager(api_key, secret_key)
    await manager.start_streams(
        stock_symbols=stock_symbols,
        crypto_symbols=crypto_symbols,
        news_symbols=news_symbols,
        option_symbols=option_symbols,
        auto_stop_on_data=auto_stop
    )
    return manager

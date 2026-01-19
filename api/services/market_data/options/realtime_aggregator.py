"""
Real-time Options Data Aggregator

This module provides real-time aggregation of options market data from websocket streams,
including volume tracking, greeks updates, and market data caching.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional

from alpaca.data.live.option import OptionDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.models.snapshots import OptionsSnapshot

log = logging.getLogger(__name__)


@dataclass
class RealtimeOptionData:
    """Real-time aggregated option data."""

    symbol: str
    timestamp: datetime

    # Pricing
    bid: Optional[float] = None
    ask: Optional[float] = None
    last_price: Optional[float] = None

    # Greeks (from snapshots)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None

    # Volume tracking (aggregated from trades)
    volume: int = 0
    trade_count: int = 0

    # Open Interest (fetched separately, updated less frequently)
    open_interest: Optional[int] = None

    # Implied Volatility
    implied_volatility: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "last_price": self.last_price,
            "delta": self.delta,
            "gamma": self.gamma,
            "theta": self.theta,
            "vega": self.vega,
            "rho": self.rho,
            "volume": self.volume,
            "trade_count": self.trade_count,
            "open_interest": self.open_interest,
            "implied_volatility": self.implied_volatility,
        }


class RealtimeOptionsAggregator:
    """
    Aggregates real-time options data from websocket streams.

    Features:
    - Tracks volume from trade messages
    - Updates greeks from snapshot messages
    - Maintains current bid/ask from quotes
    - Provides callbacks for data updates
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        feed: str = "indicative",
        data_callback: Optional[Callable[[RealtimeOptionData], None]] = None,
    ):
        """
        Initialize the realtime options aggregator.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            feed: Options feed type ("indicative" or "opra")
            data_callback: Optional callback function called when data updates
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.feed = feed
        self.data_callback = data_callback

        # Data storage
        self._data: Dict[str, RealtimeOptionData] = {}
        self._lock = asyncio.Lock()

        # WebSocket stream
        self._stream: Optional[OptionDataStream] = None
        self._running = False

    async def start(self):
        """Start the websocket stream."""
        from alpaca.data.enums import OptionsFeed

        feed_enum = OptionsFeed.OPRA if self.feed.lower() == "opra" else OptionsFeed.INDICATIVE

        self._stream = OptionDataStream(
            api_key=self.api_key,
            secret_key=self.secret_key,
            feed=feed_enum,
        )

        self._running = True
        log.info("Starting realtime options aggregator...")

        # Start the stream (this will run in the background)
        asyncio.create_task(self._stream._start_ws())
        asyncio.create_task(self._stream._consume())

    async def stop(self):
        """Stop the websocket stream."""
        self._running = False
        if self._stream:
            await self._stream.stop_ws()
        log.info("Stopped realtime options aggregator")

    async def subscribe(self, *symbols: str):
        """
        Subscribe to real-time data for option symbols.

        Args:
            *symbols: Option contract symbols (e.g., "SPY250117C00590000")
        """
        if not self._stream:
            raise RuntimeError("Stream not started. Call start() first.")

        # Initialize data structures for symbols
        async with self._lock:
            for symbol in symbols:
                if symbol not in self._data:
                    self._data[symbol] = RealtimeOptionData(
                        symbol=symbol,
                        timestamp=datetime.utcnow(),
                    )

        # Subscribe to all data types
        self._stream.subscribe_trades(self._handle_trade, *symbols)
        self._stream.subscribe_quotes(self._handle_quote, *symbols)
        self._stream.subscribe_snapshots(self._handle_snapshot, *symbols)

        log.info(f"Subscribed to {len(symbols)} option symbols")

    async def unsubscribe(self, *symbols: str):
        """Unsubscribe from option symbols."""
        if not self._stream:
            return

        self._stream.unsubscribe_trades(*symbols)
        self._stream.unsubscribe_quotes(*symbols)
        self._stream.unsubscribe_snapshots(*symbols)

        async with self._lock:
            for symbol in symbols:
                self._data.pop(symbol, None)

        log.info(f"Unsubscribed from {len(symbols)} option symbols")

    async def _handle_trade(self, trade: Trade):
        """Handle incoming trade messages."""
        async with self._lock:
            if trade.symbol not in self._data:
                self._data[trade.symbol] = RealtimeOptionData(
                    symbol=trade.symbol,
                    timestamp=trade.timestamp,
                )

            data = self._data[trade.symbol]
            data.last_price = trade.price
            data.volume += int(trade.size)
            data.trade_count += 1
            data.timestamp = trade.timestamp

        if self.data_callback:
            await self._safe_callback(self._data[trade.symbol])

    async def _handle_quote(self, quote: Quote):
        """Handle incoming quote messages."""
        async with self._lock:
            if quote.symbol not in self._data:
                self._data[quote.symbol] = RealtimeOptionData(
                    symbol=quote.symbol,
                    timestamp=quote.timestamp,
                )

            data = self._data[quote.symbol]
            data.bid = quote.bid_price
            data.ask = quote.ask_price
            data.timestamp = quote.timestamp

        if self.data_callback:
            await self._safe_callback(self._data[quote.symbol])

    async def _handle_snapshot(self, snapshot: OptionsSnapshot):
        """Handle incoming snapshot messages (includes greeks)."""
        async with self._lock:
            if snapshot.symbol not in self._data:
                self._data[snapshot.symbol] = RealtimeOptionData(
                    symbol=snapshot.symbol,
                    timestamp=datetime.utcnow(),
                )

            data = self._data[snapshot.symbol]

            # Update greeks
            if snapshot.greeks:
                data.delta = snapshot.greeks.delta
                data.gamma = snapshot.greeks.gamma
                data.theta = snapshot.greeks.theta
                data.vega = snapshot.greeks.vega
                data.rho = snapshot.greeks.rho

            # Update IV
            data.implied_volatility = snapshot.implied_volatility

            # Update pricing from latest quote
            if snapshot.latest_quote:
                data.bid = snapshot.latest_quote.bid_price
                data.ask = snapshot.latest_quote.ask_price

            # Update last price from latest trade
            if snapshot.latest_trade:
                data.last_price = snapshot.latest_trade.price

            data.timestamp = datetime.utcnow()

        if self.data_callback:
            await self._safe_callback(self._data[snapshot.symbol])

    async def _safe_callback(self, data: RealtimeOptionData):
        """Safely execute the callback without blocking."""
        try:
            if asyncio.iscoroutinefunction(self.data_callback):
                await self.data_callback(data)
            else:
                self.data_callback(data)
        except Exception as e:
            log.error(f"Error in data callback: {e}")

    async def get_data(self, symbol: str) -> Optional[RealtimeOptionData]:
        """Get current aggregated data for a symbol."""
        async with self._lock:
            return self._data.get(symbol)

    async def get_all_data(self) -> Dict[str, RealtimeOptionData]:
        """Get all aggregated data."""
        async with self._lock:
            return self._data.copy()

    def set_open_interest(self, symbol: str, open_interest: int):
        """
        Set open interest for a symbol.

        This should be called periodically (e.g., daily) with updated OI data
        from a separate source, as OI is not available in real-time streams.

        Args:
            symbol: Option contract symbol
            open_interest: Open interest value
        """
        if symbol in self._data:
            self._data[symbol].open_interest = open_interest

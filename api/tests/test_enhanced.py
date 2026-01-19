"""
Enhanced test combining market hours detection with option streaming
This demonstrates how to use the new utilities with your existing code
"""

import asyncio
import os
from dotenv import load_dotenv
from alpaca.data.live import OptionDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.enums import OptionsFeed
from typing import Dict, Union
from utils.market_hours import get_market_status, is_market_open

# Load environment variables
load_dotenv()


async def trade_handler(data: Union[Trade, Dict]):
    """Handle trade data"""
    print(f"Received trade: {data.symbol} @ {data.price} (size: {data.size})")


async def quote_handler(data: Union[Quote, Dict]):
    """Handle quote data"""
    print(f"Received quote: {data.symbol} bid {data.bid_price} x {data.bid_size} | ask {data.ask_price} x {data.ask_size}")


async def main():
    print("="*60)
    print("ENHANCED ALPACA OPTIONS STREAMING TEST")
    print("="*60)

    # NEW: Check market status first
    status = get_market_status()
    print(f"\n{status['message']}")
    print(f"Current time: {status['current_time_et']}")

    available = status['available_streams']
    print(f"\nAvailable streams:")
    for stream_type, is_available in available.items():
        print(f"  {stream_type}: {'Yes' if is_available else 'No'}")

    # Warn if markets are closed
    if not is_market_open():
        print("\nWARNING: Markets are currently closed.")
        print("Options stream will connect but may not receive data.")
        print("Consider using crypto or news streams instead.")
        print("\nContinuing anyway for testing purposes...")

    # Get API credentials
    api_key = os.getenv("ALPACA_PAPER_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")

    if not api_key or not secret_key:
        print("\nERROR: API credentials not found in .env file")
        return

    print(f"\nAPI Key: {api_key[:8]}...")
    print("\n" + "="*60)
    print("Starting options data stream...")
    print("="*60)

    # Create stream (same as your original code)
    stream = OptionDataStream(
        api_key=api_key,
        secret_key=secret_key,
        feed=OptionsFeed.INDICATIVE,
        raw_data=False
    )

    print("Stream object created successfully")

    # Subscribe to option contracts
    symbol = "AAPL251219C00230000"  # AAPL Dec 19, 2025 Call at $230
    print(f"\nSubscribing to trades and quotes for {symbol}...")
    stream.subscribe_trades(trade_handler, symbol)
    stream.subscribe_quotes(quote_handler, symbol)

    print("\nConnecting to Alpaca websocket...")
    print("Press Ctrl+C to stop\n")

    # Run stream
    try:
        await stream._run_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
        await stream.close()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        await stream.close()


if __name__ == "__main__":
    asyncio.run(main())

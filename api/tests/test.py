"""
Simple test for Alpaca options data streaming

Note: Options streaming requires a paid Alpaca subscription.

Run with venv activated:
    cd api/tests && python test.py
"""

import asyncio
import os
import sys
from typing import Dict, Union
from dotenv import load_dotenv

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from alpaca.data.live import OptionDataStream
from alpaca.data.models.quotes import Quote
from alpaca.data.models.trades import Trade
from alpaca.data.enums import OptionsFeed

# Load environment variables
load_dotenv()

async def trade_handler(data: Union[Trade, Dict]):
    # Handle trade: e.g., log, analyze with Polars, or insert to TimescaleDB (Day 7)
    print(f"Received trade: {data.symbol} @ {data.price} (size: {data.size})")

async def quote_handler(data: Union[Quote, Dict]):
    # Handle quote: e.g., check for signals in Rust
    print(f"Received quote: {data.symbol} bid {data.bid_price} x {data.bid_size} | ask {data.ask_price} x {data.ask_size}")

async def main():
    print("Starting Alpaca options data stream test...")
    print("⚠️  NOTE: Options streaming requires a paid Alpaca subscription\n")
    print(f"API Key: {os.getenv('ALPACA_PAPER_API_KEY')[:8]}...")

    # Init stream for PAPER/TEST environment
    # For paper trading, use paper=True parameter
    stream = OptionDataStream(
        api_key=os.getenv("ALPACA_PAPER_API_KEY"),
        secret_key=os.getenv("ALPACA_PAPER_SECRET_KEY"),
        feed=OptionsFeed.INDICATIVE,  # Or OptionsFeed.OPRA for real-time (paid)
        raw_data=False  # Use models for structured data
    )

    print("Stream object created successfully")

    # Subscribe to option contracts (using valid future dates)
    # Format: SYMBOL + YY + MM + DD + C/P + Strike (8 digits with padding)
    # Example: AAPL251219C00150000 = AAPL Dec 19 2025 Call at $150

    # Subscribe to a few test symbols - using December 2025 expiration
    symbol = "AAPL251219C00230000"  # AAPL Dec 19, 2025 Call at $230
    print(f"Subscribing to trades and quotes for {symbol}...")
    stream.subscribe_trades(trade_handler, symbol)
    stream.subscribe_quotes(quote_handler, symbol)

    print("Connecting to Alpaca websocket...")
    print("Press Ctrl+C to stop")

    # Run forever (in prod, integrate with FastAPI lifespan or Rust Tokio loop)
    try:
        # Use _run_forever() since we're already in an async context
        await stream._run_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await stream.close()
    except ValueError as e:
        if "auth failed" in str(e):
            print(f"\n⚠️  Authentication failed: Options streaming requires paid subscription")
            print(f"   Error: {e}")
        else:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
        await stream.close()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        await stream.close()

if __name__ == "__main__":
    asyncio.run(main())
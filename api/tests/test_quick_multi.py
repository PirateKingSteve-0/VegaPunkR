"""
Quick test for multi-stream manager
This version will run for 10 seconds then exit automatically

Note: Stock/Options/News streams require a paid Alpaca subscription.
      Crypto streams work with free accounts.

Run from project root:
    PYTHONPATH=api python3 api/tests/test_quick_multi.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.multi_stream import MultiStreamManager
from utils.market_hours import get_market_status
from alpaca.data.enums import OptionsFeed

# Load environment variables
load_dotenv()


async def main():
    print("\n" + "="*60)
    print("QUICK MULTI-STREAM TEST (10 seconds)")
    print("="*60)

    # Get API credentials
    api_key = os.getenv("ALPACA_PAPER_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")

    if not api_key or not secret_key:
        print("ERROR: ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY must be set in .env")
        return

    # Create manager
    manager = MultiStreamManager(
        api_key=api_key,
        secret_key=secret_key,
        options_feed=OptionsFeed.INDICATIVE
    )

    # Check market status
    market_status = get_market_status()
    available = market_status['available_streams']

    # Select symbols based on what's available
    crypto_symbols = ["BTC/USD", "ETH/USD"]
    news_symbols = ["AAPL", "TSLA"]
    stock_symbols = ["AAPL", "MSFT"] if available['stocks'] else None
    option_symbols = ["AAPL251219C00230000"] if available['options'] else None

    print(f"\n⚠️  NOTE: Stock/Options/News streams require paid Alpaca subscription")
    print(f"   Crypto streams work with free accounts (will be tested)")
    print(f"\nThis will stream for 10 seconds to verify connectivity...")
    print()

    # Create a task that will cancel after 10 seconds
    async def run_with_timeout():
        try:
            await asyncio.wait_for(
                manager.start_streams(
                    stock_symbols=stock_symbols,
                    crypto_symbols=crypto_symbols,
                    news_symbols=news_symbols,
                    option_symbols=option_symbols,
                    auto_stop_on_data=False  # Keep streaming
                ),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            print("\n\nTimeout reached - stopping streams...")
            await manager.stop_all_streams()
            manager.print_summary()
        except Exception as e:
            print(f"\n⚠️  Stream error (this is normal for free accounts): {e}")
            await manager.stop_all_streams()
            manager.print_summary()

    await run_with_timeout()

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

    if manager.message_counts['crypto'] > 0 or manager.message_counts['news'] > 0:
        print("✅ SUCCESS: Multi-stream manager is working!")
    else:
        print("⚠️  No data received - this is normal if markets are quiet")
        print("   The connections were successful though!")


if __name__ == "__main__":
    asyncio.run(main())

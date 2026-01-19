"""
Test script for multi-stream manager
Demonstrates simultaneous streaming from multiple Alpaca feeds

Note: Stock/Options/News streams require a paid Alpaca subscription.
      Crypto streams work with free accounts.

Run from project root:
    PYTHONPATH=api python3 api/tests/test_multi_stream.py
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.multi_stream import MultiStreamManager, stream_all_markets
from utils.market_hours import get_market_status
from alpaca.data.enums import OptionsFeed

# Load environment variables
load_dotenv()


async def test_multi_stream_manager():
    """Test using the MultiStreamManager class"""
    print("\n" + "="*60)
    print("MULTI-STREAM MANAGER TEST (Class-based)")
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

    # Define symbols based on market hours
    market_status = get_market_status()
    available = market_status['available_streams']

    stock_symbols = ["AAPL", "MSFT"] if available['stocks'] else None
    crypto_symbols = ["BTC/USD", "ETH/USD"]
    news_symbols = ["*"]
    option_symbols = ["AAPL251219C00230000"] if available['options'] else None

    print("\n⚠️  NOTE: Stock/Options/News streams require paid Alpaca subscription")
    print("   Crypto streams work with free accounts\n")

    # Start streams (will auto-stop after receiving data from all streams)
    try:
        await manager.start_streams(
            stock_symbols=stock_symbols,
            crypto_symbols=crypto_symbols,
            news_symbols=news_symbols,
            option_symbols=option_symbols,
            auto_stop_on_data=True  # Stop after getting data from all streams
        )
    except Exception as e:
        print(f"⚠️  Stream error (normal for free accounts): {e}")


async def test_convenience_function():
    """Test using the convenience function"""
    print("\n" + "="*60)
    print("MULTI-STREAM CONVENIENCE FUNCTION TEST")
    print("="*60)

    # Get API credentials
    api_key = os.getenv("ALPACA_PAPER_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")

    if not api_key or not secret_key:
        print("ERROR: ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY must be set in .env")
        return

    # Check market status
    market_status = get_market_status()
    available = market_status['available_streams']

    print("\n⚠️  NOTE: Stock/Options/News streams require paid Alpaca subscription")
    print("   Crypto streams work with free accounts\n")

    # Start multi-stream with one function call
    try:
        await stream_all_markets(
            api_key=api_key,
            secret_key=secret_key,
            stock_symbols=["AAPL", "GOOGL"] if available['stocks'] else None,
            crypto_symbols=["BTC/USD", "ETH/USD", "DOGE/USD"],
            news_symbols=["AAPL", "MSFT", "GOOGL"],
            option_symbols=["AAPL251219C00230000"] if available['options'] else None,
            auto_stop=True
        )
    except Exception as e:
        print(f"⚠️  Stream error (normal for free accounts): {e}")


async def test_continuous_streaming():
    """Test continuous streaming (doesn't auto-stop)"""
    print("\n" + "="*60)
    print("CONTINUOUS MULTI-STREAM TEST")
    print("="*60)
    print("This will stream continuously until you press Ctrl+C")
    print()

    api_key = os.getenv("ALPACA_PAPER_API_KEY")
    secret_key = os.getenv("ALPACA_PAPER_SECRET_KEY")

    if not api_key or not secret_key:
        print("ERROR: ALPACA_PAPER_API_KEY and ALPACA_PAPER_SECRET_KEY must be set in .env")
        return

    manager = MultiStreamManager(api_key, secret_key)

    # Check what's available
    market_status = get_market_status()
    available = market_status['available_streams']

    print("\n⚠️  NOTE: Stock/Options/News streams require paid Alpaca subscription")
    print("   Crypto streams work with free accounts\n")

    try:
        await manager.start_streams(
            stock_symbols=["AAPL", "MSFT", "GOOGL"] if available['stocks'] else None,
            crypto_symbols=["BTC/USD", "ETH/USD"],
            news_symbols=["*"],
            option_symbols=["AAPL251219C00230000", "MSFT251219C00450000"] if available['options'] else None,
            auto_stop_on_data=False  # Keep streaming until Ctrl+C
        )
    except Exception as e:
        print(f"⚠️  Stream error (normal for free accounts): {e}")


def main():
    """Run the test"""
    print("\n" + "="*80)
    print("ALPACA MULTI-STREAM MANAGER TESTS")
    print("="*80)

    print("\nChoose a test:")
    print("1. Class-based multi-stream (auto-stops after receiving data)")
    print("2. Convenience function (auto-stops after receiving data)")
    print("3. Continuous streaming (runs until Ctrl+C)")
    print()

    choice = input("Enter choice (1-3) or press Enter for option 1: ").strip() or "1"

    if choice == "1":
        asyncio.run(test_multi_stream_manager())
    elif choice == "2":
        asyncio.run(test_convenience_function())
    elif choice == "3":
        asyncio.run(test_continuous_streaming())
    else:
        print("Invalid choice")


if __name__ == "__main__":
    main()

"""
Test script for multi-symbol options streaming

Note: Options streaming requires a paid Alpaca subscription with options data access.

Run from project root:
    PYTHONPATH=api python3 api/tests/test_multiple_symbols.py
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
    """Handle incoming trades for all subscribed symbols"""
    print(f"📊 TRADE: {data.symbol:25} | Price: ${data.price:8.2f} | Size: {data.size:6}")

async def quote_handler(data: Union[Quote, Dict]):
    """Handle incoming quotes for all subscribed symbols"""
    spread = data.ask_price - data.bid_price
    print(f"💰 QUOTE: {data.symbol:25} | Bid: ${data.bid_price:8.2f} x {data.bid_size:4} | Ask: ${data.ask_price:8.2f} x {data.ask_size:4} | Spread: ${spread:.2f}")

async def main():
    print("Starting Alpaca multi-symbol options data stream...")
    print("⚠️  NOTE: Options streaming requires a paid Alpaca subscription\n")
    print(f"API Key: {os.getenv('ALPACA_PAPER_API_KEY')[:8]}...")

    stream = OptionDataStream(
        api_key=os.getenv("ALPACA_PAPER_API_KEY"),
        secret_key=os.getenv("ALPACA_PAPER_SECRET_KEY"),
        feed=OptionsFeed.INDICATIVE,
        raw_data=False
    )

    print("Stream object created successfully\n")

    # ===== MULTIPLE WAYS TO SUBSCRIBE TO MULTIPLE SYMBOLS =====

    # Method 1: Subscribe to multiple symbols in one call (comma-separated)
    print("Method 1: Multiple symbols in one call")
    aapl_options = [
        "AAPL250117C00150000",  # AAPL Jan 17 2025 $150 Call
        "AAPL250117C00155000",  # AAPL Jan 17 2025 $155 Call
        "AAPL250117P00150000",  # AAPL Jan 17 2025 $150 Put
    ]
    stream.subscribe_trades(trade_handler, *aapl_options)
    stream.subscribe_quotes(quote_handler, *aapl_options)
    print(f"  ✓ Subscribed to {len(aapl_options)} AAPL options\n")

    # Method 2: Subscribe to different underlying symbols
    print("Method 2: Different underlying symbols")
    multi_symbol_options = [
        "TSLA250117C00200000",  # TSLA Jan 17 2025 $200 Call
        "SPY250117C00450000",   # SPY Jan 17 2025 $450 Call
        "QQQ250117C00380000",   # QQQ Jan 17 2025 $380 Call
    ]
    stream.subscribe_trades(trade_handler, *multi_symbol_options)
    stream.subscribe_quotes(quote_handler, *multi_symbol_options)
    print(f"  ✓ Subscribed to {len(multi_symbol_options)} options across different symbols\n")

    # Method 3: Subscribe to ALL options (use with caution - high volume!)
    # Uncomment if you want to receive data for ALL option contracts
    # WARNING: This will be VERY high volume during market hours
    # stream.subscribe_quotes(quote_handler, "*")
    # print("  ⚠ Subscribed to ALL options (high volume!)\n")

    # Print summary
    total_subscriptions = len(aapl_options) + len(multi_symbol_options)
    print("="*80)
    print(f"Subscribed to {total_subscriptions} option contracts:")
    print("\nAAPL Options:")
    for symbol in aapl_options:
        print(f"  • {symbol}")
    print("\nMulti-Symbol Options:")
    for symbol in multi_symbol_options:
        print(f"  • {symbol}")
    print("="*80)
    print("\nConnecting to Alpaca websocket...")
    print("Waiting for data (only streams during market hours)...")
    print("Press Ctrl+C to stop\n")

    # Run forever
    try:
        await stream._run_forever()
    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...")
    except ValueError as e:
        if "auth failed" in str(e):
            print(f"\n⚠️  Authentication failed: Options streaming requires paid subscription")
            print(f"   Error: {e}")
        else:
            print(f"\n❌ Error: {e}")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

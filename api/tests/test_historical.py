import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

from alpaca.data.historical import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest

# Load environment variables
load_dotenv()

def main():
    """
    Test historical options data (works anytime, not just market hours).
    Use this to verify your API keys and test data retrieval when markets are closed.
    """
    print("Testing Alpaca historical options data API...")
    print(f"API Key: {os.getenv('ALPACA_PAPER_API_KEY')[:8]}...")

    # Create historical data client
    client = OptionHistoricalDataClient(
        api_key=os.getenv("ALPACA_PAPER_API_KEY"),
        secret_key=os.getenv("ALPACA_PAPER_SECRET_KEY")
    )

    # Example: Get snapshot of AAPL options
    # Format: SYMBOL + YYMMDD + C/P + Strike (8 digits)
    symbols = ["AAPL250117C00150000", "AAPL250117P00150000"]

    print(f"\nFetching snapshot for options: {symbols}")

    try:
        request = OptionSnapshotRequest(symbol_or_symbols=symbols)
        snapshot = client.get_option_snapshot(request)

        print("\n" + "="*60)
        print("HISTORICAL DATA RETRIEVED SUCCESSFULLY")
        print("="*60)

        for symbol, data in snapshot.items():
            print(f"\nSymbol: {symbol}")
            if data.latest_quote:
                print(f"  Latest Quote:")
                print(f"    Bid: ${data.latest_quote.bid_price} x {data.latest_quote.bid_size}")
                print(f"    Ask: ${data.latest_quote.ask_price} x {data.latest_quote.ask_size}")
                print(f"    Time: {data.latest_quote.timestamp}")

            if data.latest_trade:
                print(f"  Latest Trade:")
                print(f"    Price: ${data.latest_trade.price}")
                print(f"    Size: {data.latest_trade.size}")
                print(f"    Time: {data.latest_trade.timestamp}")

        print("\n" + "="*60)
        print("✓ API connection working!")
        print("✓ For live streaming, run during market hours:")
        print("  Monday-Friday 9:30 AM - 4:00 PM ET")
        print("="*60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check your API keys in .env file")
        print("2. Verify options data subscription (may require paid plan)")
        print("3. Try different option symbols")

if __name__ == "__main__":
    main()

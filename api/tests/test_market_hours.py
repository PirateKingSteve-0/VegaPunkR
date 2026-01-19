"""
Test script for market hours detection
Demonstrates the new market hours utility
"""

from utils.market_hours import MarketHours, get_market_status, is_market_open, get_available_streams


def main():
    print("\n" + "="*60)
    print("MARKET HOURS DETECTION TEST")
    print("="*60)

    # Method 1: Use the class directly
    market = MarketHours()
    market.print_market_status()

    # Method 2: Use convenience functions
    print("\n" + "="*60)
    print("CONVENIENCE FUNCTIONS")
    print("="*60)

    print(f"\nIs market open? {is_market_open()}")

    status = get_market_status()
    print(f"Current ET time: {status['current_time_et']}")
    print(f"Trading day: {status['is_trading_day']}")
    print(f"Market message: {status['message']}")

    available = get_available_streams()
    print(f"\nAvailable streams:")
    for stream_type, is_available in available.items():
        print(f"  {stream_type}: {is_available}")

    # Show streaming strategy
    print("\n" + "="*60)
    print("STREAMING STRATEGY")
    print("="*60)
    strategy = market.get_streaming_strategy()
    for asset, approach in strategy.items():
        print(f"  {asset}: {approach}")

    print("\n" + "="*60)
    print("USAGE IN YOUR CODE")
    print("="*60)
    print("""
Example usage in your streaming code:

    from utils.market_hours import is_market_open, get_available_streams

    # Check if you can stream stocks/options
    if is_market_open():
        print("Can stream stocks and options")
    else:
        print("Only crypto and news available")

    # Or check specific streams
    available = get_available_streams()
    if available['stocks']:
        # Start stock stream
        pass
    if available['crypto']:
        # Start crypto stream (always True)
        pass
    """)


if __name__ == "__main__":
    main()

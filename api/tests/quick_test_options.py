"""
Quick validation test for Options Data Integration

This is a fast smoke test to verify basic functionality.
For comprehensive tests, use test_options_integration.py

Usage:
    cd api
    python tests/quick_test_options.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings


def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    try:
        from services.market_data.options.chain_fetcher import OptionChainFetcher
        print("  ✅ chain_fetcher imported")
    except Exception as e:
        print(f"  ❌ chain_fetcher import failed: {e}")
        return False

    try:
        from services.market_data.options.realtime_aggregator import RealtimeOptionsAggregator
        print("  ✅ realtime_aggregator imported")
    except Exception as e:
        print(f"  ❌ realtime_aggregator import failed: {e}")
        return False

    try:
        from alpaca.data.live.option import OptionDataStream
        stream = OptionDataStream(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY
        )
        assert hasattr(stream, 'subscribe_snapshots')
        print("  ✅ OptionDataStream has snapshot methods")
    except Exception as e:
        print(f"  ❌ OptionDataStream check failed: {e}")
        return False

    try:
        from alpaca.data.models.snapshots import OptionsSnapshot
        # Check that OptionsSnapshot has open_interest field
        test_snapshot = OptionsSnapshot("TEST", {
            "openInterest": 1000,
            "impliedVolatility": 0.5
        })
        assert hasattr(test_snapshot, 'open_interest')
        assert test_snapshot.open_interest == 1000
        print("  ✅ OptionsSnapshot has open_interest field")
    except Exception as e:
        print(f"  ❌ OptionsSnapshot check failed: {e}")
        return False

    return True


def test_chain_fetcher():
    """Quick test of chain fetcher."""
    print("\nTesting Option Chain Fetcher...")

    try:
        from services.market_data.options.chain_fetcher import OptionChainFetcher, OptionType

        fetcher = OptionChainFetcher(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY
        )

        print("  Fetching SPY option chain...")
        chain = fetcher.get_chain(underlying="SPY")
        print(f"  ✅ Found {len(chain)} contracts")

        if len(chain) > 0:
            print("  Selecting best contract...")
            contract = fetcher.select_best_contract(
                underlying="SPY",
                delta_min=0.60,
                delta_max=0.85,
                option_type=OptionType.CALL
            )

            if contract:
                print(f"  ✅ Selected: {contract.symbol}")
                print(f"     Strike: ${contract.strike}")
                print(f"     Delta: {contract.delta:.4f}" if contract.delta else "     Delta: N/A")
                print(f"     Score: {contract.score:.2f}")
                return True
            else:
                print("  ⚠️  No suitable contract found (may need to adjust filters)")
                return True  # Not a failure, just no matching contract
        else:
            print("  ⚠️  No option chain data (market may be closed)")
            return True  # Not a failure, just no data

    except Exception as e:
        print(f"  ❌ Chain fetcher test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_models():
    """Test data models."""
    print("\nTesting Data Models...")

    try:
        from services.market_data.options.realtime_aggregator import RealtimeOptionData
        from datetime import datetime

        data = RealtimeOptionData(
            symbol="SPY250117C00590000",
            timestamp=datetime.now(),
            bid=10.0,
            ask=10.5,
            delta=0.75,
            gamma=0.05,
            volume=100
        )

        assert data.symbol == "SPY250117C00590000"
        assert data.volume == 100

        # Test to_dict
        data_dict = data.to_dict()
        assert "symbol" in data_dict
        assert "delta" in data_dict

        print("  ✅ RealtimeOptionData model works")

        from services.market_data.options.chain_fetcher import SelectedContract, StrikeFilter
        from alpaca.data.models.snapshots import OptionsSnapshot
        from datetime import date

        # Test StrikeFilter
        strike_filter = StrikeFilter(
            delta_min=0.5,
            delta_max=0.8,
            min_open_interest=1000
        )
        assert strike_filter.delta_min == 0.5
        print("  ✅ StrikeFilter model works")

        return True

    except Exception as e:
        print(f"  ❌ Model test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 70)
    print("  QUICK VALIDATION TEST - Options Data Integration Phase 1")
    print("=" * 70)
    print(f"\nUsing API Key: {settings.ALPACA_PAPER_API_KEY[:10]}...\n")

    results = []

    # Test 1: Imports
    results.append(("Imports", test_imports()))

    # Test 2: Models
    results.append(("Data Models", test_models()))

    # Test 3: Chain Fetcher (requires API call)
    results.append(("Chain Fetcher", test_chain_fetcher()))

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")

    all_passed = all(p for _, p in results)

    print()
    if all_passed:
        print("🎉 All quick tests passed!")
        print("\nTo run comprehensive tests including websocket:")
        print("  python tests/test_options_integration.py")
    else:
        print("⚠️  Some tests failed. Check the output above.")
        return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
Debug script to see what data is available in the option chain
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from services.market_data.options.chain_fetcher import OptionChainFetcher


def debug_chain_data():
    """Check what data is actually available."""

    print("=" * 80)
    print("  DEBUG: Option Chain Data Analysis")
    print("=" * 80)

    fetcher = OptionChainFetcher(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY
    )

    print("\nFetching SPY option chain...")
    chain = fetcher.get_chain(underlying="SPY")

    print(f"Total contracts: {len(chain)}")

    if not chain:
        print("❌ No option chain data available")
        return

    # Analyze what data we have
    stats = {
        'has_greeks': 0,
        'has_delta': 0,
        'has_oi': 0,
        'has_quote': 0,
        'has_iv': 0,
        'delta_values': [],
        'oi_values': []
    }

    print("\nAnalyzing first 10 contracts:")
    print("-" * 80)

    for i, (symbol, snapshot) in enumerate(list(chain.items())[:10]):
        print(f"\n{i+1}. {symbol}")

        # Check greeks
        if snapshot.greeks:
            stats['has_greeks'] += 1
            print(f"   ✅ Greeks available")
            if snapshot.greeks.delta is not None:
                stats['has_delta'] += 1
                delta_val = abs(float(snapshot.greeks.delta))
                stats['delta_values'].append(delta_val)
                print(f"      Delta: {delta_val:.4f}")
            else:
                print(f"      ⚠️  Delta is None")

            if snapshot.greeks.gamma is not None:
                print(f"      Gamma: {snapshot.greeks.gamma:.4f}")
        else:
            print(f"   ❌ No greeks")

        # Check OI
        if snapshot.open_interest is not None:
            stats['has_oi'] += 1
            stats['oi_values'].append(snapshot.open_interest)
            print(f"   ✅ OI: {snapshot.open_interest}")
        else:
            print(f"   ❌ No OI")

        # Check quote
        if snapshot.latest_quote:
            stats['has_quote'] += 1
            print(f"   ✅ Quote: ${snapshot.latest_quote.bid_price} / ${snapshot.latest_quote.ask_price}")
        else:
            print(f"   ❌ No quote")

        # Check IV
        if snapshot.implied_volatility:
            stats['has_iv'] += 1
            print(f"   ✅ IV: {snapshot.implied_volatility:.2%}")
        else:
            print(f"   ❌ No IV")

    # Overall statistics
    print("\n" + "=" * 80)
    print("OVERALL STATISTICS (from all contracts):")
    print("-" * 80)

    total = len(chain)
    print(f"Total contracts: {total}")
    print(f"Contracts with greeks: {stats['has_greeks']} ({stats['has_greeks']/total*100:.1f}%)")
    print(f"Contracts with delta: {stats['has_delta']} ({stats['has_delta']/total*100:.1f}%)")
    print(f"Contracts with OI: {stats['has_oi']} ({stats['has_oi']/total*100:.1f}%)")
    print(f"Contracts with quotes: {stats['has_quote']} ({stats['has_quote']/total*100:.1f}%)")
    print(f"Contracts with IV: {stats['has_iv']} ({stats['has_iv']/total*100:.1f}%)")

    if stats['delta_values']:
        print(f"\nDelta range: {min(stats['delta_values']):.4f} to {max(stats['delta_values']):.4f}")

    if stats['oi_values']:
        print(f"OI range: {min(stats['oi_values'])} to {max(stats['oi_values'])}")

    # Try relaxed filters
    print("\n" + "=" * 80)
    print("TESTING WITH RELAXED FILTERS:")
    print("-" * 80)

    # Test 1: Very relaxed
    print("\nTest 1: Very relaxed (delta 0.3-0.9, OI 0)")
    contract = fetcher.select_best_contract(
        underlying="SPY",
        delta_min=0.30,
        delta_max=0.90,
        min_open_interest=0,
        max_bid_ask_spread_pct=1.0  # 100%
    )

    if contract:
        print(f"✅ Found: {contract.symbol}")
        print(f"   Delta: {contract.delta:.4f}")
        print(f"   OI: {contract.open_interest}")
        print(f"   Score: {contract.score:.2f}")
    else:
        print("❌ No contract found")

    # Test 2: Original filters
    print("\nTest 2: Original filters (delta 0.6-0.85, OI 1000)")
    contract = fetcher.select_best_contract(
        underlying="SPY",
        delta_min=0.60,
        delta_max=0.85,
        min_open_interest=1000,
        max_bid_ask_spread_pct=0.30
    )

    if contract:
        print(f"✅ Found: {contract.symbol}")
        print(f"   Delta: {contract.delta:.4f}")
        print(f"   OI: {contract.open_interest}")
        print(f"   Score: {contract.score:.2f}")
    else:
        print("❌ No contract found")
        print("   Recommendation: Use relaxed filters or check data availability")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    debug_chain_data()

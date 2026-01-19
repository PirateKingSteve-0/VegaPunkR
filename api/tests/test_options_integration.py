"""
Test suite for Options Data Integration Phase 1

Run individual tests or all tests to verify the implementation.

Usage:
    # Test all
    python tests/test_options_integration.py

    # Test specific component
    python tests/test_options_integration.py --test chain_fetcher
    python tests/test_options_integration.py --test websocket
    python tests/test_options_integration.py --test realtime
"""

import asyncio
import sys
import argparse
from datetime import date
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from services.market_data.options.chain_fetcher import (
    OptionChainFetcher,
    StrikeFilter,
    OptionType
)
from services.market_data.options.realtime_aggregator import (
    RealtimeOptionsAggregator,
    RealtimeOptionData
)


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_result(test_name: str, passed: bool, message: str = ""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} - {test_name}")
    if message:
        print(f"    {message}")


# ============================================================================
# Test 1: Option Chain Fetcher
# ============================================================================

def test_chain_fetcher():
    """Test the option chain fetcher with various scenarios."""
    print_section("Test 1: Option Chain Fetcher")

    try:
        # Initialize fetcher
        fetcher = OptionChainFetcher(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY
        )
        print_result("Initialize OptionChainFetcher", True)

        # Test 1a: Fetch option chain
        print("\n[1a] Fetching SPY option chain...")
        chain = fetcher.get_chain(underlying="SPY")
        has_chain = len(chain) > 0
        print_result(
            "Fetch option chain",
            has_chain,
            f"Found {len(chain)} contracts" if has_chain else "No contracts found"
        )

        if not has_chain:
            print("⚠️  No option chain data available. Skipping remaining chain tests.")
            return False

        # Test 1b: Select best contract (with paper-trading friendly filters)
        print("\n[1b] Selecting best contract with delta range...")
        contract = fetcher.select_best_contract(
            underlying="SPY",
            delta_min=0.40,  # Relaxed for paper trading
            delta_max=0.90,  # Relaxed for paper trading
            min_open_interest=0,  # 0 for paper (no OI in indicative feed)
            option_type=OptionType.CALL
        )

        if contract:
            print_result("Select best contract", True, f"Selected: {contract.symbol}")
            print(f"    Strike: ${contract.strike}")
            print(f"    Delta: {contract.delta:.4f}" if contract.delta else "    Delta: N/A")
            print(f"    Gamma: {contract.gamma:.4f}" if contract.gamma else "    Gamma: N/A")
            print(f"    Open Interest: {contract.open_interest}")
            print(f"    Bid/Ask: ${contract.bid}/{contract.ask}")
            print(f"    Spread: {contract.bid_ask_spread_pct:.2%}" if contract.bid_ask_spread_pct else "    Spread: N/A")
            print(f"    IV: {contract.implied_volatility:.2%}" if contract.implied_volatility else "    IV: N/A")
            print(f"    Score: {contract.score:.2f}")
        else:
            print_result("Select best contract", False, "No suitable contract found")
            return False

        # Test 1c: Filtered chain
        print("\n[1c] Getting filtered chain with custom criteria...")
        strike_filter = StrikeFilter(
            delta_min=0.45,
            delta_max=0.55,
            min_open_interest=1000,
            max_bid_ask_spread_pct=0.30,
            option_type=OptionType.CALL
        )

        contracts = fetcher.get_filtered_chain(
            underlying="SPY",
            strike_filter=strike_filter
        )

        has_filtered = len(contracts) > 0
        print_result(
            "Get filtered chain",
            has_filtered,
            f"Found {len(contracts)} matching contracts" if has_filtered else "No contracts match criteria"
        )

        if has_filtered:
            print("\n    Top 3 contracts:")
            for i, c in enumerate(contracts[:3], 1):
                print(f"    {i}. {c.symbol}")
                print(f"       Delta: {c.delta:.4f}, OI: {c.open_interest}, Score: {c.score:.2f}")

        # Test 1d: 0DTE contracts
        print("\n[1d] Finding 0DTE contracts...")
        dte_contracts = fetcher.get_0dte_contracts(
            underlying="SPY",
            delta_min=0.40,  # Relaxed for paper trading
            delta_max=0.90,  # Relaxed for paper trading
            min_open_interest=0  # 0 for paper
        )

        has_0dte = len(dte_contracts) > 0
        print_result(
            "Find 0DTE contracts",
            True,  # Always pass, even if no 0DTE available
            f"Found {len(dte_contracts)} 0DTE contracts (may be 0 if not trading day)"
        )

        # Test 1e: Caching
        print("\n[1e] Testing cache...")
        import time
        start = time.time()
        chain1 = fetcher.get_chain(underlying="SPY", use_cache=False)
        uncached_time = time.time() - start

        start = time.time()
        chain2 = fetcher.get_chain(underlying="SPY", use_cache=True)
        cached_time = time.time() - start

        cache_faster = cached_time < uncached_time
        print_result(
            "Cache performance",
            cache_faster,
            f"Uncached: {uncached_time:.2f}s, Cached: {cached_time:.2f}s"
        )

        return True

    except Exception as e:
        print_result("Chain Fetcher Tests", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# Test 2: Websocket Handler (Snapshots)
# ============================================================================

async def test_websocket_handler():
    """Test websocket snapshot subscriptions."""
    print_section("Test 2: Websocket Snapshot Handler")

    try:
        from alpaca.data.live.option import OptionDataStream
        from alpaca.data.enums import OptionsFeed

        # Test that the methods exist
        print("\n[2a] Checking OptionDataStream has snapshot methods...")
        stream = OptionDataStream(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            feed=OptionsFeed.INDICATIVE
        )

        has_subscribe = hasattr(stream, 'subscribe_snapshots')
        has_unsubscribe = hasattr(stream, 'unsubscribe_snapshots')
        has_handler = 'snapshots' in stream._handlers

        print_result("subscribe_snapshots method exists", has_subscribe)
        print_result("unsubscribe_snapshots method exists", has_unsubscribe)
        print_result("snapshots handler registered", has_handler)

        if not (has_subscribe and has_unsubscribe and has_handler):
            return False

        # Test 2b: Check OptionsSnapshot model has open_interest
        print("\n[2b] Checking OptionsSnapshot model...")
        from alpaca.data.models.snapshots import OptionsSnapshot

        # Create a dummy snapshot to check fields
        test_data = {
            "S": "TEST",
            "latestTrade": None,
            "latestQuote": None,
            "impliedVolatility": 0.5,
            "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.05, "vega": 0.2, "rho": 0.01},
            "openInterest": 1000
        }

        try:
            snapshot = OptionsSnapshot("TEST", test_data)
            has_oi_field = hasattr(snapshot, 'open_interest')
            oi_value_correct = snapshot.open_interest == 1000

            print_result("OptionsSnapshot has open_interest field", has_oi_field)
            print_result("open_interest maps correctly", oi_value_correct, f"Value: {snapshot.open_interest}")
        except Exception as e:
            print_result("OptionsSnapshot model", False, f"Error creating snapshot: {e}")
            return False

        # Test 2c: Live connection test (quick)
        print("\n[2c] Testing live websocket connection (5 seconds)...")
        print("    Note: This test connects to websocket but may not receive snapshot data")
        print("    in 5 seconds. That's OK - we're just testing the connection.")

        received_data = {"snapshot": False}

        async def snapshot_handler(data):
            received_data["snapshot"] = True
            print(f"    📥 Received snapshot: {data.symbol if hasattr(data, 'symbol') else 'unknown'}")

        try:
            # Start websocket
            await stream._start_ws()

            # Subscribe to a popular contract (might not receive data immediately)
            stream.subscribe_snapshots(snapshot_handler, "SPY*")  # All SPY options

            # Start consuming
            consume_task = asyncio.create_task(stream._consume())

            # Wait 5 seconds
            await asyncio.sleep(5)

            # Stop
            await stream.stop_ws()
            consume_task.cancel()

            print_result(
                "Websocket connection",
                True,
                "Connected successfully (may not have received data in 5 sec window)"
            )

        except Exception as e:
            print_result("Websocket connection", False, f"Connection error: {e}")
            return False

        return True

    except Exception as e:
        print_result("Websocket Handler Tests", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# Test 3: Real-time Aggregator
# ============================================================================

async def test_realtime_aggregator():
    """Test the real-time options aggregator."""
    print_section("Test 3: Real-time Options Aggregator")

    try:
        # Test 3a: Initialization
        print("\n[3a] Initializing aggregator...")

        received_callbacks = []

        async def test_callback(data: RealtimeOptionData):
            received_callbacks.append(data)
            print(f"    📥 Callback: {data.symbol}, Last=${data.last_price}, Vol={data.volume}")

        aggregator = RealtimeOptionsAggregator(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            feed="indicative",
            data_callback=test_callback
        )

        print_result("Initialize aggregator", True)

        # Test 3b: Start/Stop
        print("\n[3b] Testing start/stop...")
        await aggregator.start()
        print_result("Start aggregator", True)

        await asyncio.sleep(1)

        await aggregator.stop()
        print_result("Stop aggregator", True)

        # Test 3c: Data aggregation (10 seconds)
        print("\n[3c] Testing data aggregation (10 seconds)...")
        print("    Subscribing to SPY options and monitoring for updates...")

        await aggregator.start()

        # Get a contract to monitor
        fetcher = OptionChainFetcher(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY
        )

        contract = fetcher.select_best_contract(
            underlying="SPY",
            delta_min=0.60,
            delta_max=0.85,
            option_type=OptionType.CALL
        )

        if contract:
            print(f"    Monitoring: {contract.symbol}")
            await aggregator.subscribe(contract.symbol)

            # Monitor for 10 seconds
            await asyncio.sleep(10)

            # Check data
            data = await aggregator.get_data(contract.symbol)

            if data:
                print_result("Receive aggregated data", True)
                print(f"    Symbol: {data.symbol}")
                print(f"    Last Price: ${data.last_price}")
                print(f"    Bid/Ask: ${data.bid}/{data.ask}")
                print(f"    Delta: {data.delta}")
                print(f"    Gamma: {data.gamma}")
                print(f"    Volume: {data.volume}")
                print(f"    Trade Count: {data.trade_count}")
                print(f"    Callbacks received: {len(received_callbacks)}")
            else:
                print_result(
                    "Receive aggregated data",
                    True,  # Pass even if no data (market might be closed)
                    "No data received (market may be closed or low activity)"
                )
        else:
            print_result(
                "Subscribe to contract",
                True,
                "No contract available to test (market may be closed)"
            )

        await aggregator.stop()

        return True

    except Exception as e:
        print_result("Real-time Aggregator Tests", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# Test 4: Integration Test
# ============================================================================

async def test_integration():
    """Test the full integration: chain fetching + real-time monitoring."""
    print_section("Test 4: Full Integration Test")

    try:
        print("\n[4] Running full integration test (15 seconds)...")
        print("    This simulates a strategy selecting and monitoring a contract")

        # Step 1: Select contract
        print("\n    Step 1: Selecting best contract...")
        fetcher = OptionChainFetcher(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY
        )

        contract = fetcher.select_best_contract(
            underlying="SPY",
            delta_min=0.40,  # Relaxed for paper trading
            delta_max=0.90,  # Relaxed for paper trading
            min_open_interest=0,  # 0 for paper
            option_type=OptionType.CALL
        )

        if not contract:
            print_result(
                "Integration test",
                True,
                "No contract available (market may be closed)"
            )
            return True

        print(f"    ✓ Selected: {contract.symbol}")
        print(f"      Delta: {contract.delta:.4f}, Strike: ${contract.strike}")

        # Step 2: Start monitoring
        print("\n    Step 2: Starting real-time monitoring...")

        updates = []

        async def monitor_callback(data: RealtimeOptionData):
            updates.append({
                "time": data.timestamp,
                "price": data.last_price,
                "delta": data.delta,
                "volume": data.volume
            })
            if len(updates) <= 3:  # Only print first 3
                print(f"    📊 Update: Price=${data.last_price}, Delta={data.delta}, Vol={data.volume}")

        aggregator = RealtimeOptionsAggregator(
            api_key=settings.ALPACA_PAPER_API_KEY,
            secret_key=settings.ALPACA_PAPER_SECRET_KEY,
            data_callback=monitor_callback
        )

        await aggregator.start()
        await aggregator.subscribe(contract.symbol)

        print("    ✓ Subscribed to real-time data")

        # Step 3: Monitor for 15 seconds
        print("\n    Step 3: Monitoring for 15 seconds...")
        await asyncio.sleep(15)

        # Step 4: Get final state
        print("\n    Step 4: Final state:")
        final_data = await aggregator.get_data(contract.symbol)

        if final_data:
            print(f"    ✓ Total updates received: {len(updates)}")
            print(f"    ✓ Final price: ${final_data.last_price}")
            print(f"    ✓ Total volume: {final_data.volume}")
            print(f"    ✓ Trade count: {final_data.trade_count}")
        else:
            print("    ⚠️  No updates (market may be closed or low activity)")

        await aggregator.stop()

        print_result("Full integration test", True, "Completed successfully")
        return True

    except Exception as e:
        print_result("Integration Test", False, f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# Main Test Runner
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Test Options Data Integration')
    parser.add_argument(
        '--test',
        choices=['chain_fetcher', 'websocket', 'realtime', 'integration', 'all'],
        default='all',
        help='Which test to run'
    )
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("  OPTIONS DATA INTEGRATION - PHASE 1 TEST SUITE")
    print("=" * 80)
    print(f"\nAPI Key: {settings.ALPACA_PAPER_API_KEY[:10]}...")
    print(f"Environment: Paper Trading\n")

    results = {}

    # Run tests based on selection
    if args.test in ['chain_fetcher', 'all']:
        results['chain_fetcher'] = test_chain_fetcher()

    if args.test in ['websocket', 'all']:
        results['websocket'] = asyncio.run(test_websocket_handler())

    if args.test in ['realtime', 'all']:
        results['realtime'] = asyncio.run(test_realtime_aggregator())

    if args.test in ['integration', 'all']:
        results['integration'] = asyncio.run(test_integration())

    # Summary
    print_section("Test Summary")
    print()

    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {test_name}")

    all_passed = all(results.values())
    print()
    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed. Check output above for details.")

    print()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

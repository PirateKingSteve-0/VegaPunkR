"""
Example usage of the enhanced options data integration components.

This demonstrates how to use:
1. Real-time options data aggregator (websocket)
2. Enhanced option chain fetcher
3. Strike selection with delta range
"""

import asyncio
import logging
from datetime import date

from config import settings
from services.market_data.options.realtime_aggregator import (
    RealtimeOptionsAggregator,
    RealtimeOptionData
)
from services.market_data.options.chain_fetcher import (
    OptionChainFetcher,
    StrikeFilter,
    OptionType
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Example 1: Real-time Options Data Streaming
# ============================================================================

async def example_realtime_streaming():
    """
    Stream real-time options data including:
    - Delta, gamma, theta, vega from snapshots
    - Volume aggregated from trades
    - Bid/ask from quotes
    """

    async def data_callback(data: RealtimeOptionData):
        """Called whenever data is updated."""
        logger.info(
            f"[{data.symbol}] "
            f"Last: ${data.last_price}, "
            f"Bid/Ask: ${data.bid}/{data.ask}, "
            f"Delta: {data.delta:.3f}, "
            f"Gamma: {data.gamma:.3f}, "
            f"Volume: {data.volume}"
        )

    # Initialize aggregator
    aggregator = RealtimeOptionsAggregator(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY,
        feed="indicative",  # or "opra" for live data
        data_callback=data_callback
    )

    try:
        # Start streaming
        await aggregator.start()

        # Subscribe to specific contracts
        await aggregator.subscribe(
            "SPY250117C00590000",  # SPY Jan 17, 2025 $590 Call
            "SPY250117C00595000",  # SPY Jan 17, 2025 $595 Call
        )

        # Let it run for 60 seconds
        await asyncio.sleep(60)

        # Get current data
        spy_590 = await aggregator.get_data("SPY250117C00590000")
        if spy_590:
            logger.info(f"Final data: {spy_590.to_dict()}")

    finally:
        await aggregator.stop()


# ============================================================================
# Example 2: Option Chain Fetching and Filtering
# ============================================================================

def example_option_chain_fetching():
    """
    Fetch and filter option chains with various criteria.
    """

    # Initialize fetcher
    fetcher = OptionChainFetcher(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY,
        cache_ttl_seconds=300
    )

    # Example 2a: Simple delta-based selection for SPY 0DTE
    logger.info("=== Example 2a: 0DTE Delta Selection ===")
    best_contract = fetcher.select_best_contract(
        underlying="SPY",
        expiration_date=date.today(),
        delta_min=0.60,
        delta_max=0.85,
        min_open_interest=3000,
        max_bid_ask_spread_pct=0.20,
        option_type=OptionType.CALL
    )

    if best_contract:
        logger.info(
            f"Selected: {best_contract.symbol}\n"
            f"  Strike: ${best_contract.strike}\n"
            f"  Delta: {best_contract.delta:.3f}\n"
            f"  Gamma: {best_contract.gamma:.3f}\n"
            f"  OI: {best_contract.open_interest}\n"
            f"  Bid/Ask: ${best_contract.bid}/{best_contract.ask}\n"
            f"  Spread: {best_contract.bid_ask_spread_pct:.2%}\n"
            f"  Score: {best_contract.score:.2f}"
        )

    # Example 2b: Advanced filtering with custom criteria
    logger.info("\n=== Example 2b: Advanced Filtering ===")
    filter_criteria = StrikeFilter(
        delta_min=0.45,
        delta_max=0.55,  # ATM options
        min_open_interest=5000,
        max_bid_ask_spread_pct=0.10,  # 10% max spread
        min_implied_volatility=0.15,
        max_implied_volatility=0.50,
        option_type=OptionType.CALL
    )

    contracts = fetcher.get_filtered_chain(
        underlying="AAPL",
        expiration_date=None,  # All expirations
        strike_filter=filter_criteria
    )

    logger.info(f"Found {len(contracts)} contracts matching criteria:")
    for i, contract in enumerate(contracts[:5], 1):  # Top 5
        logger.info(
            f"{i}. {contract.symbol}: "
            f"Delta={contract.delta:.3f}, "
            f"OI={contract.open_interest}, "
            f"Score={contract.score:.2f}"
        )

    # Example 2c: Get all 0DTE contracts for a strategy
    logger.info("\n=== Example 2c: All 0DTE Contracts ===")
    dte_contracts = fetcher.get_0dte_contracts(
        underlying="SPY",
        delta_min=0.60,
        delta_max=0.85,
        min_open_interest=3000
    )

    logger.info(f"Found {len(dte_contracts)} 0DTE contracts")
    for contract in dte_contracts[:3]:
        logger.info(
            f"  {contract.symbol}: "
            f"Strike=${contract.strike}, "
            f"Delta={contract.delta:.3f}"
        )


# ============================================================================
# Example 3: Combined Usage for Strategy Execution
# ============================================================================

async def example_strategy_integration():
    """
    Demonstrates how to integrate both components for a trading strategy.
    """

    # Step 1: Select best contract using chain fetcher
    logger.info("=== Step 1: Selecting Best Contract ===")
    fetcher = OptionChainFetcher(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY
    )

    contract = fetcher.select_best_contract(
        underlying="SPY",
        expiration_date=date.today(),
        delta_min=0.65,
        delta_max=0.75,
        min_open_interest=5000,
        option_type=OptionType.CALL
    )

    if not contract:
        logger.error("No suitable contract found")
        return

    logger.info(f"Selected contract: {contract.symbol}")

    # Step 2: Start real-time monitoring
    logger.info("\n=== Step 2: Starting Real-time Monitoring ===")

    trade_signals = []

    async def monitor_callback(data: RealtimeOptionData):
        """Monitor for entry/exit signals."""
        if data.delta and data.gamma:
            # Example signal logic
            if data.volume > 100 and data.delta > 0.70:
                logger.info(
                    f"SIGNAL: High activity detected! "
                    f"Volume={data.volume}, Delta={data.delta:.3f}"
                )
                trade_signals.append({
                    "timestamp": data.timestamp,
                    "type": "entry",
                    "price": data.last_price
                })

    aggregator = RealtimeOptionsAggregator(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY,
        data_callback=monitor_callback
    )

    try:
        await aggregator.start()
        await aggregator.subscribe(contract.symbol)

        # Monitor for signals
        logger.info("Monitoring for 30 seconds...")
        await asyncio.sleep(30)

        logger.info(f"\n=== Signals Generated: {len(trade_signals)} ===")
        for signal in trade_signals:
            logger.info(signal)

    finally:
        await aggregator.stop()


# ============================================================================
# Example 4: Update Open Interest Periodically
# ============================================================================

async def example_open_interest_updates():
    """
    Demonstrates periodic open interest updates (since OI is not real-time).
    """

    aggregator = RealtimeOptionsAggregator(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY
    )

    fetcher = OptionChainFetcher(
        api_key=settings.ALPACA_PAPER_API_KEY,
        secret_key=settings.ALPACA_PAPER_SECRET_KEY
    )

    try:
        await aggregator.start()

        # Subscribe to contracts
        symbols = [
            "SPY250117C00590000",
            "SPY250117C00595000"
        ]
        await aggregator.subscribe(*symbols)

        # Update OI every 5 minutes (OI is updated daily, but this shows the pattern)
        while True:
            logger.info("Updating open interest data...")

            for symbol in symbols:
                # Fetch latest snapshot to get OI
                chain = fetcher.get_chain(underlying="SPY", use_cache=False)
                if symbol in chain:
                    snapshot = chain[symbol]
                    if snapshot.open_interest:
                        aggregator.set_open_interest(symbol, snapshot.open_interest)
                        logger.info(f"{symbol}: OI = {snapshot.open_interest}")

            await asyncio.sleep(300)  # 5 minutes

    finally:
        await aggregator.stop()


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    # Run examples
    print("=" * 80)
    print("Options Data Integration Examples")
    print("=" * 80)

    # Example 1: Real-time streaming (async)
    # asyncio.run(example_realtime_streaming())

    # Example 2: Option chain fetching (sync)
    example_option_chain_fetching()

    # Example 3: Combined usage (async)
    # asyncio.run(example_strategy_integration())

    # Example 4: OI updates (async)
    # asyncio.run(example_open_interest_updates())

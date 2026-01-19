"""
Background Worker for Strategy Execution

This service runs continuously and:
1. Monitors active strategies
2. Fetches real-time market data
3. Executes strategy logic via StrategyExecutor
4. Handles errors and logging

Uses APScheduler for lightweight background job scheduling.
For production with multiple workers, consider upgrading to Celery + Redis.
"""
import logging
import asyncio
from datetime import datetime
from typing import List, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal
from models import User, Strategy
from engine.strategy_executor import StrategyExecutor
from engine.trading_client_manager import TradingClientManager

logger = logging.getLogger(__name__)


class StrategyWorker:
    """
    Background worker that continuously monitors and executes active strategies.

    Features:
    - Concurrent strategy execution with asyncio.gather
    - Semaphore to limit concurrent strategies (protects DB + API rate limits)
    - Separate DB sessions per strategy (prevents race conditions)
    - Row-level locking on position updates (prevents data corruption)
    """

    # Max concurrent strategies (protects DB connections + Alpaca API rate limits)
    MAX_CONCURRENT_STRATEGIES = 10

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.trading_client = TradingClientManager()
        self.is_running = False
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_STRATEGIES)

    def start(self):
        """Start the background worker"""
        if self.is_running:
            logger.warning("Worker is already running")
            return

        logger.info("Starting Strategy Worker...")

        # Schedule strategy execution every 1 minute
        self.scheduler.add_job(
            self.execute_all_strategies,
            trigger=IntervalTrigger(seconds=60),  # Run every minute
            id='execute_strategies',
            name='Execute Active Strategies',
            replace_existing=True
        )

        # Schedule position monitoring every 30 seconds (more frequent for 0DTE)
        self.scheduler.add_job(
            self.monitor_positions,
            trigger=IntervalTrigger(seconds=30),
            id='monitor_positions',
            name='Monitor Open Positions',
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True

        logger.info("✅ Strategy Worker started successfully")
        logger.info("  - Strategy execution: every 60 seconds")
        logger.info("  - Position monitoring: every 30 seconds")

    def stop(self):
        """Stop the background worker"""
        if not self.is_running:
            logger.warning("Worker is not running")
            return

        logger.info("Stopping Strategy Worker...")
        self.scheduler.shutdown(wait=True)
        self.is_running = False
        logger.info("✅ Strategy Worker stopped")

    async def execute_all_strategies(self):
        """
        Main job: Execute all active strategies CONCURRENTLY.

        This is called every minute by the scheduler.

        Features:
        - Runs strategies in parallel using asyncio.gather
        - Limited by semaphore (MAX_CONCURRENT_STRATEGIES)
        - Each strategy gets its own DB session
        - Failures in one strategy don't affect others
        """
        logger.debug("Executing all active strategies...")

        # Use a temporary session just to fetch the list of active strategies
        db = SessionLocal()
        try:
            # Get all active strategies (just IDs and basic info)
            active_strategies = db.query(Strategy).filter(
                Strategy.is_active == True
            ).all()

            if not active_strategies:
                logger.debug("No active strategies to execute")
                return

            logger.info(f"Found {len(active_strategies)} active strategies - executing concurrently")

            # Execute all strategies concurrently with separate sessions
            # return_exceptions=True prevents one failure from canceling others
            results = await asyncio.gather(*[
                self._execute_single_strategy(strategy.id)
                for strategy in active_strategies
            ], return_exceptions=True)

            # Log any exceptions
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Strategy {active_strategies[i].id} failed: {str(result)}"
                    )

        except Exception as e:
            logger.error(f"Error in execute_all_strategies: {str(e)}", exc_info=True)
        finally:
            db.close()

    async def _execute_single_strategy(self, strategy_id: int):
        """
        Execute a single strategy with its own DB session.

        Uses semaphore to limit concurrent executions and row-level
        locking to prevent race conditions on shared data.
        """
        async with self._semaphore:  # Limit concurrent strategies
            # Each strategy gets its own DB session
            db = SessionLocal()
            try:
                # Create executor with this session
                executor = StrategyExecutor(db)

                # Re-fetch strategy in this session
                strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
                if not strategy:
                    logger.warning(f"Strategy {strategy_id} not found")
                    return

                # Get user for this strategy
                user = db.query(User).filter(User.id == strategy.user_id).first()

                if not user:
                    logger.error(f"User not found for strategy {strategy.id}")
                    return

                # Get market data for strategy instruments
                instruments = strategy.instruments or []

                for symbol in instruments:
                    # Fetch real-time market data
                    market_data = await self._fetch_market_data(user, symbol, strategy)

                    if not market_data:
                        logger.warning(f"Could not fetch market data for {symbol}")
                        continue

                    # Execute strategy tick
                    result = await executor.execute_strategy_tick(
                        user=user,
                        strategy=strategy,
                        market_data=market_data
                    )

                    # Log results
                    if result.get('signals_generated'):
                        logger.info(
                            f"Strategy {strategy.id} ({strategy.name}) - "
                            f"Signals: {len(result['signals_generated'])}"
                        )

                    if result.get('orders_placed'):
                        logger.info(
                            f"Strategy {strategy.id} ({strategy.name}) - "
                            f"Orders placed: {len(result['orders_placed'])}"
                        )

                    if result.get('positions_closed'):
                        logger.info(
                            f"Strategy {strategy.id} ({strategy.name}) - "
                            f"Positions closed: {len(result['positions_closed'])}"
                        )

                    if result.get('errors'):
                        logger.error(
                            f"Strategy {strategy.id} ({strategy.name}) - "
                            f"Errors: {result['errors']}"
                        )

            except Exception as e:
                logger.error(
                    f"Error executing strategy {strategy_id}: {str(e)}",
                    exc_info=True
                )
            finally:
                db.close()

    async def _fetch_market_data(self, user: User, symbol: str, strategy: Strategy) -> Dict:
        """
        Fetch real-time market data for a symbol.

        Routes to appropriate market data service based on strategy asset_type:
        - options: OptionsMarketDataService (selects contract, gets greeks)
        - stocks: TODO - StocksMarketDataService
        - crypto: TODO - CryptoMarketDataService

        Args:
            user: User object
            symbol: Underlying symbol from strategy.instruments (e.g., "SPY")
            strategy: Strategy object with params_json

        Returns:
            Dict with market data for SignalGenerator
        """
        try:
            params = strategy.params_json
            asset_type = params.get('asset_type', 'options')

            if asset_type == 'options':
                # Use EnhancedOptionsService with improved contract selection
                from services.market_data.options.enhanced_service import get_enhanced_options_service

                options_service = get_enhanced_options_service(enable_realtime=False)
                market_data = await options_service.get_market_data(strategy, symbol)

                if market_data:
                    logger.debug(
                        f"Options data for {symbol}: contract={market_data.get('symbol')}, "
                        f"price=${market_data.get('price', 0):.2f}, delta={market_data.get('delta', 0):.3f}, "
                        f"source={market_data.get('data_source')}"  # Shows 'realtime' or 'rest'
                    )
                return market_data

            elif asset_type == 'stocks':
                # TODO: Implement StocksMarketDataService
                logger.warning(f"Stock market data not yet implemented for {symbol}")
                return None

            elif asset_type == 'crypto':
                # TODO: Implement CryptoMarketDataService
                logger.warning(f"Crypto market data not yet implemented for {symbol}")
                return None

            else:
                logger.error(f"Unknown asset_type: {asset_type}")
                return None

        except Exception as e:
            logger.error(f"Error fetching market data for {symbol}: {str(e)}", exc_info=True)
            return None

    async def monitor_positions(self):
        """
        Monitor open positions for exit conditions

        This runs more frequently (every 30s) than strategy execution
        to catch stop losses and take profits quickly
        """
        logger.debug("Monitoring open positions...")

        db = SessionLocal()
        try:
            from api.models import Position

            # Get all open positions
            open_positions = db.query(Position).filter(
                Position.qty > 0
            ).all()

            if not open_positions:
                return

            logger.debug(f"Monitoring {len(open_positions)} open positions")

            # For each position, check current price and update
            for position in open_positions:
                user = db.query(User).filter(User.id == position.user_id).first()
                strategy = db.query(Strategy).filter(
                    Strategy.id == position.strategy_id
                ).first()

                if not user or not strategy:
                    continue

                # Fetch current price
                market_data = await self._fetch_market_data(
                    user, position.symbol, strategy
                )

                if not market_data:
                    continue

                current_price = market_data['price']

                # Update position price and unrealized P&L
                position.current_price = current_price
                position.unrealized_pnl = (
                    (current_price - position.avg_entry_price) * position.qty
                )

                db.commit()

        except Exception as e:
            logger.error(f"Error monitoring positions: {str(e)}", exc_info=True)
        finally:
            db.close()


# Global worker instance
_worker_instance = None


def get_worker() -> StrategyWorker:
    """Get or create the global worker instance"""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = StrategyWorker()
    return _worker_instance


def start_worker():
    """Start the background worker (called at app startup)"""
    worker = get_worker()
    worker.start()


def stop_worker():
    """Stop the background worker (called at app shutdown)"""
    worker = get_worker()
    worker.stop()


# Optional: CLI script to run worker standalone
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("Starting Strategy Worker (standalone mode)...")

    worker = StrategyWorker()
    worker.start()

    try:
        # Keep running until interrupted
        logger.info("Worker is running. Press Ctrl+C to stop.")
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        worker.stop()
        sys.exit(0)

# Trendline Strategy Architecture & Implementation Gameplan

## Overview

This document outlines the architectural plan for enhancing VegaPunkR's strategy engine with:
1. **WebSocket-driven event processing** (replacing polling-based execution)
2. **Trendline analysis integration** (support/resistance, channels, breakouts)
3. **Flexible strategy configuration** for different technical analysis approaches

---

## Current Strategy Architecture (Polling-Based)

### Execution Flow

```
Background Worker (APScheduler)
    ↓ Every 60 seconds
Strategy Executor
    ↓ Receives market_data dict
Signal Generator
    ↓ Checks technical indicators
    ├─ EMA (9-period)
    ├─ VWAP
    ├─ Volume spikes
    ├─ Delta (for options)
    └─ Bid-ask spread
    ↓ Returns Signal or None
Risk Manager validates
    ↓
Order Manager executes
```

### Current Implementation

**File:** `api/engine/strategy_executor.py`

**Key Components:**
- `execute_strategy_tick()` - Main execution method called every 60s
- Market data passed as dict with: `symbol`, `price`, `volume`, `bid`, `ask`, `delta`, `open_interest`
- Signal generator maintains price history in memory (deque of last 100 bars)
- Indicators calculated on-demand from price history

**Limitations:**
- ❌ Polling-based (might miss rapid moves)
- ❌ Only uses moving averages (EMA/VWAP)
- ❌ No support/resistance detection
- ❌ No breakout detection
- ❌ No channel analysis
- ❌ WebSocket integration not active

---

## Proposed Architecture (Event-Driven)

### Enhanced Execution Flow

```
WebSocket Data Stream (Alpaca)
    ↓ Real-time: trades, quotes, bars
Market Data Aggregator
    ↓ Maintains candle state
    ↓ Updates trendlines
    ↓ Triggers strategy on new bar/tick
Strategy Engine
    ↓ Receives enriched market data
Trendline Analyzer
    ↓ Provides trendline signals
    ├─ Support/Resistance lines
    ├─ Channel detection
    ├─ Breakout detection
    ├─ Pivot points
    └─ Trend strength
Signal Generator (Enhanced)
    ↓ Combines indicators + trendlines
Risk Manager → Order Manager
```

### Key Improvements

| Aspect | Current | Proposed |
|--------|---------|----------|
| **Execution Model** | Polling (60s intervals) | Event-driven (instant reaction) |
| **Market Data** | Mocked/polled dict | Real-time WebSocket streams |
| **Trendlines** | None | Support/resistance, channels, breakouts |
| **Customization** | Limited indicator options | Flexible trendline configurations |
| **Performance** | May miss moves between polls | React instantly to market events |

---

## Component Design

### 1. TrendlineAnalyzer Component

**File:** `api/analysis/trendline_analyzer.py` (NEW)

```python
class TrendlineAnalyzer:
    """
    Provides trendline analysis tools for strategies

    Features:
    - Support/Resistance detection
    - Channel detection (ascending/descending)
    - Breakout detection with volume confirmation
    - Pivot point calculations
    - Trend strength measurement
    """

    def __init__(self):
        self.support_resistance_detector = SupportResistanceDetector()
        self.channel_detector = ChannelDetector()
        self.breakout_detector = BreakoutDetector()
        self.pivot_calculator = PivotPointCalculator()

    def analyze(
        self,
        symbol: str,
        bars: List[Bar],
        config: Dict
    ) -> TrendlineSignals:
        """
        Analyze price action and return trendline signals

        Args:
            symbol: Trading symbol
            bars: Historical price bars
            config: Configuration dict with:
                {
                    'detect_support_resistance': True,
                    'detect_channels': True,
                    'detect_breakouts': True,
                    'lookback_periods': 50,
                    'sensitivity': 'medium',  # 'low', 'medium', 'high'
                    'min_touches': 3,
                    'tolerance': 0.02  # 2% price tolerance for clustering
                }

        Returns:
            TrendlineSignals object containing:
                - support_levels: List[float]
                - resistance_levels: List[float]
                - channels: Optional[Channel]
                - breakouts: Optional[Breakout]
                - pivot_points: Dict[str, float]
                - trend_strength: float (0.0-1.0)
        """
        signals = TrendlineSignals()

        if config.get('detect_support_resistance'):
            signals.support_levels = self.support_resistance_detector.find_support(
                bars,
                min_touches=config.get('min_touches', 3)
            )
            signals.resistance_levels = self.support_resistance_detector.find_resistance(
                bars,
                min_touches=config.get('min_touches', 3)
            )

        if config.get('detect_channels'):
            signals.channels = self.channel_detector.detect(bars)

        if config.get('detect_breakouts'):
            signals.breakouts = self.breakout_detector.check(
                bars,
                signals.support_levels,
                signals.resistance_levels
            )

        signals.pivot_points = self.pivot_calculator.calculate(bars)
        signals.trend_strength = self._calculate_trend_strength(bars)

        return signals

    def _calculate_trend_strength(self, bars: List[Bar]) -> float:
        """
        Calculate trend strength based on higher highs/lower lows
        Returns: -1.0 (strong downtrend) to +1.0 (strong uptrend)
        """
        if len(bars) < 20:
            return 0.0

        highs = [bar.high for bar in bars[-20:]]
        lows = [bar.low for bar in bars[-20:]]

        # Count higher highs and higher lows
        higher_highs = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        lower_lows = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i-1])

        # Normalize to -1.0 to +1.0
        strength = (higher_highs - lower_lows) / len(highs)
        return max(-1.0, min(1.0, strength))
```

### 2. Support/Resistance Detector

**File:** `api/analysis/support_resistance.py` (NEW)

```python
class SupportResistanceDetector:
    """
    Detects support and resistance levels using pivot points
    and price clustering algorithms
    """

    def find_support(
        self,
        bars: List[Bar],
        min_touches: int = 3,
        tolerance: float = 0.02
    ) -> List[float]:
        """
        Find support levels using pivot lows

        Algorithm:
        1. Find local lows (pivot points where low is lowest in window)
        2. Cluster nearby lows within tolerance (e.g., 2%)
        3. Confirm with minimum number of touches

        Args:
            bars: Historical price bars
            min_touches: Minimum times price must touch level to confirm
            tolerance: Price tolerance for clustering (0.02 = 2%)

        Returns:
            List of support price levels, sorted ascending
        """
        pivot_lows = self._find_pivot_lows(bars, window=5)
        clustered_levels = self._cluster_levels(pivot_lows, tolerance)

        # Filter by minimum touches
        support_levels = [
            level for level, touches in clustered_levels.items()
            if touches >= min_touches
        ]

        return sorted(support_levels)

    def find_resistance(
        self,
        bars: List[Bar],
        min_touches: int = 3,
        tolerance: float = 0.02
    ) -> List[float]:
        """
        Find resistance levels using pivot highs

        Same algorithm as support but using pivot highs
        """
        pivot_highs = self._find_pivot_highs(bars, window=5)
        clustered_levels = self._cluster_levels(pivot_highs, tolerance)

        resistance_levels = [
            level for level, touches in clustered_levels.items()
            if touches >= min_touches
        ]

        return sorted(resistance_levels, reverse=True)

    def _find_pivot_lows(self, bars: List[Bar], window: int = 5) -> List[float]:
        """
        Find local lows where price is lowest in surrounding window

        Example: If window=5, checks 2 bars before and 2 bars after
        """
        pivot_lows = []

        for i in range(window, len(bars) - window):
            current_low = bars[i].low

            # Check if this is lowest in window
            is_pivot = True
            for j in range(i - window, i + window + 1):
                if j != i and bars[j].low < current_low:
                    is_pivot = False
                    break

            if is_pivot:
                pivot_lows.append(current_low)

        return pivot_lows

    def _find_pivot_highs(self, bars: List[Bar], window: int = 5) -> List[float]:
        """
        Find local highs where price is highest in surrounding window
        """
        pivot_highs = []

        for i in range(window, len(bars) - window):
            current_high = bars[i].high

            # Check if this is highest in window
            is_pivot = True
            for j in range(i - window, i + window + 1):
                if j != i and bars[j].high > current_high:
                    is_pivot = False
                    break

            if is_pivot:
                pivot_highs.append(current_high)

        return pivot_highs

    def _cluster_levels(
        self,
        levels: List[float],
        tolerance: float
    ) -> Dict[float, int]:
        """
        Cluster nearby price levels and count touches

        Args:
            levels: List of price levels (pivot highs or lows)
            tolerance: Clustering tolerance (e.g., 0.02 = 2%)

        Returns:
            Dict mapping clustered level to number of touches
            Example: {450.25: 3, 455.80: 5} means price touched
                     450.25 three times and 455.80 five times
        """
        if not levels:
            return {}

        clustered = {}

        for level in levels:
            # Find if this level belongs to existing cluster
            found_cluster = False

            for cluster_level in list(clustered.keys()):
                if abs(level - cluster_level) / cluster_level <= tolerance:
                    # Add to existing cluster (update average)
                    total = cluster_level * clustered[cluster_level] + level
                    clustered[cluster_level] += 1
                    new_avg = total / clustered[cluster_level]

                    # Update cluster level to new average
                    clustered[new_avg] = clustered.pop(cluster_level)
                    found_cluster = True
                    break

            if not found_cluster:
                # Create new cluster
                clustered[level] = 1

        return clustered
```

### 3. Channel Detector

**File:** `api/analysis/channel_detector.py` (NEW)

```python
import numpy as np
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class Channel:
    """Represents a price channel"""
    upper_slope: float
    upper_intercept: float
    lower_slope: float
    lower_intercept: float
    direction: str  # 'ascending', 'descending', 'sideways'
    strength: float  # 0.0-1.0, how well price respects channel

    def get_upper_bound_at(self, x: int) -> float:
        """Get upper channel boundary at bar index x"""
        return self.upper_slope * x + self.upper_intercept

    def get_lower_bound_at(self, x: int) -> float:
        """Get lower channel boundary at bar index x"""
        return self.lower_slope * x + self.lower_intercept

    def is_price_at_lower_bound(self, price: float, x: int, tolerance: float = 0.005) -> bool:
        """Check if price is near lower channel bound (within tolerance)"""
        lower_bound = self.get_lower_bound_at(x)
        distance = abs(price - lower_bound) / lower_bound
        return distance <= tolerance

    def is_price_at_upper_bound(self, price: float, x: int, tolerance: float = 0.005) -> bool:
        """Check if price is near upper channel bound (within tolerance)"""
        upper_bound = self.get_upper_bound_at(x)
        distance = abs(price - upper_bound) / upper_bound
        return distance <= tolerance


class ChannelDetector:
    """
    Detects ascending/descending price channels using linear regression
    """

    def detect(self, bars: List[Bar], min_bars: int = 20) -> Optional[Channel]:
        """
        Detect price channel using linear regression on highs and lows

        Algorithm:
        1. Fit trendline to highs (resistance line)
        2. Fit trendline to lows (support line)
        3. Check if slopes are parallel (within tolerance)
        4. Calculate how well price respects channel boundaries

        Args:
            bars: Historical price bars
            min_bars: Minimum bars required for detection

        Returns:
            Channel object if detected, None otherwise
        """
        if len(bars) < min_bars:
            return None

        x = np.arange(len(bars))
        highs = np.array([bar.high for bar in bars])
        lows = np.array([bar.low for bar in bars])

        # Fit upper trendline (resistance) using linear regression
        upper_slope, upper_intercept = self._fit_line(x, highs)

        # Fit lower trendline (support) using linear regression
        lower_slope, lower_intercept = self._fit_line(x, lows)

        # Check if slopes are parallel (within 10% difference)
        slope_diff = abs(upper_slope - lower_slope)
        avg_slope = (abs(upper_slope) + abs(lower_slope)) / 2

        if avg_slope > 0 and slope_diff / avg_slope > 0.10:
            return None  # Not parallel enough

        # Determine channel direction
        avg_slope = (upper_slope + lower_slope) / 2
        if avg_slope > 0.001:
            direction = 'ascending'
        elif avg_slope < -0.001:
            direction = 'descending'
        else:
            direction = 'sideways'

        # Calculate channel strength (how well price respects boundaries)
        strength = self._calculate_channel_strength(
            bars, x, upper_slope, upper_intercept, lower_slope, lower_intercept
        )

        return Channel(
            upper_slope=upper_slope,
            upper_intercept=upper_intercept,
            lower_slope=lower_slope,
            lower_intercept=lower_intercept,
            direction=direction,
            strength=strength
        )

    def _fit_line(self, x: np.ndarray, y: np.ndarray) -> tuple:
        """
        Fit linear regression line to data

        Returns:
            (slope, intercept)
        """
        # Use numpy polyfit (degree 1 = linear)
        coeffs = np.polyfit(x, y, 1)
        slope = coeffs[0]
        intercept = coeffs[1]
        return slope, intercept

    def _calculate_channel_strength(
        self,
        bars: List[Bar],
        x: np.ndarray,
        upper_slope: float,
        upper_intercept: float,
        lower_slope: float,
        lower_intercept: float
    ) -> float:
        """
        Calculate how well price respects channel boundaries

        Returns:
            Strength from 0.0 (weak) to 1.0 (strong)
        """
        violations = 0
        total_bars = len(bars)

        for i, bar in enumerate(bars):
            upper_bound = upper_slope * x[i] + upper_intercept
            lower_bound = lower_slope * x[i] + lower_intercept

            # Check if price breached channel
            if bar.high > upper_bound * 1.01:  # 1% tolerance
                violations += 1
            elif bar.low < lower_bound * 0.99:  # 1% tolerance
                violations += 1

        # Calculate strength (inverse of violation rate)
        violation_rate = violations / total_bars
        strength = max(0.0, 1.0 - violation_rate)

        return strength
```

### 4. Breakout Detector

**File:** `api/analysis/breakout_detector.py` (NEW)

```python
from typing import Optional, List
from dataclasses import dataclass

@dataclass
class Breakout:
    """Represents a price breakout"""
    type: str  # 'resistance_breakout' or 'support_breakdown'
    level: float  # The level that was broken
    breakout_price: float  # Price at breakout
    volume_confirmation: bool  # True if volume confirmed breakout
    volume_ratio: float  # Current volume / average volume
    timestamp: datetime


class BreakoutDetector:
    """
    Detects price breakouts above resistance or below support
    with volume confirmation
    """

    def check(
        self,
        bars: List[Bar],
        support_levels: List[float],
        resistance_levels: List[float],
        volume_multiplier: float = 1.5,
        lookback_periods: int = 20
    ) -> Optional[Breakout]:
        """
        Detect price breakouts with volume confirmation

        Args:
            bars: Historical price bars
            support_levels: List of support levels
            resistance_levels: List of resistance levels
            volume_multiplier: Minimum volume increase to confirm breakout
            lookback_periods: Periods for average volume calculation

        Returns:
            Breakout object if detected, None otherwise
        """
        if len(bars) < lookback_periods + 1:
            return None

        latest_bar = bars[-1]

        # Calculate average volume
        avg_volume = sum(bar.volume for bar in bars[-lookback_periods:]) / lookback_periods
        volume_ratio = latest_bar.volume / avg_volume if avg_volume > 0 else 0
        volume_confirmed = volume_ratio >= volume_multiplier

        # Check resistance breakouts (bullish)
        for resistance in sorted(resistance_levels):
            # Check if price broke above resistance
            if (latest_bar.close > resistance and
                latest_bar.high > resistance):

                # Verify this is a NEW breakout (wasn't above resistance in previous bars)
                previous_bars = bars[-5:-1]  # Check last 4 bars
                was_below = all(bar.close <= resistance for bar in previous_bars)

                if was_below:
                    return Breakout(
                        type='resistance_breakout',
                        level=resistance,
                        breakout_price=latest_bar.close,
                        volume_confirmation=volume_confirmed,
                        volume_ratio=volume_ratio,
                        timestamp=latest_bar.timestamp
                    )

        # Check support breakdowns (bearish)
        for support in sorted(support_levels, reverse=True):
            # Check if price broke below support
            if (latest_bar.close < support and
                latest_bar.low < support):

                # Verify this is a NEW breakdown
                previous_bars = bars[-5:-1]
                was_above = all(bar.close >= support for bar in previous_bars)

                if was_above:
                    return Breakout(
                        type='support_breakdown',
                        level=support,
                        breakout_price=latest_bar.close,
                        volume_confirmation=volume_confirmed,
                        volume_ratio=volume_ratio,
                        timestamp=latest_bar.timestamp
                    )

        return None
```

### 5. Enhanced Strategy Configuration

**Update:** `api/models.py` - Strategy.params_json structure

```python
# Example Strategy.params_json with trendline configuration
{
    # ========== EXISTING PARAMETERS ==========

    # Entry Conditions (Traditional Indicators)
    "ema_period": 9,
    "use_vwap": True,
    "use_tick_indicator": False,
    "volume_spike_required": True,
    "min_volume_multiplier": 2.0,

    # Options Filtering
    "option_type": "0DTE",
    "delta_min": 0.60,
    "delta_max": 0.85,
    "min_open_interest": 3000,
    "max_bid_ask_spread": 0.20,

    # Risk Management
    "risk_per_trade_pct": 1.5,
    "max_contracts": 3,
    "daily_loss_limit_pct": 5.0,
    "max_drawdown_pct": 10.0,

    # Exit Conditions
    "take_profit_pct": 25,
    "stop_loss_pct": 50,
    "trailing_stop": True,
    "trailing_stop_activation": 15,
    "trailing_stop_distance": 10,
    "max_hold_time_minutes": 30,
    "exit_before_close_minutes": 15,

    # ========== NEW: TRENDLINE ANALYSIS ==========

    "trendline_analysis": {
        # Enable/disable trendline analysis
        "enabled": True,

        # Which trendline features to detect
        "detect_support_resistance": True,
        "detect_channels": True,
        "detect_breakouts": True,
        "detect_pivot_points": True,

        # Detection parameters
        "lookback_periods": 50,  # How many bars to analyze
        "min_touches": 3,  # Minimum touches to confirm S/R level
        "tolerance": 0.02,  # 2% price tolerance for clustering
        "sensitivity": "medium",  # 'low', 'medium', 'high'

        # Breakout confirmation
        "breakout_volume_multiplier": 2.0,  # Volume must be 2x average
        "breakout_confirmation_bars": 2,  # Wait N bars to confirm breakout

        # Channel trading
        "channel_min_strength": 0.7,  # Only trade strong channels (0.7+)
        "channel_position_entry": "lower_bound",  # Enter at 'lower_bound' or 'upper_bound'

        # How to use trendlines
        "use_for_entry": True,  # Use trendlines for entry signals
        "use_for_exit": True,  # Use trendlines for exit signals
        "override_traditional_indicators": False,  # If True, trendlines can override EMA/VWAP

        # Multi-timeframe analysis (future)
        "multi_timeframe": {
            "enabled": False,
            "timeframes": ["1min", "5min", "15min"],
            "require_alignment": True  # All timeframes must agree
        }
    },

    # ========== ENTRY SIGNAL PATTERNS ==========

    # Traditional patterns (existing)
    # "entry_signal": "price_above_9ema_and_vwap"

    # NEW: Trendline-based patterns
    "entry_signal": "breakout_above_resistance",
    # Options:
    #   - "breakout_above_resistance" - Buy on resistance breakout with volume
    #   - "bounce_off_support" - Buy when price bounces off support
    #   - "support_breakdown" - Sell when price breaks support
    #   - "channel_bottom_reversal" - Buy at bottom of ascending channel
    #   - "channel_top_reversal" - Sell at top of descending channel
    #   - "pivot_point_reversal" - Enter at pivot point bounces
    #   - "combined_ema_and_support" - Require both EMA and trendline alignment
}
```

### 6. WebSocket-Driven Strategy Engine

**File:** `api/engine/realtime_strategy_engine.py` (NEW)

```python
import asyncio
from typing import Dict, List, Optional, Callable
from datetime import datetime
from sqlalchemy.orm import Session

from models import User, Strategy, Position
from engine.signal_generator import SignalGenerator
from engine.risk_manager import RiskManager
from engine.order_manager import OrderManager
from analysis.trendline_analyzer import TrendlineAnalyzer
from services.market_data.market_data_aggregator import MarketDataAggregator


class RealtimeStrategyEngine:
    """
    Event-driven strategy engine powered by WebSocket streams

    Replaces polling-based execution with instant reaction to market events:
    - Listens to WebSocket streams for real-time data
    - Triggers strategy logic on new bars/quotes/trades
    - Maintains trendline analysis in real-time
    - Executes signals immediately when conditions met
    """

    def __init__(self, db: Session):
        self.db = db

        # Core components
        self.signal_generator = SignalGenerator()
        self.trendline_analyzer = TrendlineAnalyzer()
        self.risk_manager = RiskManager(db)
        self.order_manager = OrderManager(db)

        # WebSocket market data aggregator
        self.market_data_aggregator = MarketDataAggregator()

        # Active strategies tracking
        self.active_strategies: Dict[int, Strategy] = {}
        self.strategy_subscriptions: Dict[int, List[str]] = {}  # strategy_id -> [symbols]

        # Trendline cache (updated per bar)
        self.trendline_cache: Dict[str, TrendlineSignals] = {}  # symbol -> signals

        # Event loop
        self.running = False

    async def start(self):
        """
        Start the real-time strategy engine

        1. Load all active strategies from database
        2. Subscribe to WebSocket streams for each symbol
        3. Begin listening for market events
        """
        logger.info("Starting real-time strategy engine...")
        self.running = True

        # Load active strategies
        strategies = self.db.query(Strategy).filter(
            Strategy.is_active == True
        ).all()

        logger.info(f"Loaded {len(strategies)} active strategies")

        for strategy in strategies:
            await self._activate_strategy(strategy)

        logger.info("Real-time strategy engine started")

    async def stop(self):
        """Stop the real-time strategy engine"""
        logger.info("Stopping real-time strategy engine...")
        self.running = False

        # Unsubscribe from all streams
        await self.market_data_aggregator.unsubscribe_all()

        logger.info("Real-time strategy engine stopped")

    async def _activate_strategy(self, strategy: Strategy):
        """
        Activate a strategy and subscribe to its symbols

        Args:
            strategy: Strategy to activate
        """
        self.active_strategies[strategy.id] = strategy
        self.strategy_subscriptions[strategy.id] = []

        user = self.db.query(User).filter(User.id == strategy.user_id).first()

        # Subscribe to each symbol in strategy.instruments
        for symbol in strategy.instruments:
            logger.info(f"Subscribing to {symbol} for strategy {strategy.id}")

            # Subscribe to bars (primary signal source)
            await self.market_data_aggregator.subscribe_bars(
                symbol=symbol,
                timeframe=strategy.timeframe or '1min',
                on_bar=lambda bar: self._on_new_bar(user, strategy, bar)
            )

            # Subscribe to quotes (for real-time bid/ask)
            await self.market_data_aggregator.subscribe_quotes(
                symbol=symbol,
                on_quote=lambda quote: self._on_new_quote(user, strategy, quote)
            )

            # Subscribe to trades (for volume tracking)
            await self.market_data_aggregator.subscribe_trades(
                symbol=symbol,
                on_trade=lambda trade: self._on_new_trade(user, strategy, trade)
            )

            self.strategy_subscriptions[strategy.id].append(symbol)

        logger.info(f"Strategy {strategy.id} activated with {len(strategy.instruments)} symbols")

    async def _on_new_bar(self, user: User, strategy: Strategy, bar: Bar):
        """
        Called when a new bar completes (primary signal source)

        This is where most trading decisions happen:
        1. Update trendline analysis
        2. Check entry signals
        3. Check exit signals
        """
        if not self.running or strategy.id not in self.active_strategies:
            return

        symbol = bar.symbol

        try:
            # Get historical bars for analysis
            trendline_config = strategy.params_json.get('trendline_analysis', {})
            lookback = trendline_config.get('lookback_periods', 50)

            historical_bars = self.market_data_aggregator.get_bars(
                symbol=symbol,
                lookback=lookback
            )

            # Run trendline analysis if enabled
            trendline_signals = None
            if trendline_config.get('enabled'):
                trendline_signals = self.trendline_analyzer.analyze(
                    symbol=symbol,
                    bars=historical_bars,
                    config=trendline_config
                )
                # Cache for use in other callbacks
                self.trendline_cache[symbol] = trendline_signals

            # Check for entry signals
            await self._check_entry_signals(
                user=user,
                strategy=strategy,
                bar=bar,
                trendline_signals=trendline_signals
            )

            # Check for exit signals
            await self._check_exit_signals(
                user=user,
                strategy=strategy,
                bar=bar,
                trendline_signals=trendline_signals
            )

        except Exception as e:
            logger.error(f"Error processing bar for {symbol}: {e}", exc_info=True)

    async def _on_new_quote(self, user: User, strategy: Strategy, quote: Quote):
        """
        Called on every quote update (real-time bid/ask)

        Use for:
        - Updating position P&L in real-time
        - Tight stop losses that need tick-level precision
        """
        # Update positions with latest bid/ask
        positions = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == quote.symbol,
            Position.qty > 0
        ).all()

        for position in positions:
            # Use bid for long positions (exit price)
            position.current_price = quote.bid_price
            position.unrealized_pnl = (quote.bid_price - position.avg_entry_price) * position.qty

        self.db.commit()

    async def _on_new_trade(self, user: User, strategy: Strategy, trade: Trade):
        """
        Called on every trade (real-time volume tracking)

        Use for:
        - Detecting unusual volume spikes
        - Tape reading strategies
        """
        # Future: Implement volume profile analysis
        pass

    async def _check_entry_signals(
        self,
        user: User,
        strategy: Strategy,
        bar: Bar,
        trendline_signals: Optional[TrendlineSignals]
    ):
        """Check for entry signals and execute if conditions met"""
        # Check if we have room for more positions
        open_positions_count = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.qty > 0
        ).count()

        max_positions = strategy.max_positions or 3
        if open_positions_count >= max_positions:
            return

        # Generate entry signal (enhanced with trendlines)
        entry_signal = self.signal_generator.check_entry_signal_with_trendlines(
            strategy=strategy,
            symbol=bar.symbol,
            current_bar=bar,
            trendline_signals=trendline_signals
        )

        if not entry_signal:
            return

        logger.info(f"Entry signal generated: {entry_signal}")

        # Calculate position size
        qty = self.risk_manager.calculate_position_size(
            user=user,
            strategy=strategy,
            current_price=bar.close
        )

        # Run pre-trade risk checks
        risk_check = self.risk_manager.validate_pre_trade(
            user=user,
            strategy=strategy,
            symbol=bar.symbol,
            qty=qty,
            estimated_price=bar.close,
            side=entry_signal.action
        )

        if not risk_check.approved:
            logger.warning(f"Trade rejected: {risk_check.reason}")
            return

        # Execute the signal
        order_result = await self.order_manager.execute_signal(
            user=user,
            strategy=strategy,
            signal=entry_signal,
            qty=qty
        )

        if order_result.success:
            logger.info(f"Entry order executed: {order_result.message}")
        else:
            logger.error(f"Order execution failed: {order_result.message}")

    async def _check_exit_signals(
        self,
        user: User,
        strategy: Strategy,
        bar: Bar,
        trendline_signals: Optional[TrendlineSignals]
    ):
        """Check open positions for exit signals"""
        positions = self.db.query(Position).filter(
            Position.user_id == user.id,
            Position.strategy_id == strategy.id,
            Position.symbol == bar.symbol,
            Position.qty > 0
        ).all()

        for position in positions:
            # Check for exit signal (enhanced with trendlines)
            exit_signal = self.signal_generator.check_exit_signal_with_trendlines(
                strategy=strategy,
                symbol=bar.symbol,
                entry_price=position.avg_entry_price,
                current_price=bar.close,
                entry_timestamp=position.opened_at,
                position_side='long',
                current_high=bar.high,
                current_low=bar.low,
                trendline_signals=trendline_signals
            )

            if not exit_signal:
                continue

            logger.info(f"Exit signal generated: {exit_signal}")

            # Close the position
            order_result = await self.order_manager.close_position(
                user=user,
                strategy=strategy,
                position=position,
                reason=exit_signal.reason
            )

            if order_result.success:
                logger.info(f"Exit order executed: {order_result.message}")
            else:
                logger.error(f"Exit order failed: {order_result.message}")
```

### 7. Enhanced Signal Generator

**Update:** `api/engine/signal_generator.py`

```python
def check_entry_signal_with_trendlines(
    self,
    strategy: Strategy,
    symbol: str,
    current_bar: Bar,
    trendline_signals: Optional[TrendlineSignals] = None
) -> Optional[Signal]:
    """
    Enhanced entry signal that combines traditional indicators with trendlines

    Args:
        strategy: Strategy with params_json configuration
        symbol: Trading symbol
        current_bar: Current bar data
        trendline_signals: Trendline analysis results (if enabled)

    Returns:
        Signal object if entry conditions met, None otherwise
    """
    params = strategy.params_json
    indicators = {}

    # ========== TRADITIONAL INDICATORS (EXISTING) ==========

    # Update price history
    self._update_history(symbol, current_bar.close, current_bar.volume)

    # EMA check
    ema_period = params.get('ema_period', 9)
    if ema_period:
        ema_value = self._calculate_ema(symbol, ema_period)
        if ema_value is not None:
            indicators['ema'] = ema_value

    # VWAP check
    if params.get('use_vwap'):
        vwap_value = self._calculate_vwap(symbol)
        if vwap_value is not None:
            indicators['vwap'] = vwap_value

    # Volume spike check
    if params.get('volume_spike_required'):
        min_volume_multiplier = params.get('min_volume_multiplier', 2.0)
        avg_volume = self._calculate_avg_volume(symbol, period=20)
        if avg_volume and avg_volume > 0:
            volume_ratio = current_bar.volume / avg_volume
            indicators['volume_ratio'] = volume_ratio
            if volume_ratio < min_volume_multiplier:
                logger.debug(f"{symbol}: Volume spike insufficient")
                return None

    # ========== TRENDLINE ANALYSIS (NEW) ==========

    if trendline_signals and params.get('trendline_analysis', {}).get('use_for_entry'):
        trendline_config = params.get('trendline_analysis', {})
        entry_pattern = params.get('entry_signal', '')

        # Pattern 1: Breakout above resistance
        if 'breakout_above_resistance' in entry_pattern:
            if trendline_signals.breakouts:
                breakout = trendline_signals.breakouts
                if breakout.type == 'resistance_breakout':
                    indicators['breakout'] = True
                    indicators['breakout_level'] = breakout.level
                    indicators['volume_confirmed'] = breakout.volume_confirmation

                    # Require volume confirmation if configured
                    if not breakout.volume_confirmation:
                        logger.debug(f"{symbol}: Breakout lacks volume confirmation")
                        return None
                else:
                    logger.debug(f"{symbol}: No resistance breakout detected")
                    return None
            else:
                logger.debug(f"{symbol}: No breakout detected")
                return None

        # Pattern 2: Bounce off support
        elif 'bounce_off_support' in entry_pattern:
            if not trendline_signals.support_levels:
                logger.debug(f"{symbol}: No support levels detected")
                return None

            # Check if price is near support
            nearest_support = None
            min_distance = float('inf')

            for support in trendline_signals.support_levels:
                distance = abs(current_bar.close - support) / support
                if distance < min_distance:
                    min_distance = distance
                    nearest_support = support

            # Must be within 1% of support
            if min_distance < 0.01:
                # Check for bullish reversal candle
                if current_bar.close > current_bar.open:
                    indicators['support_bounce'] = True
                    indicators['support_level'] = nearest_support
                else:
                    logger.debug(f"{symbol}: Not a bullish reversal candle")
                    return None
            else:
                logger.debug(f"{symbol}: Price not near support")
                return None

        # Pattern 3: Support breakdown (bearish)
        elif 'support_breakdown' in entry_pattern:
            if trendline_signals.breakouts:
                breakout = trendline_signals.breakouts
                if breakout.type == 'support_breakdown':
                    indicators['breakdown'] = True
                    indicators['breakdown_level'] = breakout.level
                    indicators['volume_confirmed'] = breakout.volume_confirmation

                    if not breakout.volume_confirmation:
                        logger.debug(f"{symbol}: Breakdown lacks volume confirmation")
                        return None
                else:
                    logger.debug(f"{symbol}: No support breakdown detected")
                    return None
            else:
                return None

        # Pattern 4: Channel bottom (ascending channel)
        elif 'channel_bottom' in entry_pattern:
            if not trendline_signals.channels:
                logger.debug(f"{symbol}: No channel detected")
                return None

            channel = trendline_signals.channels

            # Check if channel is ascending
            if channel.direction != 'ascending':
                logger.debug(f"{symbol}: Channel not ascending")
                return None

            # Check if channel is strong enough
            min_strength = trendline_config.get('channel_min_strength', 0.7)
            if channel.strength < min_strength:
                logger.debug(f"{symbol}: Channel strength {channel.strength:.2f} < {min_strength}")
                return None

            # Check if price is at lower bound
            bar_index = len(self.price_history[symbol]) - 1
            if channel.is_price_at_lower_bound(current_bar.close, bar_index, tolerance=0.005):
                indicators['channel_entry'] = True
                indicators['channel_direction'] = 'ascending'
                indicators['channel_strength'] = channel.strength
            else:
                logger.debug(f"{symbol}: Price not at channel lower bound")
                return None

        # Pattern 5: Combined EMA and support
        elif 'combined_ema_and_support' in entry_pattern:
            # Require both EMA and support bounce
            if 'ema' not in indicators:
                logger.debug(f"{symbol}: EMA not available")
                return None

            if not trendline_signals.support_levels:
                logger.debug(f"{symbol}: No support levels")
                return None

            # Check EMA alignment
            if current_bar.close <= indicators['ema']:
                logger.debug(f"{symbol}: Price not above EMA")
                return None

            # Check support proximity
            nearest_support = min(
                trendline_signals.support_levels,
                key=lambda s: abs(current_bar.close - s)
            )
            distance = abs(current_bar.close - nearest_support) / nearest_support

            if distance > 0.02:  # Must be within 2%
                logger.debug(f"{symbol}: Price not near support")
                return None

            indicators['combined_signal'] = True
            indicators['support_level'] = nearest_support

    # ========== TRADITIONAL PATTERN CHECKS (EXISTING) ==========

    # If using traditional patterns, check them here
    # (Keep existing EMA/VWAP logic from current implementation)

    # ========== CALCULATE CONFIDENCE ==========

    confidence = self._calculate_signal_confidence_with_trendlines(
        indicators,
        params,
        trendline_signals
    )

    # ========== DETERMINE ACTION ==========

    entry_pattern = params.get('entry_signal', 'price_above_9ema_and_vwap')

    # Determine buy vs sell based on pattern
    if any(word in entry_pattern for word in ['breakout', 'bounce', 'channel_bottom', 'above']):
        action = 'buy'  # Bullish
    elif any(word in entry_pattern for word in ['breakdown', 'channel_top', 'below']):
        action = 'sell'  # Bearish
    else:
        action = 'buy'  # Default

    # ========== GENERATE SIGNAL ==========

    signal = Signal(
        signal_type='entry',
        action=action,
        symbol=symbol,
        confidence=confidence,
        reason=f"Entry: {', '.join(indicators.keys())}",
        price=current_bar.close,
        indicators=indicators
    )

    logger.info(f"ENTRY SIGNAL: {signal}")
    return signal


def _calculate_signal_confidence_with_trendlines(
    self,
    indicators: Dict,
    params: Dict,
    trendline_signals: Optional[TrendlineSignals]
) -> float:
    """
    Calculate confidence score including trendline factors

    Returns:
        float: Confidence between 0.0 and 1.0
    """
    # Base confidence
    confidence = 0.6

    # Traditional indicator boosts (existing)
    if 'ema' in indicators and 'vwap' in indicators:
        confidence += 0.1

    if 'volume_ratio' in indicators and indicators['volume_ratio'] > 2.0:
        confidence += 0.1

    # Trendline boosts (NEW)
    if 'breakout' in indicators:
        confidence += 0.15  # Breakouts are high confidence
        if indicators.get('volume_confirmed'):
            confidence += 0.05  # Extra boost for volume confirmation

    if 'support_bounce' in indicators:
        confidence += 0.12  # Support bounces are strong signals

    if 'channel_entry' in indicators:
        channel_strength = indicators.get('channel_strength', 0)
        confidence += 0.10 * channel_strength  # Scale by channel strength

    if 'combined_signal' in indicators:
        confidence += 0.15  # Combined signals are very strong

    # Trend strength boost
    if trendline_signals and hasattr(trendline_signals, 'trend_strength'):
        if abs(trendline_signals.trend_strength) > 0.5:
            confidence += 0.05  # Strong trend confirmation

    # Cap at 0.95 (never 100% certain)
    return min(confidence, 0.95)
```

---

## Implementation Roadmap

### Phase 1: Core Trendline Components (Week 1-2)
- [ ] Create `TrendlineAnalyzer` class
- [ ] Implement `SupportResistanceDetector`
- [ ] Implement `ChannelDetector`
- [ ] Implement `BreakoutDetector`
- [ ] Add unit tests for each component
- [ ] Validate algorithms against historical data

### Phase 2: Strategy Integration (Week 3)
- [ ] Update `Strategy.params_json` schema
- [ ] Create database migration for new params
- [ ] Update `SignalGenerator` with trendline methods
- [ ] Add trendline pattern matching
- [ ] Create strategy templates with trendline configs

### Phase 3: WebSocket Engine (Week 4-5)
- [ ] Create `RealtimeStrategyEngine` class
- [ ] Build `MarketDataAggregator` for WebSocket streams
- [ ] Integrate with Alpaca WebSocket API
- [ ] Implement event handlers (bars, quotes, trades)
- [ ] Add trendline caching mechanism
- [ ] Test with paper trading

### Phase 4: UI Integration (Week 6)
- [ ] Add trendline configuration form
- [ ] Create trendline visualization charts
- [ ] Display support/resistance levels on charts
- [ ] Show channel lines on charts
- [ ] Highlight breakout points
- [ ] Real-time strategy status dashboard

### Phase 5: Backtesting (Week 7)
- [ ] Build trendline backtesting engine
- [ ] Historical bar replay with trendline detection
- [ ] Performance comparison (trendline vs traditional)
- [ ] Optimize trendline parameters
- [ ] Generate backtest reports

### Phase 6: Advanced Features (Week 8+)
- [ ] Multi-timeframe trendline analysis
- [ ] Machine learning trendline detection
- [ ] Pattern recognition (head & shoulders, triangles)
- [ ] Adaptive sensitivity based on volatility
- [ ] Portfolio-level trendline correlation
- [ ] Risk management with trendline stops

---

## Testing Strategy

### Unit Tests
```python
# tests/test_trendline_analyzer.py
def test_support_resistance_detection():
    bars = create_test_bars_with_support_at_100()
    detector = SupportResistanceDetector()
    support_levels = detector.find_support(bars, min_touches=3)
    assert 100.0 in support_levels

def test_channel_detection():
    bars = create_ascending_channel_bars()
    detector = ChannelDetector()
    channel = detector.detect(bars)
    assert channel is not None
    assert channel.direction == 'ascending'

def test_breakout_detection():
    bars = create_resistance_breakout_bars(resistance=150.0)
    detector = BreakoutDetector()
    breakout = detector.check(bars, [], [150.0])
    assert breakout is not None
    assert breakout.type == 'resistance_breakout'
```

### Integration Tests
```python
# tests/test_realtime_engine.py
async def test_strategy_execution_with_trendlines():
    engine = RealtimeStrategyEngine(db)
    strategy = create_test_strategy_with_breakout_pattern()

    # Simulate bars leading to breakout
    bars = create_breakout_scenario()

    for bar in bars:
        await engine._on_new_bar(user, strategy, bar)

    # Verify entry signal was generated
    positions = db.query(Position).filter(
        Position.strategy_id == strategy.id
    ).all()

    assert len(positions) == 1
```

### Paper Trading Tests
- Run strategies with trendline analysis in paper mode
- Compare results with traditional indicators only
- Monitor false signals and missed opportunities
- Optimize parameters based on results

---

## Performance Considerations

### Computational Complexity
- **Support/Resistance Detection:** O(n²) worst case (can optimize with caching)
- **Channel Detection:** O(n) with numpy linear regression
- **Breakout Detection:** O(n×m) where m = number of levels
- **Real-time Updates:** Only recalculate on new bar (1-5 min intervals)

### Optimization Strategies
1. **Caching:** Cache trendline results per bar, invalidate on new bar
2. **Incremental Updates:** Don't recalculate entire history, update incrementally
3. **Parallel Processing:** Analyze multiple symbols concurrently
4. **Database Indexing:** Index on timestamp for fast historical queries
5. **Memory Management:** Limit lookback periods (50-100 bars max)

### Scalability
- Single server: Handle 10-20 active strategies with 5 symbols each
- Multi-server (future): Use Celery + Redis for distributed processing
- WebSocket connections: Pool connections, share streams across strategies

---

## Risk Management with Trendlines

### Trendline-Based Stops

```python
# Example: Use support as dynamic stop loss
def calculate_trendline_stop(position, trendline_signals):
    if not trendline_signals.support_levels:
        return None

    # Find nearest support below entry
    entry_price = position.avg_entry_price
    supports_below = [s for s in trendline_signals.support_levels if s < entry_price]

    if supports_below:
        # Place stop just below nearest support
        nearest_support = max(supports_below)
        stop_price = nearest_support * 0.99  # 1% buffer
        return stop_price

    return None
```

### False Breakout Protection

```python
# Wait for confirmation bars before entering breakout
"trendline_analysis": {
    "breakout_confirmation_bars": 2,  # Wait 2 bars to confirm
    "breakout_volume_multiplier": 2.0,  # Require 2x volume
}
```

---

## Monitoring & Alerting

### Key Metrics to Track
- **Trendline Detection Rate:** % of symbols with detected S/R levels
- **Breakout Success Rate:** % of breakouts that continue vs reverse
- **Channel Accuracy:** How well price respects detected channels
- **Signal Quality:** Win rate comparison (trendline vs traditional)
- **False Signal Rate:** % of signals that immediately reverse

### Logging
```python
logger.info(f"Trendline analysis: {symbol}")
logger.info(f"  Support levels: {support_levels}")
logger.info(f"  Resistance levels: {resistance_levels}")
logger.info(f"  Channel: {channel.direction if channel else 'None'}")
logger.info(f"  Breakout: {breakout.type if breakout else 'None'}")
logger.info(f"  Trend strength: {trend_strength:.2f}")
```

---

## Next Steps

1. **Review this gameplan** - Discuss and refine approach
2. **Prioritize features** - Which components to build first?
3. **Set milestones** - Define clear deliverables
4. **Begin implementation** - Start with Phase 1 (trendline components)
5. **Iterate and test** - Build, test, refine, repeat

---

## Questions to Resolve

1. **Timeframes:** Which bar timeframes to support? (1min, 5min, 15min, 1hr?)
2. **Sensitivity:** Default sensitivity levels for trendline detection?
3. **UI Priority:** How important is visual chart display vs backend first?
4. **Backtesting:** Historical data source? (Alpaca, local DB, other?)
5. **Migration:** Gradual rollout or big switch from polling to WebSocket?

---

## References

### Technical Analysis Resources
- Support and Resistance: https://www.investopedia.com/trading/support-and-resistance-basics/
- Channel Trading: https://www.investopedia.com/articles/trading/06/channeltrading.asp
- Breakout Strategies: https://www.investopedia.com/articles/trading/08/trading-breakouts.asp

### Implementation References
- Alpaca WebSocket Docs: https://alpaca.markets/docs/api-references/market-data-api/stock-pricing-data/realtime/
- NumPy Linear Regression: https://numpy.org/doc/stable/reference/generated/numpy.polyfit.html
- AsyncIO Best Practices: https://docs.python.org/3/library/asyncio-task.html

---

**Document Version:** 1.0
**Last Updated:** 2025-11-22
**Status:** Draft - Pending Review

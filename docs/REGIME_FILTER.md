# Regime Filter - Multi-Timeframe Validation

**Phase 2 Implementation Guide**

A regime filter determines the overall market "state" to ensure trades align with the dominant trend.

---

## 🎯 Core Concept

**Rule:** Only trade in the direction of the higher timeframe trend.

```
30-minute chart: Uptrend (bullish regime)
  ✅ Allow: Buy signals (calls)
  ❌ Block: Sell signals (counter-trend)

30-minute chart: Downtrend (bearish regime)
  ❌ Block: Buy signals (counter-trend)
  ✅ Allow: Sell signals (puts/exits)

30-minute chart: Sideways (neutral regime)
  ⚠️ Reduce size or skip trades
```

---

## 📊 Three Timeframes

### 1. **1-Minute** (Entry Timing)
- Generate entry signals
- Precise entry/exit points
- High noise, needs filtering

### 2. **5-Minute** (Confirmation)
- Confirm 1m signals
- Reduce false signals
- Trend alignment check

### 3. **30-Minute** (Regime Filter)
- Overall market direction
- Filter out counter-trend trades
- Highest priority filter

---

## 🔧 Implementation Methods

### Method 1: EMA Crossover (Recommended for Start)

```python
class RegimeFilter:
    """30-minute regime filter using EMA crossover."""

    def get_regime(self, bars_30m):
        """
        Returns: 'bullish', 'bearish', or 'neutral'
        """
        ema9 = calculate_ema(bars_30m, period=9)
        ema21 = calculate_ema(bars_30m, period=21)

        # Trend strength (separation)
        separation = abs(ema9 - ema21) / ema21

        if separation < 0.005:  # < 0.5% apart
            return 'neutral'  # Too choppy

        if ema9 > ema21:
            return 'bullish'
        else:
            return 'bearish'
```

### Method 2: Price vs MA

```python
def get_regime(self, bars_30m):
    """Price position relative to MA."""
    ma20 = calculate_sma(bars_30m, period=20)
    current_price = bars_30m[-1]['close']

    if current_price > ma20 * 1.005:  # 0.5% above
        return 'bullish'
    elif current_price < ma20 * 0.995:  # 0.5% below
        return 'bearish'
    else:
        return 'neutral'
```

### Method 3: Multi-Timeframe Alignment (Advanced)

```python
def get_regime(self, bars_5m, bars_30m):
    """Both timeframes must agree."""
    trend_5m = get_trend(bars_5m)
    trend_30m = get_trend(bars_30m)

    if trend_5m == 'up' and trend_30m == 'up':
        return 'strong_bullish'
    elif trend_5m == 'down' and trend_30m == 'up':
        return 'bullish_pullback'  # Buy the dip
    elif trend_5m == 'down' and trend_30m == 'down':
        return 'strong_bearish'
    else:
        return 'neutral'
```

---

## 🎨 Signal Filtering Logic

### Basic Filter

```python
def should_allow_trade(signal_action, regime):
    """
    Args:
        signal_action: 'buy' or 'sell'
        regime: 'bullish', 'bearish', 'neutral'

    Returns:
        bool: True if trade allowed
    """
    # Neutral regime: allow both (or skip entirely)
    if regime == 'neutral':
        return False  # Skip choppy markets

    # Buy calls only in bullish regime
    if signal_action == 'buy' and regime == 'bullish':
        return True

    # Sell/exit only in bearish regime
    if signal_action == 'sell' and regime == 'bearish':
        return True

    # Block counter-trend trades
    return False
```

### Advanced Filter (with strength)

```python
def should_allow_trade(signal_action, regime, signal_confidence):
    """Filter with signal strength consideration."""

    # Strong signals can override weak regime
    if signal_confidence > 0.8:
        return True

    # Regular filtering
    if regime == 'neutral':
        return signal_confidence > 0.7  # Higher bar in chop

    if signal_action == 'buy' and regime == 'bullish':
        return True

    if signal_action == 'sell' and regime == 'bearish':
        return True

    return False
```

---

## 🚀 Integration Points

### In `strategy_executor.py`

```python
async def _check_entry_signals(self, ...):
    """Check entry signals with regime filter."""

    # 1. Fetch multi-timeframe bars
    bars_1m = await options_service.get_bars(symbol, '1Min', limit=50)
    bars_5m = await options_service.get_bars(symbol, '5Min', limit=50)
    bars_30m = await options_service.get_bars(symbol, '30Min', limit=50)

    # 2. Determine regime
    regime = self.regime_filter.get_regime(bars_30m)
    logger.info(f"📊 Regime (30m): {regime}")

    # 3. Generate signal
    signal = self.signal_generator.generate_signal(
        symbol=symbol,
        bars=bars_1m,
        current_price=current_price,
        additional_data=market_data
    )

    # 4. Apply regime filter
    if not self.regime_filter.should_allow_trade(signal.action, regime):
        logger.info(f"🚫 Signal blocked by {regime} regime")
        return

    # 5. Optional: 5m confirmation
    trend_5m = self._get_trend(bars_5m)
    if trend_5m != regime:
        logger.info("⏳ Waiting for 5m alignment...")
        return

    # 6. Place order (all filters passed)
    logger.info(f"✅ Trade approved: {regime} regime + {trend_5m} 5m")
    # ... order placement logic
```

### In `signal_generator.py`

```python
class SignalGenerator:
    """Enhanced with multi-timeframe support."""

    def __init__(self):
        self.regime_filter = RegimeFilter()

    def generate_signal_mtf(
        self,
        bars_1m: List[Dict],
        bars_5m: List[Dict],
        bars_30m: List[Dict],
        current_price: float,
        additional_data: Dict
    ) -> Optional[Signal]:
        """
        Multi-timeframe signal generation.

        Returns None if regime filter blocks.
        """
        # Determine regime
        regime = self.regime_filter.get_regime(bars_30m)

        # Generate 1m signal
        signal_1m = self._generate_from_bars(bars_1m, current_price)

        if not signal_1m:
            return None

        # Apply regime filter
        if not self.regime_filter.should_allow_trade(signal_1m.action, regime):
            return None

        # Add regime info to signal
        signal_1m.regime = regime
        signal_1m.confidence *= self._regime_confidence_multiplier(regime)

        return signal_1m
```

---

## 📈 For 0DTE Options Strategy

### Recommended Settings

```python
# Strategy params_json
{
    "timeframes": {
        "entry": "1Min",       # Entry signals
        "confirmation": "5Min",  # Trend confirmation
        "regime": "30Min"      # Overall filter
    },

    "regime_filter": {
        "enabled": True,
        "ema_fast": 9,
        "ema_slow": 21,
        "min_separation": 0.005,  # 0.5%
        "allow_neutral": False     # Skip neutral regimes
    },

    "multi_timeframe": {
        "require_5m_alignment": True,
        "require_30m_alignment": True
    }
}
```

### Expected Impact

**Before Regime Filter:**
- Win rate: 55%
- Trades per day: 15
- Many whipsaws in chop

**After Regime Filter:**
- Win rate: 65-70% (improved)
- Trades per day: 8-10 (reduced but better quality)
- Fewer whipsaws
- Better risk/reward

---

## 🎯 Phase 2 Implementation Checklist

### Step 1: Add Bar Fetching
- [ ] Implement `get_bars()` method in options service
- [ ] Support 1Min, 5Min, 30Min timeframes
- [ ] Cache bars for performance

### Step 2: Create Regime Filter
- [ ] Create `engine/regime_filter.py`
- [ ] Implement EMA crossover method
- [ ] Add `get_regime()` function
- [ ] Add `should_allow_trade()` function

### Step 3: Update Signal Generator
- [ ] Add multi-timeframe support
- [ ] Integrate regime filter
- [ ] Add confidence adjustments based on regime

### Step 4: Update Strategy Executor
- [ ] Fetch multi-timeframe bars
- [ ] Call regime filter before entries
- [ ] Log regime state
- [ ] Add regime to signal context

### Step 5: Testing
- [ ] Test in different regimes (bull/bear/neutral)
- [ ] Verify counter-trend blocking
- [ ] Monitor win rate improvement
- [ ] Backtest if possible

---

## 💡 Visual Example

```
Timeline: 9:30 AM ────────────────────────── 12:00 PM

30m Bars:  📈 Up    📈 Up    📈 Up    📉 Down
Regime:    ╰──── Bullish ────╯    ╰── Bearish ──╮

5m Bars:   📈📉📈📈📈📉📈📉📉📉📉📉
Trend:     ↗️ Bullish ↗️       ↘️ Bearish ↘️

1m Signal: 🟢      🔴      🟢      🔴
Time:      10:15   10:30   11:15   11:45

Result:    ✅      ❌      ❌      ✅
           Allow   Block   Block   Allow
           (with   (vs     (vs     (with
           regime) regime) regime) regime)
```

---

## 🚨 Common Mistakes to Avoid

1. **Over-filtering**: Don't require ALL timeframes to align perfectly
2. **Lag**: 30m regime updates slowly, accept some lag
3. **Whipsaw**: In neutral regime, either skip OR reduce size (don't trade both sides)
4. **Ignoring strength**: Strong 1m signal + neutral regime might still work
5. **No adaptation**: Regime changes, adjust strategy accordingly

---

## 📚 Next Steps

After implementing regime filter:

1. **Phase 3**: Add position Greeks aggregation
2. **Phase 4**: Volatility-based position sizing
3. **Phase 5**: Multi-leg strategies (spreads)

---

## 🔗 Related Docs

- [OPTIONS_DATA_INTEGRATION_PHASE1.md](./OPTIONS_DATA_INTEGRATION_PHASE1.md) - Current implementation
- [STRATEGY_INTEGRATION.md](./STRATEGY_INTEGRATION.md) - Integration guide
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) - Common issues

---

## 📝 Notes

- Start with simple EMA crossover
- Test thoroughly before going live
- Monitor regime changes in logs
- Adjust EMA periods if needed (9/21 is a good start)
- Consider ADX for trend strength later

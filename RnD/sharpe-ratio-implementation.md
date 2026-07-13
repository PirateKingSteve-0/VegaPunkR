# Sharpe Ratio Implementation

## What It Is

The Sharpe ratio measures **risk-adjusted return** - how much return you get per unit of risk taken.

## Formula (Per-Trade % Returns)

```
For each trade:
  Return% = (Net P&L / Entry Cost) * 100

Sharpe Ratio = Mean(Returns%) / StdDev(Returns%)
```

## Example

**Trade 1:** Cost $1,000, P&L +$200 → Return = +20%
**Trade 2:** Cost $1,000, P&L -$100 → Return = -10%
**Trade 3:** Cost $1,000, P&L +$300 → Return = +30%

- **Mean Return**: (20% + (-10%) + 30%) / 3 = 13.33%
- **Std Dev**: 16.33%
- **Sharpe Ratio**: 13.33 / 16.33 = **0.82**

## Interpretation

| Sharpe Ratio | Quality     | Meaning |
|--------------|-------------|---------|
| **≥ 3.0**    | Excellent   | Exceptional risk-adjusted returns |
| **≥ 2.0**    | Very Good   | Strong performance for the risk taken |
| **≥ 1.0**    | Good        | Acceptable, you're getting paid for risk |
| **0 - 1.0**  | Poor        | Barely compensated for volatility |
| **< 0**      | Negative    | Losing money |

## Why Per-Trade % Returns?

For 0DTE options trading, **per-trade percentage returns** make the most sense because:

1. **No overnight holdings**: Traditional Sharpe uses daily/monthly returns, but 0DTE positions close same-day
2. **Position size varies**: Using % return normalizes for different position sizes
3. **Apples-to-apples**: A 10% return on a $500 trade is equivalent to a 10% return on a $5,000 trade

## How It's Calculated

### Frontend (UI)
File: `ui/src/app/pages/performance/performance.component.ts`

```typescript
const returns: number[] = [];
for (const position of closedPositions) {
  const cost = Math.abs(position.cost || 0);
  if (cost < 0.01) continue; // Skip invalid data

  const pnl = position.net_pnl ?? position.gain_loss ?? 0;
  const returnPct = (pnl / cost) * 100;
  returns.push(returnPct);
}

// Mean and standard deviation
const meanReturn = average(returns);
const stdDevReturn = standardDeviation(returns);
const sharpeRatio = meanReturn / stdDevReturn;
```

### Backend (API)
File: `api/routers/performance.py`

```python
returns = []
for trade in trades:
    # Options: cost = entry_price * qty * 100 (contract multiplier)
    # Stocks: cost = entry_price * qty
    multiplier = 100 if trade.asset_class == 'option' else 1
    cost = abs(trade.entry_price * trade.qty * multiplier)

    if cost > 0.01:
        return_pct = (trade.pnl / cost) * 100
        returns.append(return_pct)

mean_return = sum(returns) / len(returns)
variance = sum((x - mean_return) ** 2 for x in returns) / len(returns)
std_dev = sqrt(variance)
sharpe_ratio = mean_return / std_dev if std_dev > 0 else 0.0
```

## What Makes a Good Sharpe for 0DTE?

**Standard benchmarks** (from traditional investing):
- S&P 500 long-term: ~0.5 - 0.8
- Hedge funds: 1.0 - 2.0
- Exceptional traders: 2.0+

**For 0DTE options** (high volatility):
- **> 1.5**: Solid - you're getting good returns for the wild swings
- **> 2.0**: Excellent - exceptional risk management
- **> 3.0**: Outlier - rarely sustainable long-term

## Limitations

1. **Assumes normal distribution**: If your returns are heavily skewed (many small wins, few huge losses), Sharpe can be misleading
2. **No risk-free rate**: We're not subtracting the risk-free rate (T-bill yield), which is technically part of the formula. For short-term 0DTE trading, this is negligible.
3. **Not annualized**: Traditional Sharpe ratios are annualized. Ours is per-trade, so it's not directly comparable to published Sharpe ratios from funds.
4. **Requires 2+ trades**: Can't calculate standard deviation with one trade

## Complementary Metrics

Use these alongside Sharpe for a complete picture:

1. **Win Rate**: % of winning trades (doesn't tell you magnitude)
2. **Profit Factor**: Gross profit / Gross loss (doesn't account for volatility)
3. **Max Drawdown**: Largest peak-to-trough decline (shows worst-case scenario)
4. **Sortino Ratio**: Like Sharpe, but only penalizes downside volatility

## Where It Appears

**Performance Dashboard:**
- Displayed as a metric card in the top grid
- Shows the ratio value (e.g., "2.15")
- Color-coded: green (≥2.0), gray (1.0-2.0), red (<1.0)
- Quality label: "Excellent", "Very Good", "Good", "Poor", or "Negative"

**API Endpoint:**
- `GET /api/v1/performance` - Returns Sharpe for all strategies
- `POST /api/v1/performance/calculate/{strategy_id}?period=all_time` - Calculates Sharpe for a strategy

## Example Scenarios

### Scenario 1: Consistent Winner
- 10 trades, all profitable: +5%, +7%, +6%, +5%, +8%, +7%, +6%, +5%, +7%, +6%
- Mean: 6.2%, Std Dev: 1.03%
- **Sharpe: 6.0** ← Excellent!

### Scenario 2: Volatile But Profitable
- 10 trades: +50%, -30%, +40%, -20%, +60%, -25%, +45%, -15%, +35%, -10%
- Mean: 13%, Std Dev: 30.7%
- **Sharpe: 0.42** ← Poor (returns don't justify volatility)

### Scenario 3: Grinder Strategy
- 10 trades: +2%, +1%, +3%, +2%, +1%, +2%, +3%, +1%, +2%, +1%
- Mean: 1.8%, Std Dev: 0.79%
- **Sharpe: 2.28** ← Very Good! (low volatility compensates for low returns)

## Actionable Insights

**If Sharpe < 1.0:**
- Your returns barely justify the risk you're taking
- Consider: smaller position sizes, tighter stops, or different entry criteria

**If Sharpe 1.0 - 2.0:**
- Healthy risk-adjusted returns
- Keep doing what you're doing, optimize incrementally

**If Sharpe > 2.0:**
- Exceptional performance
- Monitor for over-fitting or lucky streak
- Consider scaling up position sizes carefully

## Code Changes

### Files Modified
1. `ui/src/app/pages/performance/performance.component.ts` - Added Sharpe calculation to metrics
2. `api/routers/performance.py` - Updated Sharpe formula from dollar P&L to percentage returns

### What Changed
- **Before**: `Sharpe = Mean($PnL) / StdDev($PnL)` ❌ (not accurate)
- **After**: `Sharpe = Mean(%Return) / StdDev(%Return)` ✅ (correct)

### Testing
To verify it's working:
1. Go to Performance page in UI
2. Check the "Sharpe Ratio" metric card
3. Should show a value like "1.85" with quality label "Good"
4. If you have <2 trades, it shows "N/A"

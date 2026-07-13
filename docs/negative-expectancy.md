# Negative Expectancy by Construction

*Written 2026-07-13, after a day that lost $1,851 with no bug in the engine.*

## The short version

If your **stop loss is wider than your take profit**, you need to win *more than half*
your trades just to break even. If you don't, you lose money on every trade in
expectation — and trading more only loses it faster.

That is what "negative expectancy by construction" means: not a bug, not bad luck, not
a bad day. The parameters guarantee the outcome. The engine did exactly what it was
told, 124 times.

## The one formula that matters

To break even, your win rate must satisfy:

```
                       stop_loss
  break-even win rate = ─────────────────────
                       stop_loss + take_profit
```

That's it. Two numbers you type into a form determine the win rate you must achieve
before you make a single dollar.

**What we were running on 2026-07-13:**

| Strategy | Stop loss | Take profit | Break-even win rate | Actual |
|---|---|---|---|---|
| TSLA 0DTE Scalping | 20% | 15% | **57.1%** | 31% |
| SPY 0DTE Scalping | 50% | 25% | **66.7%** | — |

TSLA needed to be right **57% of the time** and was right **31%** of the time.

## What that costs, per trade

Expected value per trade:

```
  EV = (win_rate × take_profit) − (loss_rate × stop_loss)
```

For TSLA that day:

```
  EV = (0.31 × 15%) − (0.69 × 20%)
     =  4.65%       −  13.8%
     = −9.15% per trade
```

**Every single trade was worth about −9% of the position, before it was placed.**

At roughly $1,000–1,800 per position that's −$100 to −$165 in expectation *per trade*.
Multiply by 124 round trips:

```
  124 × ~−$15 avg realized  ≈  −$1,851   ← exactly what happened
```

The loss was not an accident. It was arithmetic.

## Why the day *looked* like a disaster

The same broken trade had been running for weeks. It just didn't trade much:

```
2026-05-21   36 trades    -$2.13
2026-07-08   13 trades    -$2.67
2026-07-09   40 trades   -$72.00
2026-07-13  124 trades  -$1,851.00   ← same flaw, more volume
```

A −$70 day at 40 trades and a −$1,851 day at 124 trades are **the same trade**. Volume
didn't cause the loss; it revealed it. This is the insidious part of negative
expectancy: at low volume it hides in the noise and looks like variance.

## The trap that made it worse

`params_json` carried **two spellings of the same setting**, with different values:

```python
# signal_generator.py:355  —  `_pct` wins
stop_loss_pct = params.get('stop_loss_pct') or params.get('stop_loss_percentage')
```

SPY had `stop_loss_pct: 50` **and** `stop_loss_percentage: 15`. The UI edits the
`_percentage` column. So:

- **The UI showed a 15% stop.**
- **The engine enforced a 50% stop.**

Nobody was lying. Nobody was wrong. The screen simply was not showing the number being
traded, and there was no way to tell from the screen.

**Lesson:** two names for one setting is not a convenience, it's a bug waiting for a bad
day. All four keys and both columns are now written together (`scripts/fix_strategy_expectancy.py`).

## What we changed

Both strategies moved to **1:2 risk/reward — SL 15% / TP 30%**:

```
  break-even win rate:  15 / (15 + 30)  =  33.3%
```

| | Before | After |
|---|---|---|
| TSLA | SL 20 / TP 15 → 57.1% needed | SL 15 / TP 30 → **33.3%** needed |
| SPY | SL 50 / TP 25 → 66.7% needed | SL 15 / TP 30 → **33.3%** needed |

## What we did NOT fix — read this part

**This does not make the strategy profitable.** It removes the *structural* guarantee of
losing. At the observed 31% win rate, 1:2 is *still* negative:

```
  EV = (0.31 × 30%) − (0.69 × 15%)  =  −1.05% per trade
```

We went from "guaranteed to lose" to "loses unless the signal improves." That is
progress, not a solution.

**And the win rate is not a constant.** It is a *function of* the stop and target you
choose. The 31% was measured with a 15% target — an easy target to reach. A 30% target
is hit less often, so the win rate will likely fall. You cannot hold win rate fixed and
tune your way to profit; the two move together.

### The measured number (not a projection)

Across **275 closed TSLA trades** in the database, computed from real fill prices:

```
  mean per-trade return :  -1.08%
  std dev               :   7.38%
  Sharpe                :  -0.146
```

**The strategy's realized expectancy is −1.08% per trade.** That is the ground truth, and
it is negative. The theoretical EV under the new 15/30 params at a 31% win rate is
−1.05% — essentially identical. Changing the stop and target moved the *structure*, not
the edge.

A negative mean per-trade return is what negative expectancy looks like when you stop
theorising and just measure it. Watch this number. If it is not positive, nothing else
about the strategy matters.

## The real problem

A 31% win rate on a **38-second re-entry cycle** is the actual finding. That cadence is
not a market signal — it's a machine cycling as fast as its throttle allows:

- Median gap between consecutive entries: **38 seconds**
- 106 of 119 entries came within 90s of the previous one
- The 5-second order rate limiter blocked **108 of ~233 attempted orders (46%)**

That rate limiter is the only thing holding the churn down. It is a governor pinned to
the floor, not a safety margin.

No stop/target arrangement rescues an entry signal that is wrong 69% of the time while
grinding spread and fees every 38 seconds. `price_above_9ema_and_vwap` + a volume spike,
evaluated every second on 0DTE TSLA, is firing on noise.

## Before running this live again

1. **Re-measure the win rate** under the new 15/30 params. The old 31% is not
   transferable.
2. **Add a re-entry cooldown.** Round-tripping the same decaying contract 50 times in a
   session (which is what happened to `TSLA260713C00405000`) is a fee-and-spread grinder,
   not a strategy.
3. **Require stronger confirmation after a stop-out.** Re-entering 30 seconds after being
   stopped out is a bet that the thing that just went against you will now go for you.
4. **Watch expectancy, not P&L.** `win_rate × TP − loss_rate × SL`. If that number is
   negative, the strategy is broken no matter what today's P&L says — you are simply
   waiting for volume to prove it.

## The rule

> **Never deploy a strategy without computing `SL / (SL + TP)` first.**
> If your realistic win rate is below that number, the strategy is not "risky."
> It is *arithmetically guaranteed to lose*, and the only variable is how fast.

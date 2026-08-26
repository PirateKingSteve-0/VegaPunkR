# Negative Expectancy by Construction

*Written 2026-07-13. **Substantially corrected 2026-07-14** — see the correction notice below.*

---

## ⚠️ CORRECTION (2026-07-14): the measured numbers in the original were garbage

The original version of this doc reported a **31% win rate**, a **−1.08% mean per-trade
return**, and a **Sharpe of −0.146**, and concluded that the TSLA strategy was still
negative-EV after the fix.

**Every one of those numbers was computed from Tradier sandbox fills, and sandbox fills
are fabricated.** They are not a simulation of the market — they are disconnected from it.

Proof, from 2026-07-14: SPY's real tape at 10:34 ET was **752.02**, and the engine's
streamed price agreed (751.98). A **749 call** with SPY at 752 has **$3.00 of intrinsic
value**. Tradier sandbox priced and filled it at **$1.84–$2.14** — *below intrinsic*.
That cannot happen in a real market; it would be free arbitrage.

```
  time       SPY      strike   intrinsic   sandbox fill
  14:34:58   751.98    749       2.98        2.14     ← impossible
  14:35:39   751.87    749       2.87        1.93     ← impossible
  14:36:33   751.99    749       2.99        2.03     ← impossible
```

**What survives from this doc:** the *structural* finding. A stop wider than a target
needs a >50% win rate to break even. That is arithmetic, and it was real, and fixing it
was right.

**What does NOT survive:** every claim about how the strategy actually *performed*. We
do not know its win rate. We do not know its expectancy. **We do not know whether these
strategies are profitable, and we cannot find out in sandbox.**

---

## The one formula that matters (still true)

To break even, your win rate must satisfy:

```
                       stop_loss
  break-even win rate = ─────────────────────
                       stop_loss + take_profit
```

Two numbers you type into a form determine the win rate you must achieve before you make
a single dollar.

**What we were running on 2026-07-13:**

| Strategy | Stop loss | Take profit | Break-even win rate |
|---|---|---|---|
| TSLA 0DTE Scalping | 20% | 15% | **57.1%** |
| SPY 0DTE Scalping | 50% | 25% | **66.7%** |

The stop was **wider than the target** on both. To break even, TSLA had to be right 57%
of the time and SPY 67% of the time — before costs. That is a very high bar for any
signal, and it was baked in by two form fields.

**This is what "negative expectancy by construction" means:** the parameters, not the
market, determine the outcome. It is not bad luck and not a bug.

## The trap that hid SPY's 50% stop

`params_json` carried **two spellings of the same setting**, with different values, and
`signal_generator.py:355` reads `_pct` **first**:

```python
stop_loss_pct = params.get('stop_loss_pct') or params.get('stop_loss_percentage')
```

SPY had `stop_loss_pct: 50` **and** `stop_loss_percentage: 15`. The UI edits the
`_percentage` column. So:

- **The UI showed a 15% stop.**
- **The engine enforced a 50% stop.**

Nobody was lying. The screen simply was not showing the number being traded, and there
was no way to tell from the screen.

> **Two names for one setting is not a convenience. It's a bug waiting for a bad day.**

All four keys and both columns are now written together
(`scripts/fix_strategy_expectancy.py`). We deliberately did **not** delete the `_pct`
keys — `trading_safeguards.py:54` rejects any strategy whose `stop_loss_pct` is absent or
< 10. That validator is dead code today, but deleting the key would arm a landmine if it
is ever wired up.

## What we changed

Both strategies moved to **1:2 risk/reward — SL 15% / TP 30%**:

```
  break-even win rate:  15 / (15 + 30)  =  33.3%
```

| | Before | After |
|---|---|---|
| TSLA | SL 20 / TP 15 → 57.1% needed | SL 15 / TP 30 → **33.3%** needed |
| SPY | SL 50 / TP 25 → 66.7% needed | SL 15 / TP 30 → **33.3%** needed |

**Caveat added 2026-07-14:** the *specific* 15/30 numbers were chosen partly to sit below
an observed "31% win rate" that we now know was an artifact of fake fills. The
**direction** of the change is unambiguously right — a target wider than the stop. The
exact ratio should be revisited once we have real fill data.

---

## Why sandbox cannot evaluate a strategy

The engine **must** read live market data: Tradier's sandbox has no market-data
WebSocket, so quotes always come from the live endpoint. But orders **fill in sandbox**.
Those are two different price universes, and the engine straddles both:

```
  entry recorded  = sandbox fill        1.84
  exit evaluated  = live market price   3.49
  pnl_pct         = (3.49 - 1.84)/1.84  = +89.67%   →  "Take profit hit!"
  exit then fills = sandbox again       1.81        →  actually -1.6%
```

**The engine's logic is correct. The data is fake.** Take-profit and stop-loss fire on a
genuine comparison between two incompatible price worlds.

Measured across both sessions:

```
2026-07-13 (TSLA):  120 of 121 exits fired at a price we did NOT get.  mean gap $0.92
2026-07-14 (SPY) :   20 of  22 exits fired at a price we did NOT get.  mean gap ~$1.05
```

A "take profit hit: 89.67%" that realises **−1.6%**. A "stop loss hit: −15.58%" that
realises **+5.1%**. **Exits are effectively random.** Any win rate measured under these
conditions is a coin flip, and any expectancy derived from it is meaningless.

### What sandbox CAN test

Order placement, fill confirmation, reconciliation, the WebSocket streams, contract
selection and reselection, risk gates, and that nothing crashes. All of that is real, and
all of it was verified successfully on 2026-07-14.

### What sandbox CANNOT test

Win rate. Expectancy. P&L. Whether take-profit and stop-loss levels are well chosen.
**Whether the strategy makes money.**

---

## Where that leaves us

1. **The structural fix was right** and is done. A stop wider than a target is
   indefensible regardless of what the data says.
2. **We do not know if these strategies work.** The 31% win rate, the −1.08% expectancy
   and the "the signal is firing on noise" conclusion were all built on fabricated fills.
   They should not be cited.
3. **To actually find out**, you need one of:
   - **A backtester** against real historical option data (TODO **C1**) — the safe path.
   - **Live trading with minimal size** — real fills, real quotes, one consistent price
     universe. This is the *only* way to measure the strategy as-built, and it must not
     happen until there are **broker-side stops** (TODO #1).

## What we still know is true

- **Churn is real, and it's not a pricing artifact.** Median gap between consecutive TSLA
  entries on 2026-07-13 was **38 seconds**; 106 of 119 entries came within 90s of the
  previous one. The 5s rate limiter blocked **108 of ~233 attempted orders (46%)** — a
  governor pinned to the floor, not a safety margin. Timing data doesn't depend on fill
  prices.
- **Re-entering 30 seconds after being stopped out** is a bet that the thing which just
  went against you will now go for you. That's a design question, not a data question.
- **The exit-reason labels in `system_events` are unreliable** for any sandbox session,
  because the reason is chosen from the fictional pnl_pct.

## The rule

> **Never deploy a strategy without computing `SL / (SL + TP)` first.**
> If your realistic win rate is below that number, the strategy is not "risky" — it is
> *arithmetically guaranteed to lose*, and the only variable is how fast.

## The other rule (learned the hard way, 2026-07-14)

> **Never measure strategy performance in a sandbox whose fills you have not validated
> against the real market.**
> Check the simplest invariant first: **an option cannot trade below its intrinsic value.**
> Tradier's sandbox does. One line of arithmetic would have saved a day of analysis built
> on fiction.

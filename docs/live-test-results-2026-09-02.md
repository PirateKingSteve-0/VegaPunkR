# Live Test Results — Wed 2026-09-02

First real-money session. Account **6YB70356** (cash), prod DB, `APP_ENV=prod`,
`LIVE_TEST_LOGGING=1`. Logs in `logs/livetest-2026-09-02/`.

**Result: the session succeeded at what it was for.** It was never about P&L — it was about
getting one honest set of fills, because sandbox fabricates them and every price-derived number
from the previous five sessions was measuring that artifact rather than the engine.

---

## 1. The headline: exit pricing was never broken

Three sessions were spent hunting a bug in the exit path. There wasn't one.

| | sandbox 09-01 | **live 09-02** |
|---|---|---|
| exits mismatched (claimed vs realised) | 61/61 — **100%** | **0/3 — 0%** |
| median hold | 5.8 s | **859 s** (14 min) |
| round trips | 64 | **3** |
| phantom adoptions | 0 | **0** |
| P&L | −$95 | **+$143** |

Claimed and realised now agree to within a fraction of a point:

```
t2   claimed +25.08%    realised +25.7%     gap 0.6
t4   claimed +25.06%    realised +24.8%     gap 0.3
t6   claimed -15.20%    realised -15.5%     gap 0.3
```

On sandbox those gaps were 60–95 points. The engine read prices correctly the whole time; the
sandbox's invented fill prices (roughly half the real market) made every position look instantly
+90%, which is what produced the 5-second churn and the 100% mismatch.

**Consequence:** the stale-quote diagnosis of 2026-08-27 was wrong, and the exit-path guard
written to fix it addressed a problem that did not exist. See §5.

---

## 2. The three trades

All calls. SPY rallied; the put strategy armed once and never traded.

| # | contract | in | out | fill in | fill out | held | P&L |
|---|---|---|---|---|---|---|---|
| 1 | C00760000 | 10:00:10 | 10:06:49 | 3.27 | 4.11 | 6m39s | **+$84** |
| 2 | C00760000 | 10:07:27 | 10:21:46 | 4.23 | 5.28 | 14m19s | **+$105** |
| 3 | C00763000 | 11:15:52 | 11:48:21 | 2.96 | 2.50 | 32m29s | **−$46** |

Times ET. Trades 1 and 2 are the **same contract** — the engine took profit and immediately
re-entered. That detail matters; see F2.

Equity $1,060 → $1,202. Two winners of three.

---

## 3. Findings

### F1. The trailing stop is unreachable by construction *(structural bug)*

`prod` strategy 3 is configured:

```
trailing_stop = true    activation = 15%    distance = 10%    take_profit = 25%
```

`signal_generator.check_exit_signal` evaluates in a fixed order, each returning immediately:

```
1. take profit    (25%)   -> return
2. stop loss      (15%)   -> return
3. trailing stop  (activates at 15%)   <- unreachable
4. max hold time
```

The trail arms at +15% but take profit fires at +25% and returns first. **Any position that would
arm the trail is sold before the trail can act.** It has never executed and cannot at these
numbers. This is not a tuning preference — it is a configured feature that is dead code.

### F2. The flat 25% target burns scarce settled cash

Contract `C00760000` ran from 3.27 to a session high of **6.40** (~10:45 ET):

```
10:00   3.57
10:15   4.68
10:30   5.46
10:45   6.13    (session high 6.40)
11:00   5.53
```

What actually happened, versus one position with a working 10% trail (exit ≈ 6.40 × 0.90 = 5.76):

| | settled cash used | P&L | return on cash |
|---|---|---|---|
| actual: two 25% round trips | **$750** | +$189 | **25%** |
| one trailed position | **$327** | ≈ +$249 | **76%** |

*(An earlier verbal estimate of "left 56% on the table" was wrong — it ignored that the re-entry
captured a second 25% bite. The corrected figure is ~+$60 more P&L, which is modest.)*

**The real cost is not the P&L — it is the cash.** Those two round trips consumed $750 of settled
cash to earn $189. A single trailed position would have earned more using $327, leaving capacity
for further trades. On this account, settled cash is the binding constraint (F3), so an exit rule
that forces re-entry into the same move is expensive in the currency that is actually scarce.

### F3. Settled cash caps the account at ~3 trades/day

By 11:48 ET the account was done:

```
total_equity    $1,202.46
cash_available  $   13.46      <- settled
unsettled       $1,189.00
```

From 10:01 PDT onward the log is a wall of:

```
Preview failed for SPY: Tradier preview rejected:
  You do not have enough buying power for this trade.
```

**214 rejected previews** and **321 entry signals** for 3 executed trades. T+1 settlement on a cash
account: proceeds are unusable until tomorrow. Nothing is broken — `_preview_or_abort` refused
rather than submitting blind — but the engine spent five hours signalling into a wall.

**No GFV was incurred.** Every buy was funded from settled cash; the ledger reconciles to the
broker exactly:

```
start settled                     $1,060
t1 BUY  -$327   settled $733
t2 SELL +$411   settled $733   unsettled $411
t3 BUY  -$423   settled $310      <- from settled, not the $411
t4 SELL +$528   settled $310   unsettled $939
t5 BUY  -$296   settled $ 14      <- from settled
t6 SELL +$250   settled $ 14   unsettled $1,189   (broker: $13.46 after ~$0.54 fees)
```

Settled cash never went negative, so no purchase touched unsettled proceeds — the only way to earn
a Good Faith Violation. Rejected previews carry no penalty; nothing is submitted.

### F4. `order_cost_raw` on a SELL is NEGATIVE — TODO B1 answered

B1 flagged this as undocumented and said no exit-drift number could be trusted until it was known.
Live data settles it:

```
buys    +329   +424   +295
sells   -411   -530   -252
```

Magnitude is the per-contract cost; the sign encodes direction. Exit-drift figures can now be read.

### F5. Preview drift is negligible on live — reconsider TODO B2

All six previews:

```
buy   3.27 -> 3.29    +0.61%
sell  4.09 -> 4.11    +0.49%
buy   4.225 -> 4.24   +0.36%
sell  5.29 -> 5.30    +0.19%
buy   2.94 -> 2.95    +0.34%
sell  2.51 -> 2.52    +0.40%
```

Range **0.19%–0.61%**. On sandbox 08-27 it ran −9% to −12.8%, and earlier +20% to +83%. That drift
was *also* a sandbox artifact. B2 proposes a preview-drift cancel rule; on this evidence there may
be nothing to cancel. Do not build it until live data shows drift worth acting on.

### F6. The entry stale-quote guard never fires

Quote age at entry, across 321 signals:

```
280 x  quote_age=0s
 38 x  quote_age=1s
  3 x  quote_age=2s
```

Maximum observed: **2 seconds**, against a 30-second threshold. Zero `Stale stream quote ... at
entry` events. The guard is belt-and-braces, not load-bearing — streamed quotes stay fresh at
entry. Its silent-failure risk did not materialise.

### F7. The stop-loss exit — inconclusive, not clearly wrong

Trade 3 stopped at 2.50 (−15.5%). The contract recovered to 2.98 (high 3.13) by 12:00 — but was
back to **2.50 by 13:00**. So the stop exited at a local low that mean-reverted and then declined
again. It looks like a shakeout in the first twelve minutes and like a correct exit by the end of
the hour. **One trade proves nothing here.** Do not retune the stop on this evidence.

---

## 4. Suggestions, and what each would affect

Ordered by value. None should be made without a deliberate change and tests — every one of these
touches the exit path, which governs every position the engine holds.

### S1. Make the trailing stop reachable *(recommended, highest value)*

Two options:

**(a) Check the trail before the flat target.** Reorder so trailing is evaluated ahead of take
profit. Once a position is up 15%, the trail governs and the flat 25% only fires if price gaps
past it.

**(b) Raise `take_profit_pct` above the trail's useful range** (e.g. 60%), leaving the trail as the
normal exit and the target as a ceiling.

*Affects:* every exit the engine makes. Winners run further and exit lower than their peak;
average hold time rises; round-trip count falls; the settled-cash problem (F3) eases because one
position captures what previously took two. **Risk:** a position that reaches +15% and reverses
now exits around +5% instead of at +25% — this converts some current winners into smaller winners.
It is a real trade-off, not a free improvement, and (a) changes behaviour more aggressively
than (b). Prefer (b) first: it is a data change, reversible from the portal, and needs no code.

### S2. Treat settled cash as a first-class gate

The engine generated 321 entry signals and had capacity for 3. It should recognise it is out of
buying power and stop previewing, rather than rejecting 214 times.

*Affects:* log readability, broker request volume, rate-limit headroom. **No change to trading
behaviour** — those orders were already being refused. Low risk, purely additive. Note this is
adjacent to TODO A1's reservation ledger, whose probe still has never been run; today's protection
came from Tradier's check, not ours.

### S3. Do not build B2's preview-drift cancel rule yet

*Affects:* saves building a gate against a phenomenon (F5) that appears to be a sandbox artifact.
Revisit only if live drift exceeds a few percent.

### S4. Reconsider account funding before further strategy tuning

Three trades exhausted the account in under two hours. At ~$300/contract on $1,060 of settled cash,
that is the structural ceiling regardless of how good the strategy is. Any statistical read on
win rate needs far more samples than three per day.

*Affects:* not a code change — a decision about whether the next test measures the strategy or
measures the cash constraint again.

### S5. Leave the stop loss alone

*Affects:* nothing. Explicitly listed so it is not quietly retuned on F7's one ambiguous data
point.

---

## 5. Housekeeping from earlier sessions

- The **exit-path stale-quote guard** (landed 08-27) was written against a misdiagnosis, now
  disproven by §1. It is harmless but unearned, and it adds a REST call to the exit path. F6 shows
  the equivalent entry guard never fires either. Decide whether to keep either.
- `api/tests/test_stale_stream_quote.py` was deleted on 2026-09-01 and never restored — the
  exit-path guard currently has no test.
- `scripts/session_report.py` was reading `trades.price` on a sell leg as the exit fill; it is the
  entry price by design (`order_manager.py:1720`). Fixed 09-01. Any realised-% figure quoted from
  that script before then is wrong.

## 6. Still unverified after today

- **The halt (`ride` / `flatten`) never ran.** Still has never executed anywhere.
- **The trailing stop never ran** — and per F1, cannot.
- **The reservation-ledger probe (TODO A1) never ran.** Today's cash protection was Tradier's.
- **The put side never traded.** Strategy 4 armed `SPY260902P00766000` once at 08:15 and never
  entered; the day was a call day.
- **Exits under a fast adverse move.** All three exits today were orderly.

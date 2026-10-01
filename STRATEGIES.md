# STRATEGIES

Every strategy we run, and every strategy or filter idea we come up with along the way. **One line
each.** Detail lives in `BRAINSTORM.md` (reasoning), `TODO.md` (work) and `JOURNAL.md` (results). This
file points at them and does not repeat them.

**Status words:** `idea` (not measured) · `tape-tested` (measured on recorded prices, not built) ·
`shadow` (running live, but only recording) · `live` (placing real orders) · `rejected` (measured, did
not hold up, so don't re-run it without new data). When something changes status, edit its line in
place and add the date.

All times are ET. **R** is one risk unit: what the trade loses if the stop hits exactly. **bp** is a
basis point, 0.01% (about 8¢ on SPY at $768).

---

## Live

| # | Strategy | What it does, plainly | Record | Where |
|---|---|---|---|---|
| L1 | SPY 0DTE momentum, calls (strat 3) | Buys a same-day call when SPY is above its 9-min average and VWAP on a volume spike; 15% stop, 25% target, trailing stop, no entries after 11:30 | 12 trades, 4 wins, **−1.6R** | TODO G, E |
| L2 | SPY 0DTE momentum, puts (strat 4) | Mirror image of L1 for falling prices | 32 trades, 22 wins, **+12.5R** | TODO G, E |
| L3 | IWM 0DTE momentum, calls and puts (strats 5/6) | Same rules on IWM, don't-chase gate still on (1.0) | 4 trades, −1.1R; often finds no contract in its delta band | TODO G6 |

On the tape, L1 and L2's entry signal is a coin flip in both directions (31 sessions, 2026-09-26). The
profit so far comes from the 11:30 cutoff, the exit geometry and luck. Sample: 48 trades.

---

## Strategy ideas (not built)

| # | Idea | What it is, plainly | Status | Where |
|---|---|---|---|---|
| S2 | Pullback continuation | After a push, enter when price turns back off the 9-min average, not merely while it's above it | idea | BRAINSTORM "Entry is a state, not an event" |
| S3 | VWAP reclaim | Trade the moment price *crosses* VWAP, not the whole time it sits on one side | idea | same |
| S4 | Prior-day levels | Yesterday's high/low/close and the pre-market range as places price stalls or breaks | idea (data already recorded) | TODO G4c |
| S5 | Fade the flush | After a big fast drop (or rise), bet on the snap-back instead of the continuation | rejected for now: snap-backs of 13–23¢ vs a stop needing ~74¢. Re-check only for flushes over 2 typical moves | BRAINSTORM "VWAP distance" |
| S6 | Expiration-day pinning | Near the close on big expiration Fridays, price drifts toward strikes with huge open interest | idea; needs the option-chain collector | TODO C1 |
| S7 | Single-stock same-day options (TSLA etc.) | Same momentum rules on a stock with Mon/Wed/Fri expirations, same-day contracts only | idea. Record-only first (`max_position_size_usd: 1`); contracts may be too expensive for the account | chat 2026-09-25 (not yet in TODO) |
| S8 | Failed breakout | Price breaks out of the opening range, then closes back inside within 5 min; trade toward the other side | **idea, rule declared 2026-09-27 before looking.** Hint: 15-min-range breakouts kept going only 42% at +30 min | X8 re-test, 2026-09-27 |

---

## Filters to try on existing strategies

| # | Filter | What it checks, plainly | Status | Where |
|---|---|---|---|---|
| F1 | Trend day vs choppy day | Only trade when the morning is moving in a line, not back and forth | idea with a hint: smoother half of 16 days +9.3R, choppier half +1.4R (weak, correlation 0.13) | TODO E12 / G4d |
| F2 | Near the day's low or high | Skip puts right at the day's low, calls right at the high | tape-tested: 2–3 bp worse, same in both halves, **not beyond noise**; opposite in live trades. Watch | 2026-09-27 |
| F3 | Last 10 min moved the other way | Skip a put if SPY rose over the last 10 min (Friday 10:28 loss) | **idea, declared 2026-09-27 before looking** | 2026-09-27 |
| F4 | Volume vs normal for this time of day | Compare volume against the usual for this clock minute, not the last 20 minutes | tape-tested defect (gate loosest late, tightest early). Not fixed | TODO G4a |
| F5 | SPY, QQQ and IWM agree | Trust a move more when all three move together | idea | chat 2026-09-26 |
| F6 | Candle shape | Where the minute closed within its range, body size, rejection wick near VWAP | idea | chat 2026-09-25 |
| F7 | `$TICK` breadth | Is the whole market pushing, or just SPY? Setting exists but nothing feeds it data | half-built | TODO G4 note |
| F9 | Chart shapes as context (double bottom/top) | **Skip a put if the day's low was tested twice and held (within ~10¢) in the last 30 min**; mirror for calls. Shapes describe the day, not buy triggers. Friday 09-25 10:28 put was bought after exactly this. Swing points already detected by exit shadow's structure stop | **idea, rule declared 2026-09-27 before looking.** Test after the cost breakdown | chat 2026-09-27; TODO K1 (labelling UI) |
| F8 | Order-flow divergence | Buyers push but price falls (or the reverse), so expect a snap back toward the push | 2 of 32 checks passed, category added after looking, **untrusted**. Re-run at ~20 sessions | 2026-09-26 |

---

## Rejected (measured; don't re-run without new data)

| # | Idea | Why it was rejected | When |
|---|---|---|---|
| X1 | Don't-chase gate on SPY (block if stretched over 1 wiggle from VWAP) | The trades it blocked were the best ones: +$412 blocked vs +$21 allowed | removed 2026-09-23; re-checked 2026-09-26 |
| X2 | Higher delta for SPY calls | Higher delta did worse on 12 trades; distance in the money made no difference | 2026-09-26 |
| X3 | Avoid Fridays | −$177 over 12 trades is chance (38% by shuffle), and Fridays aren't choppier | 2026-09-26 |
| X4 | Order flow: confirmation, absorption, air pocket | None predicted the next 15–30 min over 8 sessions | 2026-09-26 |
| X5 | Exhaustion (skip after a big 10-min move) | Backwards: big moves continued slightly (63% right) | 2026-09-27 |
| X6 | Breakeven stop after +5–12% | Flips between halves of the sample; noise | 2026-09-26 |
| X7 | Block the middle, allow extreme stretch | Held in one half of one instrument only | 2026-09-23 |
| X8 | Opening-range breakout (S1) | 31 days, each breakout counted once: kept going 53–58%, avg +0.2 to +0.4 bp vs 3.2–4.1 bp break-even (4–6% chance it clears it); 15-min range negative. The early +3.69 bp came from 4 days and from counting every minute beyond the range | 2026-09-27 |

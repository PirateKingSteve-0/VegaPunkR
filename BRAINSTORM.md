# BRAINSTORM

Open questions, options weighed, and decisions that shaped a design — the reasoning that would
otherwise be lost between sessions.

`TODO.md` is what we intend to build. This is why it looks the way it does. Keep entries short;
once something becomes work, it moves to `TODO.md` and this keeps only the decision.

---

## The strategy view should render the gate chain, not the form *(2026-09-14)*

**Decision: build the flowchart view READ-ONLY and LIVE — every gate between a tick and an order,
each carrying its current state. Not a second editor. Node list derived from the engine, never
hand-drawn.** Prompted by *"a engine/strat tray or page ... we can make the edits for strats
there"*. Related: TODO.md G3/G4 (the questions this view exists to answer),
`strategy-form.component.html`.

### Why not editable

A second editor means the same `params_json`, the same validation and the same role gates
maintained twice — double the surface for no new capability, and the eight-section form already
does it. Worse, the gates that matter most are not strategy params: daily loss cap, position size
cap, role and trading window live on the `User` row. The form already separates these ("Engine
Settings — read-only, account-wide"); a flowchart would render them inline and visually identical
to editable nodes, which is the trap.

### Live state is the whole point

A static chart is a prettier form. A chart carrying per-node state — passed / blocking / warming /
unreachable — answers the question this project keeps hitting: **why didn't we trade?** Today that
means grepping DEBUG logs that are not enabled. Pre-open on 09-14 it would have shown both sides
unarmed on open interest, the volume baseline still filling until ~09:50 ET, and — permanently —
that `$TICK` is fully implemented at `signal_generator.py:489` yet unreachable, because
`to_market_data()` never supplies `tick_value`.

### The scope trap: ~20 gates, not 8

`check_entry_signal` is cleanly numbered 0–7 and is tempting to render alone. It is about a third
of the chain, which also spans `stream_driven_worker` (market open, armed contract, delta drift,
eval throttle), `strategy_executor._check_entry_signals` (active, max_positions, re-entry cooldown,
option price) and `order_manager.execute_signal` (role, daily loss cap, size cap, settled cash +
reservations, preview-or-abort, throttle). Rendering only the middle third omits the gates that
actually stop trades — the loss cap latched 09-11 11:59 ET; OI starvation left both sides unarmed
overnight 09-13.

### Derive it, do not draw it

A hand-maintained chart of a live engine is wrong within a month, and a wrong chart here is a
liability. Nodes come from a gate registry the engine itself reads, so adding a gate adds a node.
Sequencing: block reasons must be observable first — they log at DEBUG and the engine runs at INFO
— which is small, useful on its own, and a prerequisite either way. No graph library in the UI
today (chart.js, lightweight-charts only); hand-rolled SVG over pulling in dagre/mermaid for this.

---

## The cost budget comes before the signal search *(2026-09-14)*

**Decision: a candidate signal is rejected on arithmetic before it is measured on tape, by
comparing its plausible effect size against the move the contract needs to break even. Applied to
the four candidates above, the budget disqualifies the search as currently framed — not the
individual signals.** Prompted by *"how does someone even begin to understand what works
mathematically?"* Related: the section above (this reverses its order of operations), TODO.md G3/G4,
`docs/negative-expectancy.md`, `docs/live-test-results-2026-09-02.md` F3.
Calculator: `scripts/cost_budget.py` (stdlib only, no DB, no network).

### Why this inverts the method above

That section's rule — measure on the tape before building — is right and stays. What it does not do
is tell you what result would be *good enough*. ORB measured +3.69 bp and the section could only say
it "does not clear ORB for building" against a one-contract estimate of ~9.7 bp. The budget makes
that threshold a computed number for every hour and every delta the gate allows, so a candidate can
be ruled out in five minutes instead of twenty, and — more usefully — so can a whole strategy shape.

Black-Scholes, r=0, solved by bisection rather than by a linear delta approximation because 0DTE
gamma over a 30-minute hold is not small. Calibrated to the one real fill we have: SPY 2026-09-02,
strike 760, filled 3.27 at 10:00 ET under a delta gate of >=0.60. IV near 35% annualised reproduces
that premium. **Cross-check: the model returns 10.36 bp where the hand estimate said ~9.7 bp.**
Conclusions are insensitive to +/-20% on IV, and very sensitive to delta and to time of day.

### Two budgets, not one — conflating them is what made 9.7 bp hard to act on

- **Breakeven room** — the favourable move needed to cover round-trip spread plus decay. Below it
  the trade loses *even when the direction call is right*.
- **Stop room** — the adverse move that fires the percentage stop. This decides whether the stop is
  measuring the signal being wrong, or measuring noise.

The second one is where the strategy dies, and it was never being computed.

### The stop sits inside the noise in every configuration

SPY's 1-sigma move is **26.4 bp over 30 minutes** and **18.1 bp over 14 minutes** (IV 35%). Against
that, a 15% premium stop, and how often a driftless random walk alone touches it:

| delta | hold | stop room | in sigma | P(stopped by noise) |
|---|---|---|---|---|
| 0.60 | 30m | 10.36 bp | 0.39 | ~100% |
| 0.70 | 30m | 12.79 bp | 0.48 | 99% |
| 0.70 | 14m | 13.92 bp | 0.77 | 84% |
| 0.85 | 30m | 16.86 bp | 0.64 | 94% |
| **0.85** | **14m** | **17.58 bp** | **0.97** | **65%** |

All at 10:00 ET, the most favourable hour. **The best cell in the entire grid is stopped out by
noise about two thirds of the time.** The measured edge is 3.69 bp = **0.14 sigma** over 30 minutes.
A signal worth 0.14 sigma cannot survive a barrier at 0.39-0.97 sigma: the exit is driven by
Brownian motion, not by the signal.

**This is the mechanism behind the eight flat parameter sweeps.** Entry window, forced-exit, stop,
trail, target, cooldown, loss-cooldown, trades-per-day all landing between -1% and -3% is what it
looks like when exits are noise-triggered — the knobs move *which* noise stops you, never *whether*
it does. The sweeps were not underpowered; they were measuring a random walk.

### After about 14:00 ET the trade is arithmetically dead

Decay over a 30-minute hold, against a 15% stop:

```
  delta 0.60/0.70, 30m hold
  ET      decay %prem    stop room
  10:00       1.9-2.9      +10.4 to +12.8 bp
  13:00       3.7-6.7       +4.8 to  +7.8 bp
  14:00       6.6-9.6       +2.5 to  +4.4 bp
  15:00         17.9              -0.92 bp     <- decay alone exceeds the stop
  15:30         28.5              -2.48 bp
```

**Negative stop room means the position needs a favourable move just to avoid being stopped out by
the clock.** At 15:30 a delta-0.60 contract held 30 minutes loses 28.5% of premium to time while the
stop sits at 15%. The exit fires on the calendar and gets labelled a stop-loss. Every win rate,
expectancy and exit-reason statistic gathered from late-session trades is measuring the passage of
time.

**This compounds with candidate 1 above, exactly backwards.** That finding is that
`min_volume_multiplier` is *loosest* into the close — a typical 15:45 minute scores ~2.2x with no
spike at all. So the gate opens widest at precisely the hour where the stop is guaranteed to fire on
decay. Two independently-found defects pointing the same direction, and the per-clock-minute volume
profile fixes only one of them.

### The breakeven margin is smaller than the error bar on the measurement

```
  delta 0.70, 10:00 ET, edge 3.69 bp
  30-minute hold:  breakeven 4.11 bp  ->  margin -0.42 bp   (loses)
  14-minute hold:  breakeven 3.18 bp  ->  margin +0.51 bp   (wins)
```

**The sign of the expectancy flips on the hold period**, and neither margin exceeds 0.51 bp. With an
effective sample of 4 sessions — the 105 breakouts are clustered by day, not independent — the
uncertainty on the 3.69 bp is far wider than 0.5 bp. ORB is therefore not "marginal". It is
**unmeasurable at this sample size**, and its apparent viability is being decided by
`max_hold_time_minutes` rather than by the signal. Confirming a 3.69 bp effect against a ~4 bp
threshold needs on the order of 600 independent breakouts, which at day-level clustering is
70-115 sessions.

### What the budget says to do instead

**1. Raise `delta_min`.** Deeper ITM improves every axis that matters, because a percentage stop on
total premium corresponds to a larger underlying move once most of the premium is intrinsic:

| | delta 0.60 | delta 0.85 |
|---|---|---|
| decay, 14m at 10:00 | 1.3% | **0.4%** |
| stop room | 11.81 bp | **17.58 bp** |
| P(stopped by noise) | 93% | **65%** |
| premium per contract | $3.89 | $7.57 |
| stop room at 15:30, 30m | **-2.48 bp** | **+2.06 bp** |

`delta_max` is already 0.85, so this is a floor change inside the existing gate, not a new gate. The
cost is real and lands on the binding constraint: ~$7.57 vs ~$3.89 per contract roughly halves
trades/day on an account F3 already caps at about three.

**2. Recognise that a long option already has a stop.** Max loss is 100% of premium, known at entry.
A 15% premium stop replaces that bounded, free, noise-immune stop with a barrier at 0.4-0.9 sigma
that pays the spread every time it fires. The reason to buy an option rather than shares *is* the
built-in stop; a tight premium stop discards it and pays for the privilege.

**3. The bind this exposes is capital, not signal.** `risk_per_trade_pct: 1.5` on $1,060 equity is
$15.90. One delta-0.70 contract at 10:00 ET costs ~$522, and a 15% stop on it risks $78 — **4.9x the
configured per-trade risk**, and 7.4% of equity. The 09-02 fills confirm one contract was the actual
size (+$84 on 3.27->4.11). So `risk_per_trade_pct` is not being enforced and cannot be at this
account size: the minimum position is one contract, and one contract is half the account. Removing
the stop to stop paying the noise tax requires sizing for a 100% loss, which this account cannot do
on a $522 contract. **That is a structural conflict between account size and instrument, and no
entry signal resolves it.**

### Landmine found while calibrating — needs a decision, not an edit

`api/strategy_templates.py` still ships **SPY at SL 50 / TP 25** (break-even win rate **66.7%**) and
**TSLA at SL 40 / TP 30** (**57.1%**). `scripts/fix_strategy_expectancy.py` moved the *prod rows* to
15/30 on 2026-07-13, but the templates were never updated — so any strategy created from a template
today is born with the exact defect `docs/negative-expectancy.md` was written about, and the doc's
rule ("never deploy without computing SL/(SL+TP) first") is silently violated by the default path.
Not changed here: it is a trading-parameter change and needs sign-off. Should become a TODO item.

### The rule this produces

> **Compute the breakeven move and the stop-room-in-sigma before measuring a signal, not after.**
> A signal worth less than ~0.3 sigma of the move its stop must survive cannot be rescued by
> tuning the entry, because the exit is being decided by noise either way.

---

## Candidate entry signals — measure on the tape before building *(2026-09-11)*

**Decision: no new indicator gets built until it has been measured against the recorded SPY tape
first. Four candidates scoped, one already disqualified by measurement, one already half-built.**
Prompted by *"are there other signals option momentum traders use to increase their chance of
success?"* Related: the ORB section below (this supplies evidence it asked for), TODO.md G3, G4,
E12, and `docs/REGIME_FILTER.md`.

### Why the method is the decision

Eight parameter sweeps over 118 replayed round trips — entry window, forced-exit time, stop, trail
distance, target, cooldown, loss-cooldown, trades-per-day — all land between **−1% and −3%
expectancy per trade**. Nothing on the exit or throttle side moves the result, which is what pointed
at the entry.

Then the entry itself, measured on the underlying where no option quotes are needed and the
stop/target geometry cannot flatter it (1,010 signal-minutes, 4 prod sessions, deduped per minute):

| Rule | right at +15m | right at +30m |
|---|---|---|
| Current (9EMA + VWAP + volume) | 45.6% | 43.0% |
| — calls only | 48.6% | 47.0% |
| — puts only | 42.7% | **39.1%** |
| *Baseline — long at any minute* | *51.0%* | *50.6%* |
| **Opening range breakout (09:30–10:00)** | **58.1%** | **59.0%** |

Below a coin flip, and below simply being long. **Caveat that governs every row: all four sessions
drifted upward**, which flatters anything bullish and punishes the put side. A meaningful share of
the 39.1% is direction of tape, not signal quality.

The tape test costs ~20 minutes per candidate, needs no engine change and no money. Building first
and measuring later is what produced a strategy whose three gates test below a coin flip.

### Evidence this supplies to the ORB section below

That section asks Phase 1 to answer *"how often does SPY break its 15-minute range, and does it
follow through."* Partially answered already, at a 30-minute range rather than 15: **105 breakouts
over 4 sessions, 59.0% right at +30m, average move +3.69 bp in the break's favour against +0.77 bp
for the tape itself.** The confidence interval excludes zero — the only candidate measured so far
that does.

It does **not** clear ORB for building. +3.69 bp is smaller than the ~9.7 bp SPY move a 15% stop on
a morning contract needs, and smaller than one typical minute of drift at that hour. A real
directional signal that still cannot pay for the stop, the spread and decay is not yet a strategy.
The 15-minute range and the close-vs-touch distinction both still need measuring.

### The four candidates

**1. Relative volume by time of day — a measured defect, not a hypothesis.** SPY volume is a deep U:
median 97,052/min at 09:30, **33,950 at 12:30** (35% of the open), **122,316 at 15:30** (3.6× the
lunch rate). `min_volume_multiplier` divides by a *rolling* 20-minute baseline, which tracks the U on
flat stretches but lags it on the steep ones. Into the close the baseline trails the ramp, so a
typical 15:45 minute scores **~2.2× with no spike at all** and clears a 1.5× gate on nearly every
minute of the last half hour; at the open the reverse suppresses ratios. **The gate is loosest late
and tightest early — backwards**, since late is when contracts are cheapest and the fixed percentage
stop sits deepest in noise. Two effects compounding the same way. Fix is a per-clock-minute volume
profile rather than a trailing window. Testable on the 8 sessions already on disk.

**2. Distance from VWAP, not side of it.** The gate is binary. A penny above VWAP and 2% above it
pass identically, though they are opposite situations — noise oscillating around the line versus a
genuine extension. 2026-09-10 spent 97.6% of the post-10:20 session blocked on this gate with price
**$0.58** above VWAP. Standard treatment is bands at multiples of the session's price dispersion.
Measurable from the replay without new data: record distance-in-sigma at entry, bucket outcomes.

**3. Prior levels.** Yesterday's close, overnight high/low, pre-market range, opening range. Partly
self-fulfilling — enough participants watch them that price genuinely stalls or accelerates there.
ORB is already one member of this family and the only one tested. **The data is already on disk**:
stream logs start well before the open (the 09-08 file has quotes from 02:21 ET), so overnight and
pre-market are captured. Same measurement shape as the ORB test.

**4. Higher-timeframe agreement.** Already specified in `docs/REGIME_FILTER.md`; `check_market_regime`
ships on every strategy and is read by nothing (E12). Would have silenced the put side for most of
the measured week, and the put side is where the losses were. **This is the candidate most likely to
be fooled by this sample** — four up-drifting days is exactly the tape where a trend filter looks
brilliant by construction. Needs a down-tape stretch before it means anything.

### Already half-built, worth knowing before adding anything new

`$TICK` — the gate is **fully implemented** at `signal_generator.py:489` (`use_tick_indicator`,
`tick_threshold: 800`, `tick_direction`), but `StrategyMarketState.to_market_data()` never supplies
`tick_value`, so the branch is unreachable even when switched on. Half a feature with no note saying
so. $TICK counts NYSE up-ticks minus down-ticks and is the classic breadth confirmation for exactly
this kind of trade — but Tradier's stream does not carry it, so the missing half is a data feed, not
a few lines.

### What is deliberately NOT on this list

**Implied volatility.** It matters more than any of the four — this book only ever *buys* options, so
a fall in expected movement costs money even when the direction call is right, and it can never work
in our favour the way it would for a seller. Left off because measuring it needs option-chain
snapshots through the session, which is a data-collection project rather than a tape test. Worth
raising once the four above are settled.

---

## Opening-range breakout — what it would cost to actually run one *(2026-09-09)*

**No decision. Scoped only, nothing built.** Prompted by *"how hard would it be to set up an ORB
setup in our system?"* Directly downstream of the section below, which names opening-range breakout
as one of the three things momentum traders do that this engine cannot express. Related: TODO.md D2;
`docs/TRENDLINE_STRAT_GAMEPLAN.md` is the format a build plan would take.

The strategy in plain terms: for the first 15 minutes after the open, buyers and sellers argue and
price bounces inside a narrow band — the *opening range*. Mark its high and its low. If price later
pushes clean out of the top, buy; out of the bottom, buy puts. Those two edges stay the reference
lines for the rest of the morning — the stop goes back inside the band, the target is one or two
band-heights beyond it.

### Adding a strategy is not adding a code path

Nothing dispatches on `strategy_type`. It is metadata, read only by two "is this options?"
heuristics (`trading_safeguards.py:79`, `models.py:135`). All behaviour comes from `params_json`
keys consumed by `SignalGenerator`, and the strategies router **merges** `params_json` on update
rather than overwriting it (`routers/strategies.py:290-296`), so keys the UI form does not know
about survive an edit. A new strategy is therefore new keys plus one more gate block in an existing
chain — no migration, no model change, nothing near order placement.

### What already exists

- `entry_after_open_minutes` already expresses "no entries before 9:45 ET", and already composes
  with the account trading window as most-restrictive-wins.
- `get_timesales()` (`tradier_integration/client.py:562`) already fetches 1/5/15-minute intraday
  bars. Written, tested, unused by the engine.
- `StrategyMarketState` already accumulates `session_high`/`session_low` off the underlying trade
  stream, and `_vwap_accumulators` (`signal_generator.py:687`) is the working precedent for a
  per-symbol value that resets on the ET trading day.
- `resolve_direction()` already handles "break up → calls, break down → puts".
- Contract selection, sizing, preview, order placement and reconcile are untouched by any of it.

### The two things genuinely missing

**1. There are no bars in the live path.** The engine is tick-driven: `check_entry_signal` fires on
every trade event and has no notion of a bar ending. But the whole difference between a real
breakout and a fake one is whether price *closed* above the line or merely *touched* above it —
price pokes its head out, closes back inside, and slides. Touch-only is the version of this strategy
that loses money. "Close above" means synthesising 1-minute bars from the stream, or polling
timesales each minute and confirming off that. Neither is hard; neither exists.

**2. Every exit is a percentage of the option's premium, not a level on the underlying.**
`check_exit_signal` receives the held *contract's* price (`strategy_executor.py:562`), and there is
a pointed comment at `strategy_executor.py:550` saying why: marking a position against the
underlying inflated unrealised P&L by ~100x and the daily-loss gate read it as real. So the stop
this strategy is built around — *underlying back inside the range* — has nowhere to live, and
neither does a target of "range high plus two band-heights".

This is point 2 of the section below reached from the other direction: **the stop is a price level,
not a percentage**, and that is a property the exit path does not have for any strategy today.
Adding it means feeding the underlying price into the exit path as a *separate* field — never
reusing `current_price` — plus new exit branches. A signature change in the exit path needs a
written plan and explicit sign-off, not an in-session edit.

### The shape if it gets built

**Phase 1 — breakout as an entry trigger only, ~1 day, exit path untouched.** A new opening-range
module: `get_timesales()` as the primary source, stream accumulation as fallback. Stream-only is not
enough on its own — a worker restarting at 9:50 would compute a range from partial data and never
say so, which is the quiet-wrong-answer failure. Then one gate block in `check_entry_signal` reading
`use_opening_range`, `opening_range_minutes`, `orb_breakout_confirm` (`close`|`touch`) and
`orb_buffer_pct`, composing as most-restrictive-wins like every gate around it. Existing premium
stop-loss / take-profit / trailing / time exits stay exactly as they are. Four new UI fields.

**Phase 2 — underlying-level stop and target, plus bar confirmation. ~3–5 days.** Touches the exit
path, so `engine-guard` on the diff. Only worth starting if Phase 1's entries measure well.

Phase 1 exists to answer one question cheaply: how often does SPY break its 15-minute range, and
does it follow through. E11's thresholds govern that read as they govern everything else, and dev
fills are fabricated — so the answer has to come from prod or from replayed timesales, never from
sandbox round trips. Branch when it starts: `feature/orb-strategy` off `dev`.

---

## Entry is a state, not an event — and the strike roll is where it costs *(2026-09-09)*

**Decision: the re-entry lever is the strike roll, not a blanket cooldown. Record it; build nothing
until n grows.** Related: TODO.md G1, G2, D2, and the corrected re-entry bullet under FUTURE
CONSIDERATIONS.

Prompted by the question *"we can exit a successful trade and enter back in at a place that might
not be fruitful even if the signals look right — is that real?"* It is real, and the prod tape says
the cost is concentrated somewhere more specific than "re-entry".

### The engine has no notion of a setup

`price_above_9ema_and_vwap` (strategy 3) and `price_below_9ema_and_vwap` (strategy 4) describe a
**state**, not an **event**. The condition can hold for hours, so the instant a position closes the
condition is still true and the engine buys again. It is not re-entering because something new
happened — it is re-entering because nothing changed.

Measured on prod, the span over which the engine kept *attempting* entries after its last executed
trade of the day:

| Day | Last fill (ET) | Still attempting until (ET) | Executed | Blocked attempts |
|---|---|---|---|---|
| 09-02 | 11:15 | **15:43** | 3 | 450 preview-rejects + 141 throttles |
| 09-04 | 11:07 | **15:44** | 3 | 478 + 175 |
| 09-08 | 10:25 | **15:41** | 3 | 98 throttles |
| 09-09 | 11:01 | **13:39** | 3 | 53 throttles |

On 09-02 the engine wanted to hold a position essentially continuously from 10:22 to 15:43 ET —
**5h21m** — and took 3 trades. **Settled cash and the 5-second throttle chose which 3; the strategy
did not.** That is why the question has never been properly tested: T+1 cash has been doing the job
a setup rule should be doing, which also means removing the cash constraint (funding, per E2b) would
*expose* this rather than fix it.

### What the 14 prod round trips say

2026-09-02 → 09-09, live money, the only trustworthy fills we have. Net **+$319**, 8W/6L.
Exit mix: 2 take-profit, 6 stop-loss, 6 trailing stop.

The obvious cut says almost nothing — first-trade-of-day made +$157 over 5, re-entries +$162 over 9.
The cut that separates is **whether the engine had to pick a different contract**:

| Bucket | n | Record | P&L |
|---|---|---|---|
| First trade of the day | 5 | 4W-1L | **+$157** |
| Re-entry into the **same contract** | 6 | 4W-2L | **+$309** |
| Re-entry on a **newly selected strike** | 3 | **0W-3L** | **−$147** |

All three strike-roll re-entries lost, on three different days, on both sides of the chain:

| Day | Rolled | After | Entry | Result |
|---|---|---|---|---|
| 09-02 | C760 → **C763** | SPY rallied, C760 ran 3.27 → 5.28 | 2.96 | −$46 |
| 09-08 | P773 → **P769** | SPY fell, P773 ran 5.72 → 6.27 | 2.72 | −$39 |
| 09-09 | P769 → **P766** | SPY fell, P769 ran 5.36 → 5.79 | 2.64 | −$62 |

### Why the roll is late by construction

The roll is not random — it is the delta band firing. After a winning move the held contract goes
deep in the money (its price now tracks the underlying nearly 1:1), delta climbs past the 0.85
ceiling, and `_select_option_contract` reaches for a strike that sits back inside 0.60–0.85. That
strike is always further along the direction price **just travelled**, at roughly half the premium.
So the engine buys a cheaper contract that only pays if SPY continues by about as much again, at the
point of maximum extension. In plain terms: it buys the continuation of a move that already
happened.

The captured excursion says exactly that. Both roll entries with MFE data peaked around +10–11% and
never reached the +15% that arms the trailing stop, then reversed into the stop:

| Trade | Best point (MFE) | Armed trail? | Outcome |
|---|---|---|---|
| 09-08 P769 (roll) | +11.4% | no | −14.3% |
| 09-09 P766 (roll) | +10.2% | no | −16.7% |
| 09-08 P769 (same contract) | +22.8% | yes | +13.4% |
| 09-09 P766 (same contract) | +59.4% | yes | +43.8% |

Same contract, minutes apart, opposite outcome — the difference is *when in the move* the entry
happened, which is the thing the entry rule does not look at.

This is the same geometry as E7 from the other side. E7 found the open-interest floor starves
whichever side is counter-trend; this finds the delta band pushes the strike downstream of a
completed move. Both are the contract selector reacting to price history rather than to a setup.

### What momentum day traders do instead

There is no single canonical strategy, but the common ones — opening-range breakout (mark the first
5/15/30 minutes' high and low, trade the break, one long and one short per day at most), pullback
continuation (wait for a push, enter on the *turn* back off the 9 EMA, not on being above it), VWAP
reclaim (trade the crossing of the day's volume-weighted average price, not the whole time price is
on one side) — share three properties this engine does not have:

1. **The entry is a moment, and it is consumed.** A momentum trader thinks in swings: find one, take
   it, done. A second entry needs a second setup — a fresh higher low, a break of the prior high, a
   new pullback that holds. Our engine re-evaluates a boolean every tick and has no memory that it
   already traded this move.
2. **The stop is a price level, not a percentage.** The stop goes where the *idea* is wrong (under
   the pullback low, back inside the opening range) and size follows from that distance.
   `stop_loss_pct: 15` is 15% of the option's premium — a distance chosen by the contract's price,
   unrelated to where the trade thesis fails. On a 0.60–0.85 delta SPY contract it is roughly
   0.3–0.6 SPY points, inside ordinary intraday noise. It fired on 6 of 14 exits.
3. **The payoff is meant to be lopsided.** Momentum earns on a handful of trending days and bleeds
   the rest — a few large winners paying for many small losers (*positive skew*). Capping the winner
   is therefore the expensive mistake. E1 already moved the right way and the tape shows it: the two
   largest wins, **+51.5%** and **+43.8%**, were both trailing-stop exits the old flat +25% target
   would have halved.

### What this says about D2

D2 (automatic daily profit target) would have helped on this data. A target near +$150 stops 09-02
after +$189 and 09-04 after +$167, saving the −$46 and the −$71 — roughly +$436 instead of +$319.

But look at *which* trades it saves: the 09-02 strike-roll re-entry, and the 09-04 same-contract
re-entry bought at 4.57 after selling at 4.50. **A re-entry rule catches the same two trades and
names the cause.** D2 catches them by proxy — it stops because you have made enough, not because the
entry is a chase.

D2 also carries a live failure mode visible here: on 09-09 the account was **−$19 on the day** before
the final trade made **+$126**. A target-based halt can only ever end a day early, and the largest
single trade in this dataset was the last one taken.

So D2 stays worth building and stays **second**. It bounds the day; it does not improve entry
quality, and at ~3 entries a day of settled cash the binding question is not "have I made enough
today" but "is this a fresh setup or a continuation of one I already took".

### The evidence limit — read this before acting on any of the above

n=14 round trips, of which the losing bucket is **n=3** and the winning bucket's +$309 is carried by
two trades (+$153, +$126). This is a strong-shaped anecdote, not a measured effect. It is worth
building around because the mechanism is legible and matches theory — not because the sample settles
anything. E11's thresholds (~62 round trips for a first read, ~126 for a confident one) still govern.

Everything here is prod only. Dev is sandbox and its fills are fabricated; the 2026-09-08 journal
already retracted a re-entry finding built on dev for exactly this reason, and that retraction stands.

### The one thing this does change now

TODO's long-standing "add a re-entry cooldown after a stop-out" is **the wrong lever on this data**.
A blanket cooldown blocks the +$309 bucket along with the −$147: five of the six same-contract
re-entries came back within 90 seconds, including the +$153 and the +$126. The narrow version —
pause only when the *contract changes* — hits all three losers and none of the winners.

Cheapest testable shape when the time comes: after a strike roll, require price to re-establish the
setup before arming (minimum version: a touch back to the 9 EMA). It is an entry gate in
`stream_driven_worker`, so it composes as most-restrictive-wins, only ever removes trades, and must
let `side='sell'` through untouched.

---

## Storing the broker-confirm PDFs — S3, or nothing? *(2026-09-07)*

**Decision: store no PDF bytes.** Related: TODO.md I2.

Cost was never the issue. Confirms are ~350 KB, one per trading day — 90 MB/yr, about **$0.03/yr**
on S3 Standard in us-west-1, ~$0.26/yr after a decade. It never becomes a line item, and we already
run RDS in that region so S3 is not a new vendor.

S3 *is* the standard pattern for documents (blob in object storage, metadata row in the DB; never
large binaries in Postgres). The reasons not to here:

- **PII surface.** Confirms carry name, home address and account number. A bucket means a policy,
  public-access blocks, encryption config and an IAM credential that all have to stay right forever.
- **Second copy of something that already has a custodian.** Apex and Tradier retain these; the
  portal is the archive. We would be duplicating a re-downloadable file.
- **We do not serve documents back.** S3-for-PDFs is standard when the job is "let the user retrieve
  their files". Here the PDF is an input to a parse, not an asset.

**Open — the one real counter-argument: re-parseability.** Without the bytes, a parser fix means
re-uploading. Cheaper answer than a bucket: keep the extracted *text* (~4.9 KB per confirm, ~1.6 KB
gzipped, **~0.4 MB/yr** in Postgres) as a `source_text` column on `BrokerDocument`. Full re-parse
capability, no object storage, and stripping the cover page drops the name and address before
anything is written. Not yet adopted.

---

## Economic-event awareness — not a news feed, and not a day flag *(2026-09-07)*

**Decision: an economic-event calendar with per-release timestamps. Report-only. Morning summary at
09:00 ET *and* per-event logging through the session.** Supersedes the news-outlook sketch in TODO.md.

### Why a calendar, not a news feed

Two unrelated things get called "news":

- **Scheduled events** — CPI, PPI, NFP, FOMC. Published months ahead by the Fed and BLS.
- **Story news** — narrative headlines with sentiment, from a paid vendor.

SPY is ~500 names, so one company's story is diluted to nothing and partly offset by another's. The
book is structurally immune to single-name news and structurally fully exposed to macro. *(Caveat:
index concentration has eroded this — the top 10 are ~35–40% of SPY and NVDA earnings is now an
index-level event, not a single-stock one.)*

Magnitudes are the opposite of intuition: a stock moves 5–10% on its own earnings, SPY ~1% on CPI.
Single-name news is far bigger **per stock**; macro is far bigger **per portfolio**, because it hits
every position in the same direction in the same second and deletes diversification exactly when it
was needed. For a single-underlying SPY book only the second one exists.

**A news vendor's real job is the UNSCHEDULED event** — an FDA decision, a surprise merger, an 11:40
guidance cut. Scheduled events come free from a calendar. For SPY that unscheduled category is
essentially empty, which is why the vendor half kept evaluating as weak: not bad vendors, just
nothing for them to catch here. Deferred, not rejected — it becomes real the day the book holds
single names.

### TradingView is not a source

Every TradingView "API" is one where **TradingView is the client and we are the server**: the
Charting Library's Datafeed API and the Broker Integration API are interfaces *we* implement for
*them* to call; widgets are display-only iframes. The one outbound path is Pine Script alerts →
webhook, which carries our own chart condition, not headlines.

This is a **licensing wall, not a technical gap.** They license news from Reuters / Dow Jones /
Benzinga under contracts permitting display to a logged-in TradingView user, not redistribution. A
public news API would be reselling Dow Jones's product. Same for exchange data. Scraping is the part
of that wall that gets an account banned. "TradingView has good news" means "TradingView pays for
good news" — and for the *calendar* specifically, the upstream source is free and public, so there is
nobody to pay.

### Windows, not days — and which windows actually reach us

The naive design flags a whole day. Nobody serious does that: the market does not have a bad *day*
because of CPI, it has a violent *five minutes*. The unit is a window around the release timestamp.

That matters because releases land at different times, and this book enters after
`entry_after_open_minutes` and is flat by 15:45:

| Release | Lands | Do we hold through it? |
|---|---|---|
| FOMC decision 14:00 + presser 14:30 | mid-session | **Yes — dead centre** |
| ISM / consumer sentiment / JOLTS 10:00 | mid-morning | **Yes** |
| CPI / PPI / NFP 08:30 | pre-open | **No — resolves before entry** |

So danger to *this* book ranks **FOMC 14:00 > 10:00 releases >> CPI 08:30** — the reverse of the
intuition that made 08:30 the design's anchor. CPI is the famous one, but we are never in a position
when it prints; we enter *after* the IV crush, not into it. The Fed is the one we hold long premium
straight through, which is the classic way to be right on direction and still lose.

### What v1 records

**Both halves, one event list:**

- **09:00 ET morning summary** — what is scheduled today, on the `email_report_scheduler.py`
  two-stage anchor (03:00 cron reads Tradier `markets/calendar`, then a one-shot at
  `open.start − 30min`). Holidays fall out for free; a flat `CronTrigger(hour=9)` would fire on them.
- **Per-event logging through the session** — every release stamped with its exact time.

**Store timestamps, not dates.** A row saying *"today had CPI"* can never test a window size. A row
saying *"CPI released 2026-09-11 08:30:00 ET"* lets us go back through fills and ask whether trades
opened within 15 / 30 / 60 minutes of a release did worse, and let the data choose the window. We
already capture MFE/MAE per trade, so the test can measure how hard those trades went against us
before resolving, not just whether they lost.

The verdict is **per-day, not per-strategy** — a CPI print is true for every strategy at once. The
per-strategy column sketched in TODO reads the day's row rather than computing its own.

**Why record before acting:** this question cannot be answered retroactively. Trades ≤ id 2905 are
untrustworthy under CP-1 and the 174 post-cutoff churn trades drag everything until filtered; clean
history starts after the 2026-08-25 fixes, so roughly one CPI and one FOMC exist to look at. That is
an anecdote. The value of v1 is **starting the clock.** Same data-first pattern as B2 (entry-drift)
and A1 (GFV reservations).

### Calendar source — a checked-in file, not a vendor

FOMC dates publish a year ahead; BLS publishes an annual release schedule. ~20 entries, seeded once a
year in a repo YAML with exact release times. Cannot rate-limit, cannot be down at 08:59, reviewable
in a diff, free. A vendor econ-calendar API (Finnhub, FMP, Trading Economics) adds a key and a
network dependency to fetch data that changes annually.

**What a vendor would genuinely add is consensus forecasts.** The date is free; the *expectation* is
not — and price reacts to `actual − consensus`, not to the event. An in-line CPI is a non-event; a
two-tenths miss is a 1% move on the identical calendar entry. Report-only needs dates only, so v1
pays nothing. Consensus becomes worth buying the day we want to *predict* rather than *observe*.
*Open:* whether to cross-check the annual seed against a free vendor, or trust the release schedules.

### Deferred, and what it would inherit

`avoid_economic_news: True` is set in all eight templates (`strategy_templates.py:99,148,198,247,297,
346,395,444`) and **nothing in the tree reads it** — the engine advertises this behavior and does not
have it. The calendar is what that param was waiting for, but wiring it up is a gate, so it belongs
to the deferred phase.

If a blackout window ever ships it is a new entry gate and inherits the engine rules: compose
most-restrictive-wins with the bounds at `signal_generator.py:289` (`entry_after_open_minutes` ∧
`user.trading_window_start` ∧ forced-exit time), never widen any of them, and let `side='sell'`
through so a blackout cannot trap an open position.

### Already in the tree

- `services/email_report_scheduler.py` — the two-stage anchor to copy.
- `engine/signal_generator.py:60` `resolve_direction()` — **closes TODO's "strategy-direction mapping
  is the real design problem"**; direction is already a validated `params_json` field with one
  resolver, no `bias` column needed. Moot for a per-day verdict, but it unblocks the story-news half
  if that is ever built.
- `stream_driven_worker.py:304` — `strategy.instruments[0]`, one underlying per strategy.

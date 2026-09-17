# Static vs dynamic exits: the math, with real numbers

*Study note, written 2026-09-16. Nothing in the engine was changed by it.*

**Chart:** `data/backtest/dynamic_exits.html` (regenerate with `./venv/bin/python scripts/chart_dynamic_exits.py`).
Its panels 2-3 estimate volatility from the trailing 30 minutes only — what a live engine would know — while
§3 and §6 below use after-the-fact morning/afternoon windows. So the chart shows 10:30 at 0.86σ / 39% and
14:30 at 0.29σ / 77% where this note says 0.92σ / 36% and 0.25σ / 80%. Same conclusion, different estimator.

Every number below comes from the **2026-09-16 live session** (recorded SPY tape, recorded option
quotes, the real 10:07 ET put trade). Times are ET.

---

## 1. The one idea behind all of this

A stop loss, take profit or trailing stop is a **distance**. The question is what you measure that
distance in.

| Style | Measured in | Example |
|---|---|---|
| **Static** (what runs today) | % of the option's price | "sell if the option drops 15%" |
| **Dynamic** | how much SPY normally moves right now | "sell if SPY moves against me more than it usually does in 30 minutes" |

A static 15% is the same number all day. **But the market isn't the same all day.** A calm morning
and a crashing afternoon need different distances, or the stop means different things at
different times.

---

## 2. The three conversions you need

### A. Option move → SPY move (uses delta)

**Delta** is how much the option moves when SPY moves $1. Today's put had delta **0.64**: SPY down
$1 → put up about $0.64.

```
SPY move  =  option move  ÷  delta
option move  =  SPY move  ×  delta
```

### B. SPY move → "how normal is that?" (uses sigma)

**Sigma (σ)** is the size of a *typical* SPY move over a time window, measured from recent prices.
Measured today:

| Window | Calm morning (10:00–11:30) | Afternoon selloff (14:00–15:30) |
|---|---|---|
| typical 10-minute move | **$0.45** | **$1.73** |
| typical 30-minute move | **$0.64** | **$3.21** |

The afternoon was **5× wilder** than the morning.

```
k  =  SPY move  ÷  σ          ("how many typical moves away is my stop?")
```

### C. "How many σ away" → chance random wiggle hits it

If SPY is just drifting randomly, the chance it touches a level `k` typical moves away within that
window is roughly `2 × (1 − Φ(k))`:

| Stop is this far away (k) | Chance random noise hits it |
|---|---|
| 0.18 σ | **86%** |
| 0.25 σ | 80% |
| 0.50 σ | 62% |
| 1.00 σ | **32%** |
| 1.50 σ | 13% |
| 2.00 σ | 5% |

**Rule of thumb:** a stop closer than ~1 σ is mostly measuring noise, not "the trade was wrong."

---

## 3. Stop loss — static 15% vs dynamic

### Today's put: entry $2.52, delta 0.64

**Static 15%:**

```
option distance  = 15% × $2.52         = $0.378
SPY distance     = $0.378 ÷ 0.64        = $0.59
```

Same $0.59 — but look what it means at two times of day:

| | Calm morning | Afternoon selloff |
|---|---|---|
| typical 30-min move | $0.64 | $3.21 |
| stop is (k) | $0.59 ÷ $0.64 = **0.92 σ** | $0.59 ÷ $3.21 = **0.18 σ** |
| chance noise hits it | **36%** | **85%** |

**Same 15%. In the morning it's a reasonable stop. In the afternoon it's a coin that lands on
"stopped out" 85% of the time.**

**Dynamic — "1 typical 30-minute move":**

```
SPY distance     = 1.0 × σ30
option distance  = SPY distance × delta
stop %           = option distance ÷ option price
```

| | Calm morning | Afternoon selloff |
|---|---|---|
| SPY distance | 1.0 × $0.64 = $0.64 | 1.0 × $3.21 = $3.21 |
| option distance | $0.64 × 0.64 = **$0.41** | $3.21 × 0.64 = **$2.05** |
| as a stop % | **16.3%** | **81.5%** |
| loss if stopped, 1 contract | **$41** (2.8% of account) | **$205** (14.0% of account) |
| chance noise hits it | 32% | 32% |

**What changed:** the chance of a noise stop-out is now the **same 32% all day**. That's the point.

**The catch, and why you said "not yet":** in a wild market the honest stop is **huge** — $205 on one
contract. A dynamic stop only works if **size shrinks** when the stop widens:

```
contracts  =  (account × risk %)  ÷  (option distance × 100)
```

At 2% of $1,464 = **$29 max loss**, one contract can have an option stop of at most **$0.29**.
Morning needs $0.41 → **0 contracts**. Afternoon needs $2.05 → **0 contracts**. With one contract
as the minimum, a dynamic stop on this account means either breaking the 2% rule or skipping the
trade. That is the real constraint — not the math.

A common middle ground: use the dynamic stop, but **skip the trade** if that stop is wider than a
maximum (say 25%). The market is telling you it's too noisy for your account.

---

## 4. Take profit — static 25% vs dynamic

**Static 25%** on the $2.52 put:

```
option distance = 25% × $2.52 = $0.63
SPY distance    = $0.63 ÷ 0.64 = $0.98
morning: $0.98 ÷ $0.64 = 1.54 σ      afternoon: $0.98 ÷ $3.21 = 0.31 σ
```

Morning: SPY needs an unusually big move to reach it. Afternoon: it's reached almost by accident.

**Dynamic: set the target as a multiple of the dynamic stop** (e.g. 2× — "risk 1 to make 2"):

```
morning:  stop $0.41 (16.3%)   target 2 × $0.41 = $0.82 (32.5%)
```

**The part that does NOT change:** the win rate you need to break even depends only on the
**ratio**, not the size:

```
break-even win rate  =  stop ÷ (stop + target)

live today   15% / 25%   →  15 ÷ 40   =  37.5%
1 : 2 ratio  any size    →   1 ÷ 3    =  33.3%
```

So going dynamic doesn't change *how often you must win*. It changes *how often noise decides
the outcome* instead of the signal.

*(Live note: while the trailing stop is armed, the flat target is switched off — see §5.)*

---

## 5. Trailing stop — static 10% vs dynamic

Today's put, from the recorded quotes:

```
10:07:01  entry    $2.52
10:09:29  low bid  $2.32   (−7.9%, never near the 15% stop)
10:27:46  peak bid $2.91   (+15.5%, trail armed)
10:37:51  exit     $2.61   (+3.2%, +$9)
```

### Static: give back 10% of the peak

```
exit level = $2.91 × 0.90 = $2.62  →  sold $2.61  →  +$9
kept $0.09 of a $0.39 gain = 23%
```

The problem: exit ≈ 0.9 × peak, so

| Peak reached | You keep |
|---|---|
| +15% (just armed) | +3.5% |
| +22% | +10% |
| +30% | +17% |

### Dynamic method 1 — keep a share of the GAIN, not of the price

```
exit level = entry + keep% × (peak − entry)
```

| Keep | Exit level | First hit (recorded) | Result |
|---|---|---|---|
| 50% of gain | $2.52 + 0.5 × $0.39 = **$2.715** | 10:30:41 at $2.71 | **+$19** |
| 70% of gain | $2.52 + 0.7 × $0.39 = **$2.793** | 10:28:34 at $2.78 | **+$26** |
| static 10% of peak | $2.62 | 10:37:51 at $2.61 | +$9 |

It scales with how far the trade actually ran: a trade that barely arms gets a tight leash, a
trade that runs +50% gets room.

### Dynamic method 2 — volatility trail ("chandelier exit")

```
exit level = peak − k × delta × σ10
```

| | Calm morning (σ10 $0.45) | Afternoon (σ10 $1.73) |
|---|---|---|
| k = 0.5 | trail $0.144 (5% of peak) → exit level **$2.766** | trail $0.55 (19%) → exit $2.36 |
| k = 1.0 | trail $0.29 (10% of peak) → exit **$2.62** | trail $1.11 (38%) → exit $1.80 |

At k = 0.5 in this morning's calm tape, the first bid at or below $2.766 was **$2.76 at 10:29:18 → +$24**.
*(An earlier version of this note rounded the level to $2.77 and reported 10:28:42 / +$25 — the unrounded
level is correct.)*

**Notice k = 1.0 in the morning lands on exactly the static 10%.** Today's morning was calm enough
that the flat number happened to be right. The difference only shows up when volatility changes —
which is the entire reason to be dynamic.

---

## 6. Same flat 15%, same contract, two times of day

The call armed all day, `SPY260916C00757000`, delta ≈ 0.70:

| | 10:30 (calm) | 14:30 (selloff starting) |
|---|---|---|
| option bid | $3.49 | $3.71 |
| 15% stop distance | $0.52 | $0.56 |
| as SPY distance | $0.75 | $0.80 |
| typical 30-min move | $0.64 | $3.21 |
| stop is (k) | **1.17 σ** | **0.25 σ** |
| chance noise hits it | **24%** | **80%** |
| dynamic 1 σ stop would be | $0.45 = **13%** | $2.25 = **61%** |

**Nearly identical dollar stops. One is a sensible stop, the other is almost guaranteed to fire on
noise.** A static % can't see the difference; a dynamic one can.

---

## 7. On our real trades: the winning days

> **CORRECTED 2026-09-16 — an earlier version of this section said "dynamic target + trailing stop
> beat the live rule by +$45". It does not. Do not cite that figure.** The offline script measured
> SPY's volatility including the minute the trade was entered in — whose closing price comes from
> *after* the entry, which the engine can never know. On 09-09 at 11:01 that look-ahead put the
> dynamic target at $4.60 (+$172); measured honestly it is $4.00 (+$112). That one trade was the whole
> edge. **It was caught by the live shadow module itself:** run over all 28 real trades it disagreed
> with the script on exactly that trade; with the script fixed they agree on 128 of 128 rule/trade
> pairs. Every number below is the corrected one.

§3–§6 used one trade. This section runs the same rules over **every round trip actually filled on a
day that finished positive** — 7 days, 21 trades, real total **+$680**. Each trade keeps its real
entry time, fill price and quantity, then walks forward over that contract's recorded bid. The
**15% stop loss is held fixed**, so only the profit-side rule changes.

Script: `./venv/bin/python scripts/dynamic_exits_review.py` (add `--all-days` for losing days too).

| Rule | What it does |
|---|---|
| **live** | trail arms at +15%, sells after giving back 10% of the peak price |
| **keep 70%** | trail arms at +15%, sells after giving back 30% of the peak *gain* |
| **keep 50%** | same, gives back 50% of the gain |
| **vol trail** | trail arms at +15%, sells at peak − 0.5 × delta × typical 10-min SPY move |
| **dynamic TP** | no trail; fixed target at 2 × delta × typical 30-min SPY move above entry |
| **TP + trail** | the dynamic target, **plus** the live trailing stop underneath it — both active at once |
| **TP + BE** | the dynamic target, **plus** a break-even stop: once up +15%, the stop moves to the entry price |
| **structure** | a **stop-side** rule: the stop follows SPY swing points (see "The structure stop" below), plus the live trail, with the 15% stop as the floor |
| **literal** | "the stop is the lowest price since entry" taken literally — sells on the first new low. + 15% floor + live trail |

The trade-by-trade table below covers the profit-side rules; the two stop-side rules are broken out
in their own subsection, because they only change a handful of trades.

"Typical move" is always measured from **completed** 1-minute bars before the moment in question.

### Trade by trade

$ is the result at the real quantity. **?** = the contract stopped being recorded before that rule
would have sold, so the outcome is unknown (never counted as zero). Generated from script output.

| Day | Entry | Real | live | keep 70% | keep 50% | vol trail | dyn TP | TP + trail | TP + BE |
|---|---|---|---|---|---|---|---|---|---|
| 09-02 | 10:00 | +84 | ? | +33 | +25 | +25 | +167 | +167 | +167 |
| 09-02 | 10:07 | +105 | ? | ? | ? | +66 | ? | ? | ? |
| 09-02 | 11:15 | −46 | +26 | +44 | +31 | +42 | −45 | +26 | 0 |
| 09-04 | 10:16 | +14 | +14 | +32 | +22 | +22 | +144 | +14 | 0 |
| 09-04 | 10:29 | +153 | +144 | +135 | +102 | +60 | +142 | +142 | +142 |
| 09-04 | 11:07 | −71 | −69 | −69 | −69 | −69 | −69 | −69 | −69 |
| 09-08 | 10:00 | +55 | +54 | +79 | +54 | +96 | ? | +54 | ? |
| 09-08 | 10:17 | −39 | −41 | −41 | −41 | −41 | −41 | −41 | −41 |
| 09-08 | 10:25 | +30 | +22 | +33 | +22 | +22 | −36 | +22 | 0 |
| 09-09 | 10:01 | +43 | +44 | +73 | +54 | +89 | ? | +44 | ? |
| 09-09 | 10:28 | −62 | −44 | −44 | −44 | −44 | −44 | −44 | −44 |
| 09-09 | 11:01 | +126 | +125 | +31 | +24 | +22 | +112 | +112 | +112 |
| 09-14 | 10:02 | −15 | −15 | −15 | −15 | −15 | −15 | −15 | −15 |
| 09-14 | 10:02 | +24 | +24 | +24 | +18 | ? | ? | +24 | 0 |
| 09-14 | 10:22 | +53 | +45 | +58 | +37 | +64 | ? | +45 | −15 |
| 09-14 | 10:35 | +46 | +45 | +60 | +43 | +60 | ? | +45 | −30 |
| 09-14 | 10:47 | +33 | +29 | +49 | +34 | +49 | −60 | +29 | −21 |
| 09-15 | 10:09 | +146 | ? | +90 | ? | +110 | +126 | +126 | +126 |
| 09-15 | 11:51 | +46 | +38 | +54 | +38 | +38 | −46 | +38 | 0 |
| 09-15 | 12:30 | −54 | −54 | −54 | −54 | −54 | −54 | −54 | −54 |
| 09-16 | 10:07 | +9 | +9 | +26 | +19 | +26 | ? | +9 | ? |

### What the table says, plainly

**1. Keeping a share of the gain rescues the small winners.** The trades that barely armed and then
gave most of it back nearly all do better with **keep 70%** (one, 09-14 at 10:02, is unchanged):
+9 → **+26**, +14 → **+32**, +33 → **+49**, +46 → **+60**, +46 → **+54**. That is exactly the problem §5
described.

**2. But it cuts the big runners short.** 09-09 at 11:01 ran to **+$125** under the live rule. Keep 70%
sold it at **+$31**, the volatility trail at **+$22** — a runner that dips on the way up looks like a
reversal to a tight trail. 09-04 at 10:29 (+$144 live) fell to **+$60** under the volatility trail.

**3. The volatility trail is inconsistent at k = 0.5.** It roughly doubled two morning winners
(+54 → **+96**, +44 → **+89**) and gutted two others (+125 → +22, +144 → +60). The same tightness that
helps one path hurts the next.

**4. The dynamic target is the most volatile of all.** It caught some large wins (+167, +144, +142)
but also **capped** runners (+125 → +112 on 09-09, and +126 on a trade that really made +146), and it
turned three modest winners into stop-outs (+30 → −36, +46 → −46, +33 → −60) because it has no trail
to lock anything in. A third of its trades can't be resolved.

**5. Losing trades barely change.** Stop-outs are identical under every rule, because the stop was
held fixed. The exit rule only matters once a trade has gone your way.

**6. Giving the dynamic target a trailing stop fixes point 4's losses — and nothing more.** With the
live trail underneath it, the three winners the bare target turned into losses stay winners (+22,
+38, +29). On nearly every trade **TP + trail** sells exactly where the live rule does; where it
differs, the target sold first and *earlier than the trail would have* (see below).

**7. A break-even stop is not a substitute for a trail.** **TP + BE** only protects against a loss —
once a trade has run and faded, it sells at the entry price (the 0s), or a few cents under it when
the price gaps down past entry (−15, −21, −30). The live trail would have locked in part of those gains.

### The totals — and why the obvious one is misleading

Adding up each column over the trades that rule *could* resolve:

```
live       +396   (18 of 21)
keep 70%   +598   (20 of 21)     <- looks like +$200 better
vol trail  +568   (20 of 21)
keep 50%   +300   (19 of 21)
dyn TP     +281   (14 of 21)
TP+trail   +674   (20 of 21)     <- looks like +$280 better
TP+BE      +258   (17 of 21)
struct     +570   (19 of 21)
literal     −46   (20 of 21)
```

**Don't use those.** Each column covers a *different set of trades* — the dynamic rules can resolve
the 09-02 +$167 and 09-15 +$126 trades that the live rule can't, so they get credit the live column
never had a chance to earn.

The fair comparison uses only the **12 trades every rule resolved**:

```
struct     +198    (+23 vs live)
live       +175
TP+trail   +160    (−15)
keep 70%   +155    (−20)
keep 50%    +50    (−125)
vol trail   +32    (−143)
TP+BE       +10    (−165)
dyn TP      −12    (−187)
literal     −77    (−252)
```

**On a like-for-like basis, only the structure stop beat the live rule (+$23)** — and only by getting
out of losing trades sooner (below). Among the profit-side rules nothing beat it; TP + trail and keep
70% came closest, both slightly behind.

*(Compare rules against the **live** replay row, not the real column: real fills include slippage
past the stop — 09-09 10:28 filled at −$62 where the bid said −$44 — and 09-02 still ran the older
exit rules before the trail fix.)*

### Across every day, losing days included

Same rules over all 28 real round trips, like-for-like on the 19 every rule resolved:

```
struct     −45     (+31 vs live)
live       −76
keep 70%   −80     (−4)
TP+trail   −91     (−15)
literal   −123     (−47)
keep 50%  −193
vol trail −211
TP+BE     −266
dyn TP    −321
```

Same picture: the structure stop is the only rule ahead of live; among profit-side rules keep 70% is
closest. Losing days add almost nothing new — their
trades are stop-outs, identical under every rule.

### TP + trail, looked at closely

It sells differently from the live rule on only four trades — the ones where the target is reached
before the trail gives anything back:

| Trade | Real | live | TP + trail | |
|---|---|---|---|---|
| 09-09 11:01 | +126 | +125 | +112 | target at $4.00 sold before the trail's $4.13 |
| 09-04 10:29 | +153 | +144 | +142 | target sold $0.02 below where the trail did |
| 09-02 10:00 | +84 | ? | +167 | live rule can't be resolved here |
| 09-15 10:09 | +146 | ? | +126 | the target **capped** a trade that really ran to +$146 |

On the two it can be compared on, **the target sold earlier and for less.** The two where it looks
strong are exactly the two the live rule can't be measured on, so they say nothing about which is
better. A fixed target caps upside by design; on these trades the trail was already doing the job.

**It also can't run on the engine as it stands.** Today the flat take profit is switched off the
moment the trail arms (§4's live note). Using both at once would be a change to the exit path.

### The structure stop *(added 2026-09-17)*

The owner's idea: use the lowest low since entry as the stop, never looser than 15%.

**Taken literally, it fails.** If the stop sits *at* the lowest price seen so far, the first new low
touches it — so it sells within seconds on almost every trade, paying the spread each time (the
literal column: **−$123** like-for-like across all days, against **−$76** for live). Sept 16's put, for
example, sold at −$4 instead of making +$9.

**The workable form is a structure stop**, a standard technique. Definitions were **fixed before any
result was seen** and not tuned afterwards:

- **Levels come from SPY's 1-minute bars** (completed bars only), not the option — SPY is what the
  entry signal reads, and it is far less jumpy.
- **A swing point** is a bar whose low is below the lows of the 2 bars on each side (for a put: whose
  high is above the highs), confirmed only once those 2 later bars have closed, and formed at or after
  the entry minute.
- **The stop** sits a quarter of SPY's typical 10-minute move beyond the swing point, and **only moves
  in the trade's favour** (calls up, puts down).
- **It fires when a 1-minute bar closes beyond it**, not on a brief poke; the exit is the option bid on
  the next tick.
- **The 15% stop stays as the floor, and the live trailing stop stays on.**

**It changed only four of the 28 trades:**

| Trade | Real | Live rule | Structure stop | Difference |
|---|---|---|---|---|
| 09-04 11:07 put | −71 | −69 (15% stop at 12:05) | **−46** (sold 11:15) | **+23** |
| 09-10 10:16 put | −34 | −34 (15% stop) | −27 | +7 |
| 09-11 11:28 call | −65 | −65 (15% stop) | −64 | +1 |
| 09-15 10:09 put | +146 | ? (unresolved) | +151 | — |

**Every winner it could measure came out identical** — including Sept 16's put, which dipped 8% in its
first two and a half minutes. It helps the way a stop should: losing trades exit sooner, winners are
left alone.

**Walkthrough — 09-04 11:07 put, bought at $4.57** (chart panels 4-5 of
`data/backtest/dynamic_exits.html`):

```
11:08   SPY makes a swing high at $769.76
11:10   the 2 bars after it close -> swing confirmed, stop placed at $769.89
11:14   a 1-minute bar CLOSES at $769.94, above the stop
11:15   the option sells at the next tick, $4.11   -> −$46
12:05   the live rule, still holding, hits the 15% stop at $3.88   -> −$69
```

Every step uses only information that existed at that moment.

**Why it isn't a switch to flip yet:**

- **Nearly all of the +$31 is one trade** (09-04, +$23).
- **That trade's trigger cleared the stop by 5¢.** A slightly different buffer could have gone the other
  way — which is exactly why the buffer was fixed before looking.
- **Three changed trades is a very small sample**, the same caution that retracted the "+$45" above.

**Checked against the live engine code:** the shadow module's version of this rule, fed SPY at the
engine's once-a-second rate, agrees with the replay on **26 of 26** trades it could resolve.

### What this points to

The finding isn't "static is better" or "dynamic is better." It's that **small gains and big runs
want opposite treatment**:

- a trade that just barely armed should be **held tightly** (keep most of a small gain), and
- a trade that has run far should be **given room** (a dip on the way up isn't the end).

No profit-side rule tested does both, and **none beats the live rule on this sample.** Keep 70% comes
closest by trading big-runner profit for small-winner profit. The one rule that did beat live worked on
the other side of the trade — the **structure stop** cut losers earlier without touching winners — and
it rests on three trades. The untested idea that might do both is a
**tiered trail** — tight while the gain is small, loosening as it grows — already on the list as
**TODO E8**. It was suggested *by* these 21 trades, so it needs trades this analysis hasn't seen.

### Shadow mode — collecting that evidence live

Since 2026-09-16 the engine runs `api/engine/exit_shadow.py` on every open position. It **acts on
nothing**: it watches keep 70%, keep 50%, vol trail, dynamic TP, TP + trail and (since 2026-09-17) the
structure stop, using the same definitions as this section, and records when each *would* have sold.
For the structure stop it builds its own 1-minute SPY highs and lows from the price the engine already
sees each second. On each real close it writes
one `SHADOW SUMMARY` line to the engine log and one record to
`logs/livetest-<date>/exit_shadow-*.jsonl`. Rules still holding at the real exit are recorded as
`open`, never as flat. Tests: `api/tests/test_exit_shadow.py`.

### Limits specific to this section

- **21 trades over 7 days** (28 over 10 including losing days). One runner moves a column by $100 —
  and one trade *was* the entire previous "+$45" result.
- **Picking winning days favours rules that let winners run.** The all-days run is the fairer read.
- **The unknowns are biased.** Trades a rule can't resolve are mostly ones it would have *held
  longer* — often the long runners. Every column's total is missing some of its best and worst cases.
- **The recording is 2-second samples and exits are read off the bid**, so a replay can't see
  slippage and can miss a brief dip that triggered a real exit.

---

## 8. Cheat sheet

```
SPY distance      = option distance ÷ delta
option distance   = SPY distance × delta
k (in σ)          = SPY distance ÷ σ(window)
noise-hit chance  ≈ 2 × (1 − Φ(k))

dynamic stop      = k × σ(hold window) × delta              (k ≈ 1.0–1.5)
dynamic target    = ratio × dynamic stop                    (e.g. 2×)
break-even win %  = stop ÷ (stop + target)                  (unchanged by scaling)
trail, keep gain  = entry + keep% × (peak − entry)          (keep ≈ 50–70%)
trail, chandelier = peak − k × delta × σ(10 min)            (k ≈ 0.5–1.0)
contracts         = (account × risk%) ÷ (option stop × 100) (the sizing that has to go with it)
```

**Where σ comes from in a live engine:** the standard deviation of recent SPY moves over the
window (the recorded tape already has this), the average 1-minute high–low range (ATR), or the
option chain's implied volatility. They agree roughly; pick one and stick with it.

---

## 9. Honest limits of this note

- **One trade in §3–§6.** The "+$19 / +$24 / +$26 instead of +$9" figures are what *that* trade's
  recorded path shows. §7 runs the same rules over every real trade, and the answer changes: a
  tighter trail also exits winners that would have kept running.
- **Delta isn't constant.** It changes as SPY moves (gamma). Converting with a fixed delta is
  approximate — `scripts/cost_budget.py` found the straight-line version up to **~20% optimistic**
  over a 30-minute hold at delta 0.60.
- **Sigma is an estimate.** Measured from recent minutes, it lags sudden changes like the 14:45
  selloff. Morning and afternoon σ here come from after-the-fact windows, which a live engine
  wouldn't have yet.
- **Implied volatility moves the option too** (vega), separately from SPY. None of the conversions
  above include it.
- **Exits are sacred** (CLAUDE.md). Any of these would be a live exit-path change needing tests, a
  replay across every session, and sign-off. Related open items: TODO **D6** (sizing), **E8**
  (tiered trailing stop), and the cost-budget section of `BRAINSTORM.md`.

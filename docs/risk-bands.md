# Risk Bands — what to change as the account grows

*Written 2026-09-07. Every number below was produced by running the real
`RiskManager.calculate_position_size`, not by hand arithmetic.*

**This is a planning document, not a change.** Nothing here is implemented. It
exists so that when the account crosses a threshold there is a considered answer
ready, instead of a decision made in a hurry on a market morning.

---

## 1. Why this exists

The account is $1,214. One SPY 0DTE contract at $3.00 premium costs $300 — a
quarter of it.

That was never chosen. It is what the settings happen to produce at this account
size, and it will silently become wrong in both directions as the balance moves.

---

## 2. How sizing actually works today

Three numbers combine, and none of them means what its name suggests.

```
effective_pct   = min(user.max_trade_percentage, params.risk_per_trade_pct)
capital         = account_size × effective_pct / 100
max_contracts   = int( capital / (premium × 100 × SAFETY_FACTOR) )      SAFETY_FACTOR = 2.0
final_qty       = min(max_contracts, params.max_contracts)
```

Four things worth knowing, each of which has surprised someone:

**a. `risk_per_trade_pct: 50` does not risk 50%.** The `× 2` safety factor
halves it. At 50 you deploy **~25%** of the account, not 50%.

**b. The two percentages are a `min()`.** `risk_per_trade_pct` and the user's
`max_trade_percentage` are both 50 today. Changing one alone does nothing.
**Always change both.**

**c. `× 100` is the contract multiplier.** One option contract controls 100
shares, so a "$3.00" contract costs $300. This is why the instrument type has to
be right — see [TODO E9](../TODO.md).

**d. `int()` truncates, so sizing is lumpy at low contract counts.** The step
from 1 contract to 2 is a 100% jump in exposure. Bands are smooth on paper and
chunky in practice below ~5 contracts.

### The one formula to remember

```
risk_per_trade_pct  ≈  2 × (target % of account per position)
```

Want 10% of the account in a position? Set **20**. Want 5%? Set **10**.

---

## 3. The number that actually matters: the tail, not the stop

Two different risks, and only one of them is the one to size against.

| | At $1,214 account, $300 position |
|---|---|
| **Expected risk** — the 15% stop fires | $45 = **3.7%** of account |
| **Tail risk** — the contract goes to zero | $300 = **24.7%** of account |

3.7% is defensible. 24.7% is the one to think about, because:

- **There are no broker-side stops.** Every exit is simulated in-engine and sent
  as a market order when our own logic decides. If the process dies, the host
  reboots, or the WebSocket wedges while a position is open, nothing protects it.
  TODO ranks this above everything else: *"money-gone-in-one-event."*
- **0DTE options genuinely go to zero**, routinely, within minutes.
- **A gap moves through a simulated stop** without ever giving it a price to fire
  at.

> **Size against the full premium, not against the stop.** Ask "what if this
> position is a total loss?", not "what if my stop fires?"

---

## 4. What the settings already do, unintentionally

`max_contracts: 3` binds at about $5,000 and never releases, so exposure falls
on its own as the account grows:

| account | qty | deployed | % of account |
|---|---|---|---|
| $1,214 | 1 | $300 | **24.7%** |
| $2,000 | 1 | $300 | 15.0% |
| $5,000 | 3 | $900 | 18.0% |
| $10,000 | 3 | $900 | 9.0% |
| $25,000 | 3 | $900 | 3.6% |
| $100,000 | 3 | $900 | **0.9%** |

Today's settings are roughly right between $5k and $25k and **wrong at both
ends** — too much risk below, too little deployment above. At $100k the strategy
would be putting 0.9% to work, which is not a strategy.

---

## 5. The bands

Starting points to argue with, not prescriptions. Verified at a $3.00 premium.

| Band | Account | Target per position | `risk_per_trade_pct` **and** `max_trade_percentage` | `max_contracts` | Actual result |
|---|---|---|---|---|---|
| **A** | < $2,500 | *no choice* | 50 | 3 | 1 contract, 13–25% |
| **B** | $2,500–10k | ~10% | **20** | 3 | 1–3 contracts, 10.0% |
| **C** | $10k–25k | ~5% | **10** | 6 | 2–3 contracts, 4.5–5.0% |
| **D** | $25k–50k | ~3% | **6** | 10 | 3–4 contracts, 2.7–3.0% |
| **E** | $50k–100k | ~2% | **4** | 15 | 4–6 contracts, 2.0% |
| **F** | $100k+ | ~1% | **2** | 25 | 1.0% |

### Band A is not a recommendation, it is a description

At under $2,500 there is no sizing decision to make: one contract is the
minimum, and one contract is 13–25% of the account. **The contract price is
choosing the risk, not the settings.** The honest framing is that this band is
tuition — keep size at the floor, treat the money as the cost of learning
whether the strategy works, and get to Band B.

---

## 6. The trap: bands control the ceiling, not the exposure

Rerun at a **$5.00** premium instead of $3.00 and Band A becomes:

```
account $1,214   1 contract   $500 deployed   =  41.2% of account
```

Nothing in the settings changed. A pricier contract on a small account blows
straight past the target, because **the settings cap the capital allocated, not
the fraction of the account a single position represents.**

The lumpiness shows up higher too — at $5.00, Band D at $30,000 gets 1 contract
(1.7%) while $45,000 gets 2 (2.2%). Non-monotonic, because of `int()`.

> **A band table alone does not bound risk.** It needs a companion gate that
> checks the *actual* position against the account at entry.

---

## 7. Bringing it to life

Four ways, cheapest first. **The recommendation is 1 → 2 → 3, and explicitly
not 4.**

### Option 1 — This document plus a checklist *(recommended first step)*

Cross a threshold, open this file, change four fields in the strategy form and
one on the profile. No code.

- **Pros:** zero risk, available today, forces a deliberate human decision.
- **Cons:** relies on noticing the threshold.

### Option 2 — A dry-run script

`scripts/apply_risk_band.py --dry-run` reads the live account size, prints the
band, the current settings, the recommended settings and the diff. `--apply`
writes them.

- **Pros:** removes arithmetic errors; `--dry-run` by default; every change is
  explicit and logged.
- **Cons:** still needs to be run.
- **Note:** should refuse to run while the market is open, and never touch a
  strategy with an open position.

### Option 3 — An advisory banner in the UI

The dashboard already syncs `account_size_usd` from the broker. When it crosses
a band boundary, show a dismissible banner: *"Account passed $2,500 — recommended
position sizing has changed. Review."* Links to this doc. **Advisory only, never
auto-applies.**

- **Pros:** solves the "noticing" problem, which is the actual weakness of 1 and 2.
- **Cons:** real UI work; needs somewhere to store "last acknowledged band" so it
  does not nag.

### Option 4 — Automatic sizing from a band table *(do not build)*

Have `calculate_position_size` derive the percentage from the account size
directly.

**Rejected**, and worth writing down why: it makes position size change by
itself, with no diff, no event and nothing to point at afterwards. Debugging "why
did it buy 2 contracts today?" would mean reconstructing the account balance at
that moment. The engine rules say behavioural changes need a stated reason; a
change nobody made cannot have one.

### The missing piece — a hard position-size gate

Regardless of which option, §6 shows the bands are not self-enforcing. The
companion is a new entries-only check in `validate_pre_trade`:

```
reject when  qty × premium × 100  >  account_size × max_position_pct / 100
```

Notes for whoever builds it:

- **Entries only.** `side != 'buy'` returns approved, like every other risk gate.
- **A hard ceiling, not a resize.** Rejecting is honest; silently shrinking an
  order hides the fact that the configuration disagrees with reality.
- **It composes.** It only ever removes trades, never widens an existing bound —
  most-restrictive-bound wins.
- **It needs a machine-readable `code`** so it joins the blocked-strategy alert
  and the Blocked badge rather than failing silently.

This is the single change that would make a band table mean something, because
it bounds the fraction of the account at risk *regardless of what the contract
costs that day*.

---

## 8. What changes at each band that is not a number

Sizing is the easy part. These matter more.

| Band | The actual work |
|---|---|
| **A** — today | **Broker-side stops.** Until a resting stop exists at Tradier, the tail column is the real risk number. Also: run the fee reconcile — P&L is gross and net is unknown. |
| **B** — $2.5–10k | **Samples, not profit.** 100+ round trips before trusting any win rate. Still capped near 3 trades/day by T+1 settlement. |
| **C** — $10–25k | Enough history to tune `trailing_stop_distance` from the MFE distribution (TODO E8) and to re-enable drawdown *blocking* with a threshold that means something. |
| **D** — $25k+ | **The structural unlock.** $25k is the pattern-day-trader threshold; a margin account removes T+1 and could multiply the trade count several times over. But cash-only is a deliberate decision in CLAUDE.md — this is a decision, not a step. |
| **E** — $50k+ | **SPX becomes viable.** ~10× SPY notional per contract, so it finally fits. Section 1256 60/40 tax treatment, no wash-sale rules, deeper books at the 0.60–0.85 delta band. |
| **F** — $100k+ | Market impact becomes real. Displayed bid size at these strikes is **1–2 contracts**; daily volume is healthy but instantaneous depth is thin. Exit sizing needs its own thinking. |

---

## 9. Open questions

- **Should `daily_loss_limit_pct` scale down too?** 5% of $1,214 is $61 and binds
  after two losers. 5% of $100,000 is $5,000, which binds after nothing.
  Probably wants its own band column.
- **Should `max_positions` rise above 1 per strategy?** More positions means more
  concurrent exposure but better diversification across strikes.
- **Should Band A trade cheaper contracts instead?** A 0.30-delta contract costs
  far less than the current 0.60–0.85 band, which would fix the sizing problem
  and change the strategy's character entirely. Probably the wrong trade, but it
  is the other lever and should be named.
- **Do the bands apply per strategy or across the account?** Two strategies at
  10% each is 20% deployed. Today nothing checks the total.

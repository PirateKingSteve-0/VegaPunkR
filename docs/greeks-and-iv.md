# What an Option's Price Is Made Of

*Written 2026-09-14. A reference for the five numbers the broker publishes on every
contract — what each one measures, which ones this book can act on, and which ones are
quietly costing money on every trade.*

Plain language first, with the real term named once in parentheses. Every number below is
real, taken either from a live chain snapshot or from this repo's own recorded sessions.

---

## 1. Two halves of every price

A contract's price splits into two parts, and keeping them separate makes everything else
easier.

```
  SPY at 760.88,  a call at strike 753,  price $7.57

     real value    = 760.88 - 753 = $7.88 ... capped at the price, so ~$7.00
     betting money = the rest                          ~$0.57
```

**Real value** (*intrinsic value*) is what the contract would be worth if everything
stopped right now. It cannot evaporate.

**Betting money** (*extrinsic value*, or time value) is what you pay for the chance things
move further your way before expiry. It goes to **exactly zero** at expiry, always, with no
exceptions.

Everything painful about same-day options comes from that second half. A cheap contract is
almost entirely betting money:

```
  strike 761, price $1.90, SPY at 760.88   ->  real value $0,  betting money $1.90
  strike 753, price $7.57, SPY at 760.88   ->  real value ~$7,  betting money $0.57
```

The $1.90 contract loses its whole value by 4pm ET if SPY does not move. The $7.57 one
loses 57 cents. **Same underlying, same expiry, wildly different exposure to the clock.**

---

## 2. Implied volatility — the market's movement forecast

**Implied volatility** is the market's guess at how much SPY will bounce around — not which
direction, just how much — worked backwards out of what people are paying.

An option is insurance against a price move. If insurers are charging a lot, they expect
trouble. IV is that expectation, extracted from the premium.

It is quoted as an annual percentage, which is useless on its face. Divide by about 16 to
get a daily figure:

```
  IV 15.3%  ->  ~0.96% per day  ->  about $7.35 of SPY movement expected today
  IV 10.4%  ->  ~0.66% per day  ->  about $5.05
```

Those two lines are from one of this book's own trades, four hours apart on 2026-09-11.
Nothing dramatic happened. The market simply got quieter — and **that cost money, because
this engine only ever buys.** You paid for a $7 expectation and by 14:09 ET you were holding
a $5 expectation.

When it happens fast, traders call it *IV crush*.

Every number in the next section is computed from IV. It is the single input behind all of
them.

---

## 3. The four numbers

Each answers one question: *if only this one thing changes, how much does the price move?*
Values below are real, from `SPY260915C00761000` priced at $1.90 with SPY at $760.88.

### delta — 0.505 — what you gain per $1 of SPY

SPY up a dollar, this contract gains about 50 cents. That is the whole idea.

It doubles as roughly **the odds of finishing with real value**. A delta of 0.505 is a coin
flip; 0.85 means the market thinks it is very likely to land in the money.

It is also **how deep in the money you are**, which is why it makes a good strike selector:
a high delta means you are buying mostly real value, a low delta means mostly betting money.

### gamma — 0.0798 — how fast delta itself changes

SPY up a dollar and your delta goes from 0.505 to about 0.585. So your winners speed up and
your losers slow down. That is genuinely in a buyer's favour, and it is the one structural
gift of being long.

It is also why same-day options feel violent, and why the cost-budget model in
`scripts/cost_budget.py` solves numerically instead of multiplying: over a 30-minute hold,
delta moves too much to treat as a fixed number. The shortcut is 20% optimistic at
delta 0.60.

### theta — −1.0853 — the clock tax, per day

This contract loses about **$1.09 a day** with SPY completely still. On a $1.90 contract
that is over half its value.

Theta is not linear. It accelerates as expiry approaches, because the betting-money half
decays roughly with the square root of the time remaining. In practice, for a same-day
contract:

```
  entered 10:00 ET, held 30 min  ->  about  2% of premium gone to the clock
  entered 14:00 ET, held 30 min  ->  about  7-10%
  entered 15:00 ET, held 30 min  ->  about 18%
  entered 15:30 ET, held 30 min  ->  about 28%
```

With a 15% stop, **anything entered after roughly 14:30 ET stops itself out on the clock.**
The exit gets logged as a stop-loss. It was the calendar.

### vega — 0.1588 — what a calmer market costs you

If expectations of movement drop by one percentage point, this contract loses about 16
cents — roughly 8%. **SPY does not have to move at all.**

Vega shrinks as expiry approaches (there is less future left to have an opinion about). On
a same-day contract mid-morning it is closer to 2.4% of premium per point. A 5-point
calm-down — completely ordinary once the morning settles, or right after a scheduled
announcement resolves — is about 12% of the contract.

### rho and phi — 0.011 each

Interest rates and dividends. On a contract that expires today they are noise. Ignore them.

---

## 4. The asymmetry that governs this book

This engine **only ever buys** options. That splits the four cleanly, and the split is the
single most important thing on this page:

```
  delta   can help or hurt   - this is the bet being made
  gamma   helps              - the one free gift of being long
  theta   ALWAYS hurts       - every second held, no exceptions
  vega    ALWAYS hurts       - a calmer market is a loss, never a gain
```

Whoever sold the contract has theta and vega working **for** them. They are being paid to
take on the risk of a big move, the way an insurer is.

And they are usually right to take that bet. Across decades, options have been priced
slightly *above* what the market subsequently did — expected movement exceeds actual
movement in roughly 85% of months on SPY. That gap is the best-documented persistent edge in
the literature (*the volatility risk premium*), and **a buy-only book is on the wrong side
of it by construction.**

That does not make buying unworkable. It means the directional call has to be big enough to
pay two guaranteed costs first.

---

## 5. Reading them off a real trade

None of this has to be taken on faith. Every greek is recoverable from data already on disk,
because IV is by definition the number that reproduces the observed price — and the observed
price is in `logs/*/stream-*.jsonl`.

From `SPY260911P00767000`, the put entered at 10:36 ET on 2026-09-11, solved from nothing but
SPY's price and the option's recorded bid/ask:

```
      ET      SPY    mid   spr      IV   delta   gamma   vega  theta/d
10:16:31   765.08   2.39  0.02   15.3%  -0.739  0.1089  0.064    -2.03
12:16:53   765.41   1.81  0.02   12.3%  -0.793  0.1477  0.045    -1.78
14:09:26   765.70   1.38  0.01   10.4%  -0.870  0.1836  0.024    -1.59
15:15:31   764.91   2.10  0.01   16.2%  -0.967  0.0654  0.005    -1.37
```

Read the columns as a story. Vega falls from 0.064 to 0.005 — by 15:15 the market's opinion
about future movement barely matters, because there is no future left. Delta marches toward
−1.0 as the put goes deeper in the money. Theta of $1.20-2.50 a day on a $1.40-2.80 contract
means the whole contract, every day.

### Where the money actually went

Between 10:16 and 14:09, SPY went from 765.08 to 765.70 — **up 62 cents, essentially flat.**
The put went from $2.39 to $1.38, a loss of about a dollar:

```
  SPY moving against the put   ~ -$0.50     delta
  the market getting calmer    ~ -$0.22     vega    (15.3% -> 10.4%)
  the clock                    ~ -$0.35     theta
                               ----------
                                 ~ -$1.07   (actual: -$1.01)
```

**About 22 cents — 9% of the contract, more than half a 15% stop — was the market simply
getting quieter, with the underlying going nowhere.**

This is the decomposition worth running on every trade. "We lost money" is not actionable.
"We were right on direction and lost anyway, because we entered at 15:40 and held 20
minutes" is.

---

## 6. Rules of thumb

- **Compute `SL / (SL + TP)` before deploying anything.** That is the win rate required to
  break even. See `docs/negative-expectancy.md` — it is the rule this project learned the
  hard way.
- **A percentage stop on premium is not a fixed distance.** The same 15% is a 10 bp move in
  SPY at delta 0.60 and 17 bp at delta 0.85. Convert stops to underlying moves before judging
  whether one is tight or loose.
- **Compare the stop to how far the underlying normally wanders.** SPY moves about 26 bp in a
  typical 30 minutes. A stop closer than that is measuring noise, not being wrong.
- **Deeper in the money is better on every axis except cost.** Less clock tax, less exposure
  to a calmer market, a wider effective stop. It just ties up more cash per contract.
- **Time of day is a risk parameter, not a preference.** The same trade at 10:00 ET and 15:30
  ET is two different trades.
- **The websocket carries no greeks.** Only `quote` and `trade`, price data only. Greeks come
  from REST (`get_option_chain(..., greeks=True)` or `get_quotes([sym], True)`), or are solved
  for from a recorded price as in §5.
- **An option already has a stop built in.** Maximum loss is 100% of premium, known at entry,
  free, and immune to noise. A tight premium stop replaces that with a barrier inside the
  noise band that pays the spread every time it fires.

---

## 7. Glossary

| Plain | Real term |
|---|---|
| real value | intrinsic value |
| betting money / time value | extrinsic value |
| the market's movement forecast | implied volatility (IV) |
| expected movement collapsing | IV crush |
| gain per $1 of underlying | delta |
| how fast delta changes | gamma |
| the clock tax | theta |
| cost of a calmer market | vega |
| expires today | 0DTE (zero days to expiration) |
| sellers are paid more than movement delivers | the volatility risk premium |
| average result per trade | expectancy |
| how far price normally wanders | standard deviation / sigma |
| one hundredth of a percent | basis point (bp) |

---

## Related

- `docs/negative-expectancy.md` — the stop/target arithmetic, and how it was learned
- `scripts/cost_budget.py` — computes break-even and stop-room per hour and per delta
- `BRAINSTORM.md`, "What the greeks mean, and which ones this book can act on" — the
  decisions this feeds, and worked examples per value
- `TODO.md` C1 / C2 — recording the data this reference is derived from

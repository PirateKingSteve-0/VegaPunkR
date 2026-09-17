# TO DO

Items are grouped into work-streams so related changes can be tackled together. Within each stream, sub-items are ordered by sequence (A1 before A2, etc.).

**How to read this file** (structure tidied 2026-09-09):

| Section | What it holds |
|---|---|
| **A–I** | Open work only. A struck-through heading here means the item is *mostly* done and the remaining part is named in the heading. |
| **FUTURE CONSIDERATIONS** | Not scheduled. Things to promote into A–I when a trigger fires. |
| **RESOLVED** | Fixed items whose write-up carries an argument worth keeping — the reasoning behind a change, and in several places a "this was measured, do not undo it" note. Item numbers are unchanged, so `E1`, `D3` etc. still resolve. |
| **DONE** | One-line summaries of everything else that shipped. |

Nothing is deleted when it is finished — it moves down the file. `BRAINSTORM.md` holds the decisions that shaped a design; this file holds the work.

---

## A. Cash Reservation Ledger (T+1 / GFV protection)

Single subsystem at two scopes. **A1 must finish (probe runs cleanly against live sandbox traffic) before A2 scoping makes sense** — production-hardening decisions depend on knowing the probe-validated baseline behavior and the actual deployment topology.

### A1. Sandbox probe run + reservation correctness *(code complete 2026-05-05, pending sandbox run)*

We need a way to track T+1 on day trading cash that way we cannot execute trades for money we don't have access to and acrue penalties for. Cash-only account, so GFV is the real constraint — three violations in 12 months and the broker restricts to settled-cash-only for 90 days. Took the strict approach: never use unsettled funds. In-process pending-buy reservation ledger layered on top of Tradier's `cash.cash_available`; reservations released when orders reach a terminal broker state. Sandbox-vs-live fee parity handled with a per-contract fee buffer in non-prod envs (Tradier sandbox returns commission/fees as 0). See journal 2026-05-05 (Part 2).

- **Remaining:** run `api/debug/probe_buy_reservations.py --user-email <x> --strategy-id <id> --option-symbol <occ>` against real sandbox traffic to confirm reservations correctly subtract under concurrent signals; verify against a live preview probe so we know `cost`/`order_cost`/`commission`/`fees` line up with what we assumed; refine `SANDBOX_FEE_BUFFER_PER_OPTION_CONTRACT` once a few live trades produce real `Trade.commission`+`Trade.fees` rows.
- **Process rule:** any change to `OrderManager._preview_or_abort` or the reservation methods (`_acquire_buy_reservation`, `_release_buy_reservation`, `_active_reservations_total`, `_purge_expired_reservations`) requires re-running the probe before the change is considered safe to deploy. The probe is the only thing that proves the cash gate still serializes concurrent buys correctly — reading the diff isn't enough.
- **Production blind spots — see A2 for full hardening list.** Probe passing in dev means the logic is correct *within a single process*; multi-worker / cross-process concurrency is a separate concern that the probe cannot cover.

### A2. Production-safety hardening for the reservation ledger

The ledger (`OrderManager._pending_buy_reservations`) is a Python dict in process memory. The current design works for a single-process deployment (sandbox / single-container dev) but has known blind spots for production scale:

- **Multi-worker race:** if the API is ever run with multiple worker *processes* (gunicorn `--workers N`, multiple uvicorn workers, multiple containers behind a load balancer), each has its own dict — Worker A's reservations are invisible to Worker B. Concurrent buys for the same user routed to different workers can both pass the cash gate, and we're back to the GFV-violation risk the ledger was supposed to prevent. Same-process asyncio tasks ARE safe (single shared dict, no `await` between check and acquire); same-process threads ARE safe (GIL makes dict ops atomic); cross-process is the gap.
- **Fix options when we get there:** (a) sticky routing — pin all of a user's strategy traffic to one worker; (b) move the ledger to Redis with per-user keys + atomic INCR/DECR; (c) DB-backed ledger with row-level locking. Redis is the typical fit for this shape of problem.
- **Restart wipes ledger:** the dict empties on process restart. Any orders in flight at that moment lose their reservation. Tradier's `cash_available` still tells the truth post-restart so we don't over-spend, but during the restart window the race protection is gone. Acceptable for human-managed restarts; would need to be fixed for a true 24/7 deployment with rolling restarts.
- **Preview ≠ fill:** the gate validates against `cost` from Tradier's preview. Actual fills can differ (slippage, partial fill, contract becoming untradeable between preview and place). Not a ledger issue — but "probe passes" does not equal "no possible cash mismatch ever."
- **Investigate first:** before designing the fix, confirm the actual production deployment topology — how many workers? Single gunicorn container? Multi-replica K8s? Until that's known, we don't know whether multi-worker is a real risk or just hypothetical. If single-worker is the deployment posture today, this is a future-readiness item, not a current bug.

---

## B. Order Execution Quality (entry & exit price drift)

Both items measure "signal price vs realized price" — just on different sides of the trade. They share `system_events` instrumentation and the same analysis lens (drift distribution → break-even threshold), so the schema and tooling should be designed once. **B1's investigation will naturally produce the exit-drift logging that B2 needs**, so do them in this order.

### B1. SPY 0DTE exits drifting past SL on fast moves (and others firing prematurely)

> **2026-08-31 — exit-drift logging is now WIRED.** `close_position` takes a `signal_price` and
> hands it to the preview, and the emit site in `_preview_or_abort` no longer skips sells. Exits now
> log `ORDER_PREVIEW_DRIFT` with `side='sell'`, so both halves of the measurement exist. The
> forced-exit-without-a-price path passes `None` — there is nothing to compare there.
>
> `order_cost`'s sign on a SELL is **undocumented** (`docs/tradier/trading/preview_order.md` shows
> only a buy). The per-contract figure uses the magnitude and `event_data.order_cost_raw` carries
> the signed value, so the convention can be read off the first real sells instead of assumed.
>
> **ANSWERED 2026-09-02 (live): a SELL comes back NEGATIVE.** Buys `+329 +424 +295`,
> sells `-411 -530 -252`. Magnitude is the per-contract cost; the sign encodes direction.
> Exit-drift numbers can now be trusted. See `docs/live-test-results-2026-09-02.md` §F4.
>
> **2026-09-09 — first exit-drift distribution, n=14 live sells.** Thirteen of fourteen land within
> **±2.1%** of the signal price. The fourteenth is the outlier this item was opened for:
>
> ```
> 09-09 11:00 ET  SPY260909P00766000   signal 2.20   preview/fill 2.01   -8.6%
> ```
>
> That is a stop-loss on strategy 4. The signal fired at −16.7% from a 2.64 entry, which implies
> about **−$44**; the fill booked **−$62**. Roughly **$18 of the loss on that contract is slippage
> between trigger and fill**, not stop distance — exactly the "late exit on a fast move" mechanism
> described below, now with one live instance instead of zero.
>
> **One data point. Do not retune anything on it** (E3's caution applies unchanged). What it does
> buy is a shape to test against: if the distribution stays 13-in-14 tight with an occasional −8%,
> the fix is a marketable-limit on SL exits to cap the tail, not a change to `_EVAL_INTERVAL` or to
> the bid-vs-mid choice — both of which would move all fourteen to fix one.
>
> The categorisation work (cluster exits by reason) is still open.

Observed 2026-05-07 — some SL exits realized at ~50% loss when the configured SL was tighter, while others felt premature. Traced two compounding causes:

- **Late exits:** SL signal evaluates against the option **bid** (`strategy_executor.py:382`); the exit then submits as a market sell (`order_manager.py:342`). On a fast SPY 0DTE drop, price keeps falling between trigger and fill, so realized loss exceeds the trigger %. Compounded by `_EVAL_INTERVAL = 1s` (`stream_driven_worker.py:40`) dropping ticks — by the next allowed eval the bid can already be several % past the threshold.
- **Early exits:** bid-based eval on a wide bid/ask fires SL at a worse-than-mid loss; trailing-stop snap on a transient bid spike (peak_price pinned high) and the account `trading_window_end` cutoff are also suspects.
- **Investigate first:** categorize today's SPY exits — `position.avg_entry_price`, `Trade.exit_price`, `position.peak_price`, exit `Signal.reason` (`strategy_executor.py:423-427`), wall-clock time. Cluster by reason to see how much is slippage vs. 1s-debounce vs. trailing-snap vs. window-cutoff before changing anything.
- **~~Add exit-drift logging while you're here.~~ DONE 2026-08-31, and producing data.** `close_position` passes `signal_price` and the emit site no longer skips sells. Verified 2026-09-09: prod holds **28** `ORDER_PREVIEW_DRIFT` rows against 14 buys and 14 sells — both legs of every round trip. The distribution is in the note at the top of this item.
- **Possible fixes (after data):** switch SL eval to `(bid+ask)/2` or `(bid+last)/2` instead of bare bid; make `_EVAL_INTERVAL` adaptive (tighter on fast tape); convert SL exits from market to marketable-limit to cap slippage (risk: may not fill in a true gap).

### B2. Preview-based cancel rule for entry drift *(LIVE DATA IN — probably not needed, see 2026-09-02)*

> **2026-09-02 — the first live fills say the drift was a sandbox artifact.** All six previews of
> the live session:
>
> ```
> buy   3.27  -> 3.29   +0.61%      sell  4.09 -> 4.11  +0.49%
> buy   4.225 -> 4.24   +0.36%      sell  5.29 -> 5.30  +0.19%
> buy   2.94  -> 2.95   +0.34%      sell  2.51 -> 2.52  +0.40%
> ```
>
> Range **0.19%–0.61%** — versus −9% to −12.8% on sandbox 08-27 and +20% to +83% earlier. Exactly
> as the 08-31 note predicted: the old distribution was measuring the sandbox↔live price-universe
> gap, not slippage. On live, preview and signal agree to well under a percent.
>
> **There may be nothing here to cancel.** Do NOT build the cancel rule on this evidence — a
> threshold tuned to sandbox noise would reject good entries. Revisit only if live drift ever
> exceeds a few percent, and size the sample first (n=6 is not a distribution).
> See `docs/live-test-results-2026-09-02.md` §F5.


> **2026-08-31 — the dataset cannot answer this question, and no code change unblocks it.**
> 851 usable events since 07-14 give a symmetric distribution (p5 −46%, p50 −1.7%, p95 +63%) that is
> 20–40× the ~1% spreads actually observed. Symmetric and huge is not what slippage looks like.
>
> The reason is the one already recorded under FUTURE CONSIDERATIONS: in `paper` mode
> `get_client()` returns the **sandbox** client, so `preview_per_contract` and the fill are both
> sandbox numbers while `signal_price` is a **live** streamed mid. The drift is measuring the
> sandbox↔live price-universe gap, not market slippage. (Preview matches the sandbox fill to a
> median 0.0% — that is sandbox agreeing with itself, not evidence of accuracy.)
>
> **B2 needs live fills.** Same wall as strategy evaluation. Do not pick a threshold off this data —
> a +20% rule would have cancelled 31% of entries for a reason that has nothing to do with the market.

We need to figure out if we need to preview orders before execution. Whether that would be for slippage or for possible reconsideration in executing a trade for true TP defined. Important clarification: previews already run for buying-power validation (see `_preview_or_abort`); this item is specifically about whether to ALSO use preview output to **cancel** a signal when the preview-vs-signal price drift means the trade no longer pencils out. Per-strategy equity curves now exist (DONE 2026-05-09 Part 5), so the cross-strategy realized-vs-modeled comparison the cancel-rule decision was waiting on is unblocked — pending only that a few weeks of `ORDER_PREVIEW_DRIFT` events accumulate.

- **Data collection in flight:** entry-drift is now logged on every option buy as a structured `ORDER_PREVIEW_DRIFT` event in the system_events table. `event_data` carries `signal_price`, `preview_per_contract`, `drift_pct`, `drift_dollars`, `qty`, `option_symbol`, `order_cost`. Observation only — no cancel logic yet, no behavior change. After a fewN weeks of trading there will be a real drift distribution.
- **Threshold framing when the time comes:** arbitrary % drift is one option (easy, but the % is a guess). Economic break-even (`target_profit_at_new_price - 2 × fees - expected_exit_slippage ≤ 0`) is the right one once we have the inputs — the trade is no longer net-positive in expectation. Decide after the data lands.
- **Exit-drift counterpart lives in B1** — once that logging is wired, the same analysis applies symmetrically.

---

## C. Standalone

### C1. Backtesting feature *(spec 2026-09-14 — Phase 0 is urgent and unblocked)*

> *Original note:* "We need to add a feature for backtesting data. What im thinking is what if we
> were able to use an available api call from tradier or a different broker to be able to help us
> collect data and test strategies. We could make it so when backtesting we can give params or
> constraints such as account size or other things to see how it might behave based on different
> things?" Equity curves landed 2026-05-09 (DONE) — backtest results can share the chart shape and
> overlay against live performance.

**Requirement added 2026-09-14: local-use tool. It may ship to prod, but must not be reachable by
any other account.** See "Access" below — that requirement only binds Phase 2, and Phase 2 may
never be needed.

#### The data is perishable, and that reorders the whole item

Tradier's intraday history has a hard horizon (`docs/tradier/market/time_and_sales.md`):

```
  interval   depth (open)   depth (all)
  tick          5 days         n/a
  1min         20 days        10 days
  5min         40 days        18 days
```

`/v1/markets/history` **does** accept OCC option symbols
(`docs/tradier/market/historical_pricing_security.md`) — but it returns *daily* OHLC, which for a
0DTE contract is a single bar covering its entire life. It cannot order a stop against a target, so
it cannot backtest an intraday exit.

`/v1/markets/timesales` **does** return intraday option data — measured 2026-09-15, not inferred.
Both `interval=1min` and `interval=tick` return 200 with real rows for an OCC symbol, inside the
20-day / 5-day horizons above. **The earlier claim here that option intraday history is entirely
unrecoverable was too strong.** What it returns is still not a substitute for a chain snapshot:

- **Trade prints only — no bid, no ask.** Exits evaluate on the **bid**
  (`strategy_executor.py:562`), so a trades-only series cannot say what a position could have been
  sold at. That is the optimistic-bias mistake with a receipt already in this repo.
- **No greeks, no IV.** The ORATS block is bolted onto the chain and quote endpoints only.
- **Sparse.** `SPY260916P00718000` — the highest-volume contract in the 09-16 chain, 57,489 — returned
  **34 of 390 one-minute bars, 9% coverage.** Quieter strikes return nothing at all.
- **Parse `timestamp`, never `time`.** The same print came back as `09:41:00` at `interval=1min` and
  `13:41:29` at `interval=tick`; the epoch fields agree, the strings do not.

**Consequence, narrowed: what expires is the trade tape, and the trade tape is partial anyway. What
was never available at any horizon — and so can only ever be collected live — is the bid/ask across
all strikes, and the greeks.** There is no historical-chain endpoint:
`/v1/markets/options/chains` takes `symbol`, `expiration` and `greeks` and nothing else, so it can
only ever answer *right now*. We hold zero option quote history beyond the ~6 contracts a session's
stream happened to watch. Every session that passes without a collector is a session whose chain is
gone.

`docs/tradier/market/option_chains.md`: chains carry greeks and `bid_iv`/`mid_iv`/`ask_iv` (ORATS)
when `greeks=true`. That is the measured IV and delta the 2026-09-14 cost budget currently has to
*assume* at 35%, and it is one request per expiration per snapshot.

#### Phase 0 — chain snapshot collector. Do this first, before any tool exists.

A standalone script under `scripts/`, no engine coupling, no DB, no router. Polls the 0DTE chain for
the traded symbols with `greeks=true` every 15-30s through the session, writes gzipped JSON next to
the tick logs (`data/backtest/chains/SYMBOL_chain_YYYY-MM-DD.json.gz`). Bound it to a strike window
around spot (+/-10) so one request covers the whole snapshot; confirm the market-data rate limit
before choosing the interval.

This is cheap, it is unblocked, it touches nothing in `api/engine/`, and it is the only part of C1
with a deadline. **It also immediately upgrades `scripts/cost_budget.py` from an IV assumption to a
measurement**, and supplies the option-chain snapshots `BRAINSTORM.md` 2026-09-11 names as the
reason implied volatility was left off the candidate list.

#### Phase 1 — local CLI backtester. No API, no UI, no access-control problem.

Productise `scripts/replay_session.py` rather than rewriting it: it already replays a session
against stop / target / trail / entry-window / cooldown / max-per-day and sweeps them. Four things
it needs:

1. **A pluggable price source.** `synthetic` (Black-Scholes from the underlying tick log, IV
   supplied — the pricing core already exists in `scripts/cost_budget.py`) or `recorded` (Phase 0
   snapshots). **Every synthetic result must be labelled synthetic in its own output.** Constant IV
   cannot show a volatility collapse, and this book only ever buys premium, so a constant-IV
   backtest flatters the strategy in precisely the direction that has never been measured.
2. **The settled-cash ledger.** F3 says settled cash is the binding constraint and caps the account
   near three trades a day. A backtest that ignores T+1 will report round trips the account could
   never have funded, and will overstate the trade count — which is the number every expectancy
   figure is divided by. This is the "account size as a constraint" idea from the original note, and
   it is not optional decoration.
3. **A cost model taken from measured data, not assumed.** Entry drift 0.19-0.61% (09-02 F5); exit
   drift 13 of 14 within +/-2.1% with one -8.6% outlier (B1). `replay_session.py`'s docstring already
   admits it is optimistic by roughly half the spread; make that an explicit, tunable term and report
   results at 1x / 2x / 4x friction.
4. **The real gates, not a copy of them.** Drive `SignalGenerator.check_entry_signal` /
   `check_exit_signal` directly with an injected clock, the way `api/tests/test_bar_aggregation.py`
   already does with no network and no DB. A backtester that reimplements the entry logic tests the
   reimplementation — and G3 (`ema_period: 9` meaning nine *seconds*) is exactly the class of bug a
   second implementation hides instead of finding.

**Hard boundary: the backtest path must never import `order_manager` or `trading_client_manager`.**
Execution is a stub that applies the cost model. Nothing under C1 goes near order placement.

#### Phase 2 — API + UI. Optional, and last.

Only if the CLI proves insufficient. The measuring work all happens in Phase 1; a web view adds
presentation, not evidence.

**Access, when and only when Phase 2 happens.** Layered, same shape as the rest of the app:

- **`User.can_backtest` boolean, default False**, as the sole source of truth — consistent with how
  per-user settings already work here (no env fallback, no role invention). Adding it is a
  `models.py` change, so **migrate DEV and PROD before the edit**; `reload=True` means a model save
  hits the shared DB immediately.
- **A new `require_can_backtest` dependency in `api/auth.py`** on every backtest route. Do *not*
  reuse `get_current_active_admin`: admin is deliberately observe-only and shared, and this is a
  per-account capability, not a role.
- **`BACKTEST_ENABLED` env flag gating whether the router is mounted at all**, default off. Belt and
  braces — with it off the routes 404 in prod regardless of any DB flag. This is a deployment
  switch, not a user setting, so it does not conflict with the rule above.
- **UI hides the nav entry unless the flag is set.** The dependency is the security boundary; the
  hidden nav is the UX boundary.

#### Sequencing

Phase 0 today (perishable data). Phase 1 next — it is what answers "does the entry work", and it is
where E11's sample-size problem gets solved by replay instead of by waiting 70-115 sessions. Phase 2
only on demand.

### C2. ~~Subscribe to `summary` and `timesale` — and filter the router by type~~ *(DONE 2026-09-15 — capture only, nothing consumes them yet)*

**Landed 2026-09-15**, both halves, exactly as specced below:

- `tradier_stream_manager.py:157` — filter is now
  `["trade", "quote", "summary", "timesale"]`.
- `stream_router.py:23,80` — `_ROUTED_TYPES = frozenset({"trade", "tradex", "quote"})`
  and a type guard in `dispatch` ahead of `put_nowait`. That set is exactly what was routed
  before, so the trading path sees the identical message stream it saw on 09-14.
- `api/tests/test_stream_router_type_filter.py` — new, 10 checks, pins BOTH halves: the two
  new types never reach a strategy **or** UI queue, and `trade`/`tradex`/`quote` still do.
  A future widening of `_ROUTED_TYPES` fails this test on purpose.

**Operationally: `LIVE_TEST_LOGGING=1` is now load-bearing.** `_lt_emit_stream` early-returns
when `is_enabled()` is false, so starting prod without the flag subscribes to both new feeds
and records **nothing** — all of the bandwidth, none of the data. `docs/monday-runbook.md`
already carries it; do not drop it.

Checked and unaffected: `scripts/replay_session.py` filters positively
(`if '"kind": "quote"' not in line: continue`), so the new log lines are skipped rather
than misparsed. Expect ~110 MB/session instead of ~60.8 MB.

**`timesale` is recorded UNSAMPLED on purpose — the cost was measured, not assumed (2026-09-16).**
A review flagged it as a hazard: `_lt_emit_stream` samples `quote` to 1/symbol/2s but passes
`timesale` through, and `JsonlLogger` writes line-buffered under a global lock **on the websocket
read coroutine** — the same loop that feeds the option quote the exit path prices against. The
reasoning was sound; the magnitude was not. Benchmarked at the real volume (167,078 records, the
09-11 trade count, same record shape):

```
  4.6 us per record   0.77 s per whole session   0.003% duty cycle
  worst case, a 500-print burst: 2.3 ms of that second
```

So it stays unsampled, and **sampling it would be actively wrong**: `quote`'s 1-per-2s rule is
*time*-based, which over-weights quiet minutes — fatal for the ask-side ratio this feed exists to
count. If write pressure ever does need cutting, sample **1-in-N prints** (unbiased for a ratio),
never 1-per-interval. Re-measure on the machine prod actually runs on if that changes, the way F3
insists for its own 23 ms.

**Two of the websocket's five payload types are free, unused, and each answers a question another
TODO item is currently trying to infer indirectly.** The change is small; the *safe* version of it is
two files instead of one, and the difference matters because the naive version adds pressure to a
queue that silently drops ticks the exit path needs.

#### What we subscribe to now, and what exists

`tradier_stream_manager.py:149` sends `"filter": ["trade", "quote"]`. Tradier offers five
(`docs/tradier/streaming/ws_market_data.md:31`), and the complete field list of each is documented —
**none of the five carries greeks**, so this is not a route to delta/theta/vega. What the two unused
ones do carry:

```
summary   → open, high, low, prevClose
timesale  → exch, bid, ask, last, size, date, seq, flag, cancel, correction, session
tradex    → same shape as trade (extended-hours variant) — not wanted
```

#### Why each one is worth having

**`summary` — an authoritative session range, and prior close.** `StrategyMarketState.apply()`
accumulates `session_high`/`session_low` from ticks, which is only correct if the worker was
watching from the bell. A worker that starts or restarts at 09:50 has a partial range and **no way to
know it** — the exact quiet-wrong-answer failure the ORB section of `BRAINSTORM.md` names as the
reason stream-only range computation is not enough on its own. With `summary` the engine can compare
its accumulated high/low against the exchange's and either correct itself or refuse to trade a range
it knows is incomplete. `prevClose` arrives in the same message and is the prior-levels candidate
(BRAINSTORM 2026-09-11, candidate 3) for free.

**`timesale` — aggressor side, which upgrades the volume gate from "how much" to "which way."**
`min_volume_multiplier` can tell that a minute was busy; it cannot tell whether buyers were paying
the ask or sellers were hitting the bid. `timesale` carries bid and ask *alongside* each print, so
that ratio is directly countable. A breakout on 70% ask-side prints is buyers chasing; the same
volume at 30% is sellers unloading into a pop. It also carries `cancel` and `correction` flags —
**the volume gate currently counts busted prints as real** — and a `session` flag separating regular
hours from pre/post.

It is also the honest measurement B1 wants. B1 infers fill quality from preview-vs-fill drift;
`timesale` gives the prevailing bid/ask at the moment of each print.

**REST is not a substitute — different product, same name.** `/markets/timesales` with
`interval=tick` returns `{time, timestamp, price, volume}` and **no bid/ask** (verified 2026-09-14),
so it cannot give aggressor side. Worth knowing separately: `interval=1min` returns OHLCV **plus the
exchange's own vwap**, a free cross-check on the VWAP the engine accumulates itself. And **parse
`timestamp`, never `time`** — the epoch fields agree across intervals, the strings do not
(`interval=tick` returned `14:00:00` for a 10:00 ET query; `1min` returned `10:00:00`).

#### Behaviour change from subscribing alone: none

Traced 2026-09-14, all three layers already tolerate unknown types:

- `StrategyMarketState.apply()` (`stream_driven_worker.py:135`) branches on `trade`/`tradex`/`quote`
  and has **no else** — anything else falls through untouched.
- The entry-signal check (`stream_driven_worker.py:408`) fires only on `trade`/`tradex` for the
  underlying.
- The recorder (`tradier_stream_manager.py:43`) logs **any** type generically by name, so both land
  in `stream-*.jsonl` with no recorder change.

So nothing needs writing for them to be captured, and neither can influence a decision.

#### The risk, and why the safe version is two files

`StreamRouter.dispatch()` (`stream_router.py:76`) routes **by symbol only — it does not filter by
type** — and each strategy queue is `asyncio.Queue(maxsize=100)` that drops on overflow
(`stream_router.py:84`, `pass  # drop stale tick rather than block`). `timesale` emits one message
per trade, so it roughly **doubles** trade-side traffic: 09-11 carried 167,078 trades, so expect
~167k more messages and a session log going from 60.8 MB to roughly 110 MB.

Added queue pressure on a queue that silently drops means **the dropped message could be the `trade`
tick the entry or exit needed**. That is the trading path, and research data is not worth it.

**The recorder runs BEFORE dispatch and independently** (`tradier_stream_manager.py:125-127`).
So the safe shape is:

1. `tradier_stream_manager.py:149` — add `"summary"` and `"timesale"` to the filter array.
2. `stream_router.py:76` — drop anything whose `type` is not in `{trade, tradex, quote}` before
   `put_nowait`.

Net: full capture in the logs, **zero** extra pressure on the strategy queues. Two small changes that
together are strictly safer than doing only the first.

#### Not in scope here

Consuming either one. `summary` correcting the session range and `timesale` feeding a
buy/sell-pressure gate are both behaviour changes to the entry path and want their own items, after
there is recorded data to measure against. This item is capture only.

---

## D. Daily gates & risk controls

Everything that bounds a *session* rather than a trade: the manual halt, the daily P&L caps, the
drawdown gate, and position sizing. D3/D4/D5 are fixed and have moved to **RESOLVED**.

### D1. ~~A standalone button so we can say hey we are finishing trading today~~ *(built 2026-08-31 — `flatten` still unexercised)*

"Done for the day" now lives on the Overview session card **and** the toolbar (reachable from
every page). Clicking it asks one question — what happens to positions that are already open:

- **`ride`** — new entries stop; open positions keep their stop-loss, take-profit, trailing stop
  and forced-EOD close. Nothing is sold.
- **`flatten`** — new entries stop **and** the forced exit is brought forward to now, so the engine
  closes everything at market on its next eval tick.

Account-wide (`User.trading_halted_on` + `trading_halt_mode`, migration `e6f4a2b8c1d7`), stamped
with the ET market date so it expires by itself at the next ET midnight — the same day boundary the
daily-loss cap uses. Resumable same-day; re-postable to switch mode.

`utils.market_hours.trading_halt_state()` is the single predicate; the risk manager reads it to
reject entries and the signal generator reads it to decide whether the forced exit is due, so the
two cannot disagree. Sells are never blocked. `flatten` is expressed as a bound on the forced-exit
*time* inside `forced_exit_time_et`, so it reuses the existing EOD close path — no new order path
was added, and nothing calls `place_order` from a router.

**Remaining:** never exercised against a live session. `flatten` in particular has only been tested
at the predicate level — the close it triggers is the well-worn forced-EOD close, but the trigger
itself has not fired on real market data.

### D2. Automatic daily profit target (the upside twin of the loss cap)

> **2026-09-09 — sized against live data, and demoted to second. See G2 and BRAINSTORM.md.**
> A target near +$150 would have helped over the 14 live round trips: it stops 09-02 after +$189 and
> 09-04 after +$167, saving the −$46 and the −$71 — roughly **+$436 instead of +$319**.
>
> But the two trades it saves are the 09-02 strike-roll re-entry and the 09-04 same-contract
> re-entry bought at 4.57 after selling at 4.50. **G2's rule catches the same two trades and names
> the cause**; D2 catches them by proxy — it stops because you have made enough, not because the
> entry is a chase.
>
> **The failure mode is also now visible:** on 09-09 the account was **−$19 on the day** before the
> final trade made **+$126**. A target-based halt can only ever end a day early, and the largest
> single trade in this dataset was the last one taken.
>
> Still worth building — it bounds the day, which G2 does not. Just build it *after* entry quality,
> and size the threshold off a real MFE distribution rather than off these five days.

Every daily-scoped gate today is downside-only: `_check_user_trading_halt`,
`_check_user_daily_loss_limit`, `_check_daily_loss_limit`. There is no upside equivalent, so the
engine keeps opening positions all session no matter how far ahead it is. `take_profit_pct` is
**per trade** — it closes one position at +30% and immediately hunts the next entry.

That asymmetry matters most on exactly the strategy we run: a scalper doing dozens of round trips
can give a good morning back by 3pm and nothing stops it. The 2026-09-01 paper session did 64
round trips in four hours.

D1's manual halt is the current substitute — `ride` mode banks the day by hand. This item is the
automatic version.

**Shape (deliberately mirrors the loss cap, opposite sign):** read `daily_profit_target_pct` off
the user row, compute `today_pnl` the same way `_check_user_daily_loss_limit` does (realized
`Trade.pnl` + unrealized, anchored to the ET market day via `market_day_start_utc()`), and block
`side='buy'` once it exceeds the target. **Sells stay open** — exits are sacred, and a position
open when the target trips must still reach its own stop/target/EOD.

**Do NOT build this the night before a live run.** Raised 2026-09-01 while prepping the 09-02 live
test and explicitly deferred: adding an untested gate to the entry path hours before the first
real-money session means debugging your own change instead of measuring fills. Build it once there
is live data to size the target against.

---

### D6. Position sizing does not scale with the account — acknowledge before the next band *(planning, 2026-09-07)*

Full write-up: **[docs/risk-bands.md](docs/risk-bands.md)**. Nothing implemented; this item exists so
the decision is made deliberately rather than on a market morning.

**The situation.** A $3.00 contract costs $300, which is **24.7% of the $1,214 account**. That was
never chosen — it is what the current settings happen to produce at this balance, and it goes wrong
in both directions as the balance moves. `max_contracts: 3` binds around $5,000 and never releases,
so exposure drifts from 24.7% down to **0.9% at $100k** by accident rather than by design. Today's
settings are roughly right between $5k and $25k and wrong at both ends.

**Two things that surprise everyone reading the sizing code:**

- `risk_per_trade_pct: 50` does **not** risk 50%. `SAFETY_FACTOR = 2.0` halves it — 50 deploys ~25%.
  The rule of thumb is `risk_per_trade_pct ≈ 2 × (target % of account per position)`.
- It is a `min()` of `risk_per_trade_pct` and the user's `max_trade_percentage`, both 50 today.
  **Changing one alone does nothing.**

**Size against the tail, not the stop.** The 15% stop is 3.7% of the account; the contract going to
zero is 24.7%. There are still no broker-side stops (TODO #1), 0DTE genuinely goes to zero, and a gap
never gives a simulated stop a price to fire at. The tail is the honest number.

**Proposed bands** (verified against `calculate_position_size` at a $3.00 premium — set
`risk_per_trade_pct` **and** `max_trade_percentage` together):

| band | account | risk pct | `max_contracts` | result |
|---|---|---|---|---|
| A | < $2,500 | 50 | 3 | 1 contract, 13–25% *(no choice available)* |
| B | $2,500–10k | 20 | 3 | 10.0% |
| C | $10k–25k | 10 | 6 | 4.5–5.0% |
| D | $25k–50k | 6 | 10 | 2.7–3.0% |
| E | $50k–100k | 4 | 15 | 2.0% |
| F | $100k+ | 2 | 25 | 1.0% |

**A band table alone does not bound risk** — this is the part worth carrying forward. The settings
cap the capital *allocated*, not the fraction of the account one position represents. Rerun band A at
a **$5.00** premium and the same settings produce **41.2%** of the account in one contract. The
companion is a new entries-only gate in `validate_pre_trade`:

```
reject when  qty × premium × 100  >  account_size × max_position_pct / 100
```

Sells never gated, a hard ceiling rather than a silent resize, carries a machine-readable `code` so
it joins the D4 alert and the Blocked badge. It only ever removes trades, so it composes cleanly.

**How to roll it out** — recommended order is (1) this doc plus a manual checklist, (2) a
`--dry-run` script that prints the band and the diff, (3) an advisory UI banner when
`account_size_usd` crosses a boundary. **Explicitly NOT** automatic sizing from a band table: it
makes position size change with no diff, no event and nothing to point at afterwards, and "why did it
buy 2 contracts today" would mean reconstructing a historical balance.

**Open questions carried in the doc:** whether `daily_loss_limit_pct` needs its own band column (5%
is $61 today and $5,000 at $100k), whether `max_positions` should rise above 1, and whether bands
apply per strategy or across the account — two strategies at 10% each is 20% deployed and nothing
currently checks the total.

---

## E. Exit rule structure *(from the 2026-09-02 live session)*

Full write-up: `docs/live-test-results-2026-09-02.md`.

### E2. Settled cash is the binding constraint, and the flat target doubles its consumption

> **2026-09-05 — the 214 wasted previews are fixed (results doc §S2).** `_preview_or_abort` now runs
> a settled-cash check BEFORE the broker preview, on buys only. Cash comes from a 60s cache
> (`SETTLED_CASH_CACHE_SECONDS`, invalidated on every fill), so the precheck costs no broker call of
> its own — it replaces 214 round trips with one balance fetch per minute.
>
> Deliberately permissive: the estimate omits commission/fees in prod, so it runs slightly LOW and
> lets marginal orders through to the authoritative gate, which is unchanged and still decides.
> Unknown price or unknown cash → proceed. **Sells are never gated** — a cash shortfall must not be
> able to strand an open position.
>
> Logging is state-based, not per-event: one WARNING + one `ENTRY_SKIPPED_NO_CASH` row on the way
> in, skips counted quietly, a total reported when cash returns. The count is the useful part — it
> is the evidence that cash, not the strategy, is the binding constraint.
>
> Tests: `api/tests/test_cash_precheck_gate.py` (17 cases, sell-never-gated first among them).
> Still open here: the reservation-ledger probe (A1) has never been run, and there is no end-of-day
> summary line if the block never clears before shutdown.

The 09-02 session generated **321 entry signals**, executed **3**, and produced **214 rejected
previews** (`Tradier preview rejected: You do not have enough buying power`). T+1 settlement on a
cash account: $1,060 settled at the open, $13.46 by 11:48 ET, proceeds unusable until the next day.

No GFV was incurred — every buy was funded from settled cash and the ledger reconciles to the
broker exactly (results doc §F3). But the ceiling is roughly **three trades per day**, and E1's
flat target spends two of them on one move.

**Two separate items follow:**

- **~~E2a. Stop previewing when out of buying power.~~ DONE 2026-09-05 — confirmed 2026-09-09.**
  The pre-preview settled-cash check (note at the top of this item) works, and the event counts say
  so cleanly: `ORDER_PREVIEW_FAILED` ran **450** on 09-02 and **478** on 09-04, then **0 on 09-08
  and 0 on 09-09**, replaced by a single `ENTRY_SKIPPED_NO_CASH` transition row per day. Roughly
  930 wasted broker round trips per two sessions, gone. Trading behaviour is unchanged, as intended
  — those orders were already being refused. **A1's probe still has never run**, so today's hard
  protection is still Tradier's check rather than ours.
- **E2b. Funding is a precondition for strategy measurement.** Three samples/day cannot support any
  read on win rate. Not a code change — a decision about whether the next test measures the
  strategy or measures the cash constraint again.

### E3. Do NOT retune the stop loss on 09-02 data

Trade 3 stopped at 2.50 (−15.5%); the contract recovered to 2.98 (high 3.13) by 12:00 and was back
to **2.50 by 13:00**. It reads as a shakeout at twelve minutes and as a correct exit at the hour.
One ambiguous trade. Listed explicitly so it is not quietly retuned.

### E13. ~~Every template ships a negative-expectancy stop/target pair~~ *(FIXED 2026-09-14)*

> **Fixed the same day it was found.** All eight templates now run a 1:2 stop/target, so every one
> breaks even at **33.3%**. The stop was set to each template's own `trailing_stop_activation` and
> the target to twice that, which keeps the wider stops on the more volatile names — the relative
> ordering the file already encoded, rescaled the way `min_volume_multiplier` was on 2026-09-10:
>
> ```
>   spy / qqq / aapl / meta / amzn   50/25 -> 15/30
>   amd                              45/30 -> 18/36
>   tsla                             40/30 -> 20/40
>   nvda                             40/35 -> 20/40
> ```
>
> SPY lands on exactly the 15/30 prod strategies 3 and 4 run, so the reference template and the live
> rows now agree. Both key spellings (`params_json.*_pct` and the `*_percentage` columns) were
> written together, all 32 values verified equal. `test_strategy_risk_field_sync` and
> `test_trailing_stop_arming` both pass; neither reads the templates, so this is coverage-neutral —
> **no test asserts on template defaults, and one probably should.**
>
> **Deliberately NOT changed: `delta_min` stays at 0.60 on all eight.** Raising it toward 0.85 is the
> other half of the cost-budget recommendation and it changes the capital profile (~$7.57 vs ~$3.89
> per contract, roughly halving trades/day against F3's cash ceiling). That is option 2 below and it
> still waits on E11. What follows is the original finding.

**The prod rows were fixed on 2026-07-13. The templates they were created from never were.** So the
default path still creates strategies carrying the exact defect `docs/negative-expectancy.md` was
written about, and that doc's rule — *"never deploy a strategy without computing SL/(SL+TP) first"* —
is violated by every template in `api/strategy_templates.py`:

```
  template                SL    TP    break-even win rate
  spy_0dte_scalping       50    25          66.7%
  qqq_0dte_scalping       50    25          66.7%
  aapl_0dte_scalping      50    25          66.7%
  meta_0dte_scalping      50    25          66.7%
  amzn_0dte_scalping      50    25          66.7%
  amd_0dte_scalping       45    30          60.0%
  tsla_0dte_scalping      40    30          57.1%
  nvda_0dte_scalping      40    35          53.3%
                                            ------
  prod strategies 3 and 4 (patched)  15/30  33.3%
```

**All eight have the stop wider than the target.** Not one is at the 33.3% the live strategies run.
`scripts/fix_strategy_expectancy.py` wrote the four keys and both columns on the *existing rows*; it
was never a template change, and nothing since has closed the gap.

**The dual-key trap is NOT present here** — worth recording, because it is the thing to check. Each
template writes `params_json.stop_loss_pct` and the `stop_loss_percentage` column to the *same*
value (verified 2026-09-14, all eight), so a template-born strategy does not reproduce the
2026-07-13 failure where the UI showed 15% and the engine enforced 50%. The values agree. They are
simply the wrong values. `trading_safeguards.py:54` rejects `stop_loss_pct` below 10, so every one of
these passes validation.

#### Why this is not a one-line fix to 15/30

`BRAINSTORM.md` 2026-09-14 computes what a percentage stop on premium actually costs: at
`delta_min: 0.60` — which all eight templates also set — a **15% stop sits 10.4 bp from spot, or
0.39 sigma of SPY's 30-minute move, and a driftless random walk touches it essentially 100% of the
time.** Copying 15/30 into the templates swaps a stop that needs an unreachable win rate for a stop
that fires on noise. Both lose; they lose for different reasons.

Three options, and the choice needs to be made once rather than per-template:

1. **Match prod (15/30).** Consistent, honest about what is actually being traded, and the defect
   above is then documented rather than hidden. Cheapest, and it at least stops shipping 66.7%.
2. **Derive the pair from the cost budget** — raise `delta_min` toward 0.85 and widen the stop so it
   sits past ~1 sigma. `scripts/cost_budget.py` produces the numbers per hour and per delta. More
   correct, and it changes the capital profile (~$7.57 vs ~$3.89 per contract), which collides with
   E2/D6 and F3's roughly-three-trades-a-day cash ceiling.
3. **Ship no default at all** — require SL/TP at creation and refuse to save without them, so the
   arithmetic is forced on whoever creates the strategy. Most defensible, worst onboarding, and it
   makes the templates much less useful as templates.

**Recommendation: 1 now, 2 after E11 has sample size.** *(1 was taken 2026-09-14, with the stop scaled per template rather than flat 15/30 — see the note at the top.)* Option 1 is a value change to eight dicts
with no behavioural surface beyond creation; option 2 needs the live data E11 is blocked on, and
picking a stop distance off four up-drifting sessions is exactly the retune E3 says not to do.

#### Do not do this quietly

Changing a template changes what *new* strategies get, not what the running ones use — the strategies
router merges `params_json` on update (`routers/strategies.py:290-296`) and nothing rewrites existing
rows. So this edit cannot disturb prod strategies 3 and 4, which is what makes it safe. It is still a
trading-parameter change and wants explicit sign-off before the edit, per CLAUDE.md.

### E6. Performance metrics we do not compute

Prompted by comparing our reports against Tradervue / Lightspeed (2026-09-02). We already have
`win_rate`, `profit_factor`, `sharpe_ratio`, `max_drawdown`, `total_pnl`, `net_pnl`,
`total_trades`, `commission`, `fees`, `cum_pnl` equity curve, per-strategy breakdown.

**Worth adding — computable from existing `Trade` rows, no schema change:**

- **Expectancy** — `(win% x avgWin) - (loss% x avgLoss)`. Best single-line summary of an edge.
- **Average winning trade vs average losing trade** (payoff ratio). Win rate alone misleads.
- **Largest gain / largest loss** — catches outlier dependence.
- **Hold time split by winner / loser.** The classic cut-winners/ride-losers tell. 09-02: winners
  6 and 14 min, loser 32 min — the same shape as the Tradervue reference (5 min winners, 8 min
  losers).
- **Max consecutive wins / losses** — position-sizing input.

**Needs E5 first:** average MFE / MAE, MFE capture ratio.

**NOT worth building yet:** SQN, K-Ratio, Kelly %, Probability of Random Chance, trade P&L standard
deviation. All need sample sizes unreachable at ~3 trades/day (the Tradervue reference has 1,709
trades over a year). They would render confident-looking noise. Revisit at a few hundred trades.

**Also low value now:** Lightspeed-style gross-vs-net with a fee breakdown (Reg Fees / Fee Cost /
Other Fees). Tradier reports commission and fees as `0` even on live, and real fees are ~$0.18 per
contract inferred from cash reconciliation — see the results doc.

### E7. Deep-ITM puts structurally cannot clear the OI floor *(2026-09-03; measured across all sessions 2026-09-16)*

> **MEASURED 2026-09-16 — this is not a put problem, it is THE binding gate on both sides.** Every
> `No suitable contracts` line in `logs/livetest-*/engine-*.log`, parsed. The scan's counters are
> **sequential** (`stream_driven_worker.py:1210-1230`): a contract reaches `low OI` only after it has
> already passed the delta band, so that counter is in-band contracts lost to the floor alone.
>
> ```
>   calls   3,696 failed scans   OI was the last blocker in 3,608  (98%)
>   puts    1,002 failed scans   OI was the last blocker in 1,002 (100%)
>   in-band contracts lost per scan: 2 to 8
> ```
>
> Whole sessions sit unarmed this way: 09-09 (771 call scans), 09-10 (674), 09-14 (677), 09-15 (674).
>
> **Every contract ever armed clusters just above the line** — lowest armed is **3,054** (put) and
> **3,495** (call) against `min_open_interest: 3000`. The gate is not selecting liquidity, it is
> selecting whatever survived it. Meanwhile **the spread gate rejected zero contracts in every
> session recorded**, so the liquidity risk the floor exists to prevent is already being checked
> directly, and nothing fails that check.
>
> **The reframe, and why "just lower it" may be the wrong fix: open interest is the PRIOR day's
> settlement count.** On a same-day expiry it says nothing about today — a 0DTE strike can show OI of
> 500 and trade 50,000 contracts before noon. `min_open_interest: 3000` is longer-dated-options
> logic, where OI is a fair liquidity proxy. For 0DTE, today's **volume** and the live **spread** are
> the measures, and the spread gate is already passing everything.
>
> **What is missing to pick a number: the OI values of the rejected contracts are not logged, only
> the count.** Two ways to get them, neither done: (a) one log line in the scan loop recording the OI
> of delta-passing rejects — engine file, log-only, no behaviour change; (b) C1 Phase 0 chain
> snapshots, which give OI, volume and spread per strike and answer "should this gate be volume or
> spread instead" at the same time.
>
> **A replay cannot answer this.** OI decides which contract is ARMED, and only armed contracts have
> recorded quotes — so a lower floor buys a strike with no price history to replay. Same wall C1
> documents. Owner parked the decision 2026-09-16; do not change the floor without (a) or (b).

The put strategy has now run two live sessions and **entered zero trades**. On 09-03 it rejected
its contract scan **329 times**, always the same way:

```
181 puts scanned: 179 wrong delta (need 0.6-0.85), 0 no ask, 0 spread too wide, 2 low OI
closest to target: strike=770.0 delta=0.688 (SPY260903P00770000)
```

Only two puts fell in the delta band, and both failed `min_open_interest: 3000`. Verified against
the live chain the same hour:

```
PUTS  in band            CALLS in band
P00774000  OI =    1     C00772000  OI = 6,443
P00775000  OI =    8     C00771000  OI = 7,815
                         C00770000  OI = 8,005
```

**The OI reading was accurate** — this is not a data bug.

**Why it is geometric, not incidental.** A put at delta 0.60-0.85 is deep in the money, which means
a strike ABOVE spot. SPY sat at 771.76, so the band lands on 774/775 — strikes SPY had not traded
at that day, where no interest has accumulated. Calls at the same delta sit at 770-772, exactly
where price has been all session, so they carry thousands of contracts.

**Consequence:** deep-ITM puts only accumulate OI at strikes the underlying has already *fallen
from*. So the put side cannot arm on a rising day at all, and on a falling day can only arm once
the decline is well established. **The strategy is late to the put side by construction.** The
09-02 session is the counter-example that proves the mechanism: SPY had been at 764+ earlier, so
the 765/766 puts carried OI 3,186 / 7,728 and did qualify.

This is the delta-band-vs-OI tension already noted for calls (see the defaults item below), now
shown to be *asymmetric* — it bites the put side far harder.

**Do not change the floor on this.** It was set deliberately and the user has asked for research
before adjusting it. Recorded so the decision is made on evidence:

- Measure how often, across a month, ANY put clears both gates — is the put strategy usable at all
  at these settings, or is it dead weight burning eval cycles?
- If the answer is "rarely", the lever is the delta band, not the OI floor: a 0.35-0.55 band sits
  nearer the money where OI actually lives, on both sides. That is a different strategy, not a
  cheaper version of this one — it needs its own backtest.
- Cheap interim: log a daily one-liner of best-in-band OI per side, so the distribution accumulates
  without anyone watching for it.

### E12. `check_market_regime` is declared on every strategy and read by nothing *(2026-09-08)*

A full audit of all 32 `params_json` keys against the engine (`api/engine/`, `api/routers/`,
`api/services/`, `models.py`, `schemas.py`) found exactly three with no reader:

| key | status |
|---|---|
| `max_position_size_usd` | **resolved 2026-09-08** — enforcement added at `risk_manager.py:302`, applied last so it beats the "at least 1 contract" floor. Every strategy set to `None` (no cap) by `scripts/null_position_size_cap.py`; all 8 templates now seed `None`. Covered by `tests/test_position_size_cap.py`. |
| `avoid_economic_news` | **not a lie** — in flight. `docs/econ-calendar.md` states plainly "nothing consumes it yet", and BRAINSTORM.md carries the design. |
| `check_market_regime` | **this item.** No reader anywhere, and no design written down. |

**Keeping the key deliberately.** A regime filter is wanted; the flag records that intent and both
live strategies set it `True`. But until this is written, `check_market_regime: True` is a claim the
system does not honour — anyone reading the config (including a future session of Claude, which is
how this was found) will reasonably believe a regime check is gating entries. It is not. Nothing
about entry selection currently considers whether the market is trending, chopping or reverting.

Documented rather than deleted, following the `avoid_economic_news` precedent: an unimplemented
flag is honest as long as the gap is written down somewhere the reader will find it.

- Decide what "regime" means for a 0DTE momentum book before writing any code. Candidates: SPY vs
  its own opening range, realised vs implied vol, VIX level or term structure, breadth (the `tick`
  plumbing already exists but `use_tick_indicator` is `False` on both strategies).
- Note the interaction with E7: the OI floor already appears to starve whichever side is
  counter-trend on a given day (2026-09-03 blocked puts, 2026-09-08 blocked calls, both times the
  side the VWAP rule was rejecting anyway). A regime filter may partly duplicate an effect the
  system already has by accident. Measure that before adding a second one.
- Whatever lands must compose as a *narrowing* gate on entries only, never on exits.

### E8. Consider a tiered (tightening) trailing stop *(idea — needs data first)*

A fixed 10% trail hands back 10% of the **peak price**, so the give-back in P&L points grows with
the size of the move:

| peak | realised | handed back |
|---|---|---|
| +66% | +49% | ~17 pts *(the real 2026-09-04 trade)* |
| +100% | +80% | 20 pts |
| +200% | +170% | 30 pts |

A tiered trail — e.g. 10% up to +50%, 7% to +100%, 5% beyond — would bank more of a big run while
leaving normal trades alone.

**Do not build this yet.** There is exactly ONE big winner on record (09-04, peak +66%). Tuning an
exit rule on n=1 is how the retracted 31%-win-rate analysis happened.

**The blocker is already lifting:** E5 now writes `mfe_price` / `mae_price` onto every closed
trade, so each round trip records how far it ran before turning. After a few more live sessions
the MFE distribution answers this directly — what fraction of trades exceed +50%, +100%, and how
much a tighter band would have cost the ones that did not. Revisit then, with the distribution,
not with an intuition.

Related: `take_profit_pct` is inert whenever `trailing_stop_activation <= take_profit_pct`, which
is the current config (15 vs 25). Raising the target to 50/75/100 changes nothing. Note that
`trading_safeguards.validate_strategy_params` rejects `take_profit_pct > 100` — dead code today
(nothing calls `check_pre_trade_safeguards`) but a landmine if it is ever wired up.


### E14. Exit shadow mode — RUNNING since 2026-09-16, read the results *(observation only)*

**Live, acts on nothing.** `api/engine/exit_shadow.py`, hooked into
`strategy_executor._check_exit_signals` in three places: `observe()` on every priced tick *before*
the real exit decision (and handed nothing about it), and `on_exit()` inside both confirmed-close
branches, plus `note_underlying()` beside `_update_history` on every tick. It watches six alternative
exit rules on every open position — keep 70%, keep 50%, volatility trail, dynamic take profit, dynamic
take profit + live trail, and (since 2026-09-17) the **structure stop** — and records when each *would*
have sold. The structure stop builds its own 1-minute underlying highs/lows from the price the engine
already sees each second (`_BARS`, capped at 240 bars per symbol). Output: an INFO `SHADOW EXIT` line the first time a rule would sell, a
`SHADOW SUMMARY` line on each real close, and one record per close in
`logs/livetest-<date>/exit_shadow-*.jsonl` (when `LIVE_TEST_LOGGING` is on). Rules still holding at the
real exit are recorded `open`, never flat. `ENABLED = False` in the module turns it off.

**Why it exists:** `docs/dynamic-exits-math.md` §7 replayed all 28 real round trips under these rules.
**No profit-side rule beat the live rule like-for-like** (keep 70% −$4 / TP+trail −$15 across all days).
**The structure stop did, +$31** — but only by exiting three losing trades earlier, +$23 of it one
trade whose trigger cleared the stop by 5¢. Its shadow version agrees with the replay on 26 of 26
resolvable trades. Every idea
there — including E8's tiered trail — was generated by the same trades it was measured on. Shadow
mode gathers evidence on trades the analysis has not seen, with no exit-path risk.

**It already caught a real bug.** Run over all 28 real trades, the module disagreed with
`scripts/dynamic_exits_review.py` on 6 of 128 rule/trade pairs. The script measured volatility
*including the minute of the decision* — prices from after the entry. That look-ahead manufactured an
apparent "+$45 edge" for TP + trail, all of it from one trade (09-09 11:01: $4.60 vs an honest
$4.00). Script fixed (completed minutes only); the two now agree on **128 of 128**. The +$45 claim is
retracted in the doc.

**Safety, pinned by `api/tests/test_exit_shadow.py`:** the module contains no order, preview, DB or
network call; `observe`/`on_exit` swallow every exception; `observe` precedes the real decision and
is not handed it; both `on_exit` calls are owned by `if ...result.success:` branches; nothing reads its
return value. Plus rule-by-rule correctness on synthetic prices.

**Known gaps:**
- State is in memory. A restart mid-trade starts a fresh snapshot flagged `late` (delta, volatility
  and the dynamic target then describe the restart moment, not the entry).
- Delta is only used when the streamed contract *is* the held one; otherwise a 0.70 default, flagged
  `delta_known: false`.
- It does not see closes that happen outside the executor's exit loop (reconcile, manual); those
  snapshots are pruned after a day.

**To do:**
- [ ] After ~2-3 weeks of live trades, collect the `exit_shadow-*.jsonl` records and compare each rule
      to the real exit on the same trades — the only evidence not generated by the 28-trade sample.
- [ ] Only then decide whether any rule (or E8's tiered trail) earns a selectable exit mode.
- [ ] If it ends up worth keeping long-term, consider persisting the entry snapshot so restarts don't
      produce `late` records.

### E11. Re-run the edge analysis at adequate sample size *(BLOCKED on n — do not judge the strategy before this)*

**Trigger: ~62 closed round trips for a first read, ~126 for a confident one.** At ~3 trades/day
that is roughly 21 and 42 trading days from 2026-09-04. Do not re-litigate "is the strategy good"
before the first threshold — the answer cannot be computed, and looking early invites tuning to
noise.

#### Week-one baseline, locked in for comparison (2026-09-02 -> 09-04, PROD, live money)

```
 id  date        strat kind  entry   exit      pnl    ret%   exit reason
  2  2026-09-02  s3    CALL   3.27   4.11   +84.00  +25.7   Take profit
  4  2026-09-02  s3    CALL   4.23   5.28  +105.00  +24.8   Take profit
  6  2026-09-02  s3    CALL   2.96   2.50   -46.00  -15.5   Stop loss
  8  2026-09-03  s3    CALL   2.36   1.97   -39.00  -16.5   Stop loss
 10  2026-09-03  s3    CALL   2.16   1.82   -34.00  -15.7   Stop loss
 12  2026-09-04  s4    PUT    2.88   3.02   +14.00   +4.9   Trailing stop
 14  2026-09-04  s4    PUT    2.97   4.50  +153.00  +51.5   Trailing stop
 16  2026-09-04  s4    PUT    4.57   3.86   -71.00  -15.5   Stop loss

n=8  win rate 50%  total +$166  expectancy +$20.75/trade
avg win +$89  avg loss -$47.50  payoff 1.87x  profit factor 1.87
sd $82.87  se $29.30  t=0.71  (needs ~2.36 at n=8)
95% CI for the true per-trade edge: -$48 to +$90     <- contains zero
equity $1,060 -> $1,214 (+14.5%)
```

#### Why week one proves nothing, and what to guard against repeating

- **The CI contains zero and contains -$48/trade.** t=0.71 is a coin flip. "Positive after a week"
  is not evidence of an edge.
- **One trade is 92% of the profit.** Without t14 (+$153) the week is +$13 over 7 trades. Check
  outlier dependence again next time — if the result still rests on one or two trades, n is still
  too small regardless of what the count says.
- **The 8 trades are TWO rule sets, not one.** The trailing-stop fix (E1) landed mid-week:
  pre-fix 09-02 = +$143 over 3; post-fix 09-03/04 = +$23 over 5. Pooling them is wrong. **Going
  forward, segment by exit-rule version** — and note the OLD logic produced the better days, so
  "the trail is better" is also unproven.
- **It contradicts the 8-day replay** (114 signals: calls 32% right, puts 42%, both
  anti-predictive). One good week does not overturn that; it is exactly the variance that study
  predicts. If the larger sample disagrees with the replay, work out WHY before believing it.

#### What to compute when the sample arrives

- Expectancy with a confidence interval; win rate, payoff, profit factor.
- **MFE capture ratio** (realised / MFE) — available from the next session onward now that E5 has
  shipped. This is the number that says whether the exit rule leaves money behind, and week one
  had to be argued from a single surviving row.
- **MAE distribution on losers** — how often does a stopped-out trade later reach +15%? That is
  the real test of the stop distance, and the question E3 refused to answer on two data points.
- Split by direction (call vs put) and by strategy id — s3 and s4 traded on different days in week
  one, so nothing about their relative quality is known.
- Hold time split by outcome, and exit-reason mix (TP / SL / trail / EOD).

#### Standing caution

Established after four live sessions: the **machinery** (0% decision-vs-fill mismatch, sane holds,
no phantom adoptions, correct T+1 settlement, no GFV). The **edge** is not established. Keep those
two claims separate in any write-up.

### E9. `strategy_type` is load-bearing, and three places disagree about it *(2026-09-06)*

The engine decides whether it is sizing **options or shares** by string-matching the strategy type:

```python
_is_options = any(k in strategy.strategy_type.lower() for k in ('option', '0dte', 'scalping'))
```

`risk_manager.py:282` picks the sizing formula (`capital / (price * 100 * 2)` vs `capital / price`);
`strategy_executor.py:303` picks whether to size off the option premium or the underlying. Measured
on the live account ($1,214.25, 50% risk, $3.00 contract):

| `strategy_type` | position |
|---|---|
| `scalping_0dte` / `momentum_0dte` | **1 contract** (~$300) |
| `momentum` | **3 contracts** (~$900) — the share formula reads "$3.00" as $3, computes 202, and only `max_contracts: 3` stops it |

**The sizing logic would ask for $60,600 of options on a $1,214 account.** What actually protects
you is the `max_contracts` cap and Tradier rejecting for buying power — not the sizing code.

A third site, `trading_safeguards.py:79`, matches on **`'option'` alone**, which
`scalping_0dte` never contained and `momentum_0dte` still does not. So the delta-band config check
has never run on these strategies. Doubly disconnected: the function it lives in
(`validate_strategy_params`) is also dead — nothing calls `check_pre_trade_safeguards`. Left alone
deliberately; wiring up an untested all-or-nothing gate before a live session is the wrong trade,
and it would still not match. Note their configured band is `delta_min 0.6 / delta_max 0.85`, inside
the validator's `[0.30, 0.90]`, so enabling it would change nothing anyway.

**The real delta protection is NOT dead** and never was: `stream_driven_worker.py:1217` rejects any
contract outside the configured band at selection time, and `:1523` drops an armed contract that
drifts out.

Done 2026-09-06: strategies renamed to `momentum_0dte` (sizing verified byte-identical before and
after), `MOMENTUM_0DTE` added to the UI `StrategyType` enum with a warning comment, and a hint added
to the strategy form. Before that, `momentum` was in the dropdown and `momentum_0dte` was not —
picking the obvious option would have tripled position size silently.

**DONE 2026-09-06 — the instrument is now a stored fact.** `strategies.instrument_type`
(`'option' | 'equity' | NULL`), migration `b7c3d9e4f2a8`, applied and backfilled on **dev and prod**.
Read through a single `Strategy.trades_options` property, so the question has one definition next to
the data instead of two independent string matches. Both call sites (`risk_manager.py:283`,
`strategy_executor.py:303`) now call it.

`NULL` is load-bearing: it falls back to the old string match, so a row this has never touched
behaves exactly as before. The change therefore cannot alter behaviour for unmigrated data — it can
only make it more correct. Verified against live prod: both strategies resolve `trades_options=True`
and size to 1 contract, byte-identical to before.

Tests: `api/tests/test_instrument_type.py` (24 cases) — the stored fact overriding the name, the
NULL fallback reproducing every legacy answer, and every non-options type in the UI dropdown sizing
correctly once the fact is recorded.

Deliberately NOT exposed on `StrategyCreate` / `StrategyUpdate` — the form cannot clobber it.
Instead the **model defaults to `'option'`**, so a strategy created through the API or the template
cloner is never born NULL. Leaving new rows NULL would have let the guessing behaviour back in
through the front door for anything created from here on. Not derived from `strategy_type` at
creation either: that reproduces the original footgun, storing `'equity'` for anything named
"momentum". An equity strategy has to say so explicitly. Wire a selector into the form if a real
equity strategy ever exists.

The NULL fallback in `trades_options` stays as defence in depth — a manual insert, a restored
backup or a future migration could still produce one, and 0 of 5 rows are NULL today.

`trading_safeguards.py:79` still matches `'option'` alone and still never fires — left alone
because the function it lives in is dead (nothing calls `check_pre_trade_safeguards`) and the
contract-level delta check in `stream_driven_worker.py:1217`/`:1523` is the one that actually runs.
If that validator is ever wired up, switch it to `strategy.trades_options` first.

**Also found:** `alembic/env.py:25` reads `DATABASE_URL` and ignores `APP_ENV` entirely, so
`APP_ENV=prod alembic upgrade head` silently migrates **dev**. Caught only by verifying the column
afterwards. Migrating prod requires `DATABASE_URL="$(grep '^DATABASE_PROD_URL=' .env | cut -d= -f2-)"`.
**Fixed 2026-09-06:** `env.py` now mirrors `database.py` — `APP_ENV` selects
`DATABASE_{DEV,PROD,TEST}_URL`, an unknown `APP_ENV` raises rather than guessing, `DATABASE_URL`
remains a last-resort fallback, and it **prints the target before running anything**:

```
[alembic] APP_ENV=prod -> DATABASE_PROD_URL -> ...rds.amazonaws.com:5432/vegapunkr_prod
```

Host and database name only; credentials are never printed. Related: the engine holds `strategies` open
`idle in transaction`, so DDL needs the app stopped; running with `PGOPTIONS='-c lock_timeout=5000'`
makes it fail fast instead of queueing and blocking every reader (same hazard as the 271-second
`trades` hang recorded in JOURNAL).

### E10. Four "tests" cannot fail *(2026-09-06)*

`scripts/run_tests.sh` now labels these **SMOKE** rather than PASS, and excludes two more from the
commit gate entirely. Recorded so the labels are not mistaken for a runner quirk.

**No assertions — they print observations and always exit 0, so they fail only on a crash:**

- `test_market_hours` — a demo script printing example usage. Not a test.
- `test_position_contract_isolation` — prints what the contract lookup does; useful as a
  diagnostic, proves nothing automatically.
- `test_api`, `test_database` — see below.

**Excluded from the gate because they need live services:**

- `test_api` — HTTP against `localhost:8000`; red whenever the engine is stopped.
- `test_database` — connects to the real RDS instance.

Gating commits on those would mean a failing suite every time the app is down, and a gate that
fails for unrelated reasons gets bypassed and then ignored. `--all` runs them deliberately.

**Worth doing eventually:** give the two diagnostics real assertions, or move them out of
`api/tests/` so the directory means "things that gate a commit". Until then the honest count is
**13 real tests**, not 17 — and 17 was the number that looked reassuring before this was checked.

**Also removed 2026-09-06:** `test_worker_integration.py`, which imported
`services.strategy_worker` — a module that no longer exists and is referenced nowhere. It had been
failing on an unrelated `SessionLocal` -> `SessionLocals` rename, which is exactly the stale-test
rot the gate now prevents.

### E4. Decide the fate of the stale-quote guards

The exit-path guard (landed 08-27) was written against a misdiagnosis that the 09-02 live session
disproved — exits were never mispriced; sandbox fills were fabricated. It is harmless but unearned
and adds a REST call to the exit path.

The entry-path guard (landed 08-31) also never fires: across 321 live signals, quote age was
`0s` x280, `1s` x38, `2s` x3 — maximum 2 seconds against a 30-second threshold. Belt-and-braces,
not load-bearing.

Also: `api/tests/test_stale_stream_quote.py` was deleted 2026-09-01 and never restored, so the
exit-path guard currently has **no test**. Either restore the test or remove the guard; do not
leave an untested branch in the exit path.

---

## F. Broker routing & environment

F1 (the account stream watching the wrong account) is fixed and has moved to **RESOLVED**.

### F2. A trading-mode switch needs a process restart — and a UI banner will not survive the move to a server *(2026-09-07)*

`TradierAccountStreamManager` resolves its account **once**, when the socket connects, and holds
it for the life of the process. Order routing follows the paper/live toggle within ~30s (the
worker re-reads the user row each loop), so after a mid-session switch:

```
orders  -> new account, within ~30s
stream  -> OLD account, until the process restarts
```

Degraded, not dangerous: fills confirm over the 30s REST poll, which is the documented fallback
and how everything ran before F1. But it is exactly the protection F1 restored, silently absent
again.

**Stopgap shipped 2026-09-07:** the environment controls show a dismissible warning after a mode
switch telling the user to restart the engine.

**Why that stopgap expires.** It assumes the person clicking the toggle can restart the process —
true only while the engine runs on the same laptop as the browser. Once prod (and likely dev) move
to a server, EC2/ECS or otherwise, the UI has no idea the engine exists and no way to restart it.
The banner then instructs someone to do something they cannot do, which is worse than no banner.

**Real fix, needed before the server move:** the stream must re-resolve its account when the mode
changes, rather than relying on a human. Options, roughly in order of preference:

- **(a) Reconnect on change.** The worker already re-reads the user row every loop and calls
  `db.refresh(user)`. When `selected_trading_mode` differs from the account the stream connected
  with, tear the socket down and reconnect through the provider. The manager already records
  `_env_label` / `_account_label`, so the comparison is cheap and needs no new state.
- **(b) Reject the switch while positions are open**, restarting the stream on the next flat tick.
  Safer, more annoying, and it does not remove the human step — it moves it.
- **(c) Refuse mode switches from the UI entirely** once the engine is remote, making the mode a
  launch flag like `--env`. Most honest for a server deployment: the process gets pinned to an
  account the way it is already pinned to a database.

This interacts with the single-instance rule: the engine cannot scale horizontally (cash ledger,
settled-cash cache, throttles and unconfirmed-order map are all in-memory class state), so a
server deployment is one pinned process anyway. That argues for **(c)**, with **(a)** as the
fallback if the UI toggle must keep working.

### F3. The engine's per-tick DB read costs 23ms, and all of it is wire time to us-west-1 *(2026-09-15)*

**Measured, not estimated.** The `Position` lookup the worker runs on every eval tick
(`stream_driven_worker.py`, the "single source of truth" read that decides entry-vs-exit) against
the RDS instance, 60 runs, warm pool, from the machine prod actually runs on:

```
Position query      min 19.48ms   median 22.87ms   p95 29.15ms   max 30.79ms
raw TCP connect     min 20.70ms   median 23.20ms
```

**The query and a bare TCP handshake cost the same.** Postgres does ~0ms of work — the entire cost
is the round trip to `us-west-1`. So this is NOT a query problem: indexing it, rewriting the SQL or
caching the row would save nothing measurable. It is a "where does the process run" problem, and it
arrived with the RDS migration. Before RDS the same call was a local socket and was free.

**Why it blocks everything.** `database.py` builds a **synchronous** engine (`create_engine` +
`sessionmaker`), and the worker calls `db.query(...)` directly on the asyncio event loop.
`asyncio.to_thread` appears 8 times in `stream_driven_worker.py` and **every one of them wraps a
broker call, never a DB call**. So each 23ms freezes the whole loop: every strategy worker and the
websocket reader.

**Scale, stated honestly.** Evals are debounced to 1/second (`_EVAL_INTERVAL`), so this is one
query per second per strategy, not one per tick. At the 2 prod strategies:

```
2 strategies x 22.87ms = ~46ms/sec blocked  ->  4.6% duty cycle
```

Plus `db.refresh(strategy)` every 30s, a heartbeat `count()` every 30s, and reconcile every 60s.

**This is not losing trades, and should not be treated as if it were.** 23ms of buffered ticks is
absorbed by the socket buffer, and 23ms on a one-second exit check is irrelevant against 30-minute
0DTE holds. It is overhead. The engine rules forbid refactoring without a behavioural reason, and
4.6% is not one.

**The trigger to revisit is strategy count, because it scales linearly:**

```
2 strategies   4.6%
4 strategies   9.2%
6 strategies  ~14%
```

**Two real fixes, neither a one-liner:**

1. **Co-locate the engine with RDS in us-west-1.** Zero code. Collapses 23ms to sub-millisecond and
   deletes the item outright. This is the same move F2 is already planning for ("once the engine is
   remote"), so **F3 probably resolves as a side effect of F2 and should be sequenced behind it
   rather than fixed on its own.**
2. **Move the worker's DB access off the event loop**, if the engine stays outside us-west-1.
   Note the hazard: SQLAlchemy `Session` is **not thread-safe**, so `to_thread` cannot simply be
   sprinkled on individual calls while other code touches the same session on the loop. It needs the
   worker's DB access moved consistently onto a dedicated session — a refactor of the most
   safety-critical read in the loop, for a 4.6% win. Do not do this speculatively.

**Do not re-measure this from the laptop.** 23ms is Pacific-to-us-west-1 physics. The number is only
meaningful from whichever machine is actually running `APP_ENV=prod`.

---

## G. Entry selection *(from the 2026-09-09 prod review — 14 live round trips)*

Full write-up and the reasoning behind both items: **BRAINSTORM.md, "Entry is a state, not an event
— and the strike roll is where it costs"**. Nothing here is built. Both items are recorded so the
decision is made on evidence rather than on a market morning, and both are **blocked on sample
size** — see the caution at the end of G2.

Everything below is prod only (2026-09-02 → 09-09, live money). Dev is sandbox and its fills are
fabricated; the 2026-09-08 retraction of a dev-based re-entry finding stands.

### G1. The entry condition is a state, not an event — cash is doing the trade selection

`price_above_9ema_and_vwap` / `price_below_9ema_and_vwap` describe a condition that can hold for
hours, not a moment that occurs. So the instant a position closes the condition is still true and
the engine buys again — not because something new happened, but because nothing changed.

How long the engine kept **attempting** entries after its last executed trade of the day:

| Day | Last fill (ET) | Still attempting until (ET) | Executed | Blocked attempts |
|---|---|---|---|---|
| 09-02 | 11:15 | **15:43** | 3 | 450 preview-rejects + 141 throttles |
| 09-04 | 11:07 | **15:44** | 3 | 478 + 175 |
| 09-08 | 10:25 | **15:41** | 3 | 98 throttles |
| 09-09 | 11:01 | **13:39** | 3 | 53 throttles |

On 09-02 that is **5h21m** of continuous demand producing 3 trades. **Settled cash and the 5-second
throttle chose which 3 — the strategy did not.**

**Consequence that changes the order of work:** funding the account (E2b) does not fix this, it
*exposes* it. The T+1 cash ceiling is currently the only thing bounding trade count, so more capital
means more of exactly the entries this item is about. Whatever selectivity rule lands should land
before, or with, the funding decision.

Related: E12 (`check_market_regime` is declared and read by nothing) is the natural home for a
"should we be trading at all right now" filter; this item is the narrower "is *this* entry a fresh
setup" question. They compose but are not the same gate.

### G2. Re-entry on a rolled strike is 0 for 3 — and a blanket cooldown is the wrong lever

14 round trips, net **+$319**, 8W/6L (2 take-profit, 6 stop-loss, 6 trailing-stop exits). The
obvious cut says nothing: first-trade-of-day +$157 over 5, re-entries +$162 over 9. The cut that
separates is **whether the engine had to select a different contract**:

| Bucket | n | Record | P&L |
|---|---|---|---|
| First trade of the day | 5 | 4W-1L | **+$157** |
| Re-entry into the **same contract** | 6 | 4W-2L | **+$309** |
| Re-entry on a **newly selected strike** | 3 | **0W-3L** | **−$147** |

All three losers, three different days, both sides of the chain:

| Day | Rolled | After | Entry | Result |
|---|---|---|---|---|
| 09-02 | C760 → **C763** | SPY rallied, C760 ran 3.27 → 5.28 | 2.96 | −$46 |
| 09-08 | P773 → **P769** | SPY fell, P773 ran 5.72 → 6.27 | 2.72 | −$39 |
| 09-09 | P769 → **P766** | SPY fell, P769 ran 5.36 → 5.79 | 2.64 | −$62 |

**The mechanism is the delta band, and it is late by construction.** After a winning move the held
contract goes deep in the money, delta climbs past the 0.85 ceiling, and `_select_option_contract`
reaches for a strike back inside 0.60–0.85 — always further along the direction price *just
travelled*, at roughly half the premium. The engine ends up buying the continuation of a move that
already happened, at its point of maximum extension.

MFE confirms it. Both roll entries with excursion data peaked at +10–11%, never reached the +15% that
arms the trail, and reversed into the stop — while the *same contract* re-entered minutes later ran
to +22.8% and +59.4%:

| Trade | Best point (MFE) | Armed trail? | Outcome |
|---|---|---|---|
| 09-08 P769 (roll) | +11.4% | no | −14.3% |
| 09-09 P766 (roll) | +10.2% | no | −16.7% |
| 09-08 P769 (same contract) | +22.8% | yes | +13.4% |
| 09-09 P766 (same contract) | +59.4% | yes | +43.8% |

**This corrects the standing "re-entry cooldown after a stop-out" item** (FUTURE CONSIDERATIONS). A
blanket cooldown blocks the +$309 bucket along with the −$147: five of the six same-contract
re-entries came back within 90 seconds, including the +$153 and the +$126. **Pause on contract
*change*, not on elapsed time.**

**Cheapest testable shape, when the time comes:** after a strike roll, require price to re-establish
the setup before arming — minimum version, a touch back to the 9 EMA. It is an entry gate in
`stream_driven_worker`, so it composes most-restrictive-wins, only ever removes trades, and must
leave `side='sell'` untouched. Same-contract re-entries pass through unchanged.

**Do NOT build this yet — the sample cannot carry it.** The losing bucket is **n=3**; the winning
bucket's +$309 rests on two trades (+$153, +$126). The mechanism is legible and matches theory,
which is why it is worth building *around*, but E11's thresholds still govern: ~62 round trips for a
first read, ~126 for a confident one. Tuning an entry rule on n=3 is how the retracted 31%-win-rate
analysis happened. Also note the roll entries and the E7 open-interest starvation are the same
selector reacting to price history — measure whether a roll gate duplicates an effect E7 already
produces by accident before adding a second one.

**What to compute when the sample arrives** (all from existing columns — no schema change):

- Re-entry outcome split by *contract changed / unchanged*, with a confidence interval.
- MFE distribution for roll entries vs. all others. If roll entries systematically top out below the
  +15% activation, that is the number that justifies the gate.
- Time-since-prior-exit as a control, to confirm the separating variable is the contract change and
  not the gap. In this sample the two are confounded — fast re-entries were mostly same-contract.
- How often a roll entry would have been *avoided* rather than merely delayed by a 9-EMA touch
  requirement, i.e. what the rule actually costs in missed trades.

### G3. ~~`ema_period: 9` is nine SECONDS — and raising it past 100 deletes the gate~~ *(FIXED 2026-09-10 — warm-up seeding still open)*

> **Fixed 2026-09-10, committed in `902286f`.** Both parts of the fix shape below
> landed, and the live sessions on **2026-09-11 and 2026-09-14** ran on it (engine processes started
> after the 21:28 PT save on 09-10). `api/tests/test_bar_aggregation.py` pins it and passes.
>
> - **Bars.** `_update_history` folds ticks into 1-minute bars; only completed minutes reach
>   `price_history`, so `ema_period: 9` is nine minutes and `max_history_length = 100` is 100
>   minutes. Bar volume is differenced from the exchange cumulative counter (`cum_volume`), not
>   summed from sampled ticks. `volume_ratio` = last completed minute ÷ mean of the last 20.
> - **Fed unconditionally.** The update moved out of `check_entry_signal` into
>   `strategy_executor.execute_strategy_tick`, ahead of every gate, so indicators keep moving while
>   a position is open and during the re-entry cooldown.
> - **Missing indicator now blocks.** An EMA, VWAP or volume baseline that cannot be computed yet
>   returns no signal instead of silently skipping the gate — `ema_period > 100` no longer deletes
>   the filter. Entries only; exits untouched.
> - VWAP is still fed every tick, on purpose (measured fine, see trap 2).
>
> **Still open — the warm-up cost named under "Before building".** Nothing seeds history from
> Tradier historical bars. After any restart the strategy takes no entries for ~9 minutes (EMA) and
> ~20 minutes (volume baseline needs 20 usable bars). That is the safe direction — blocked, not
> ungated — but a mid-session restart now costs ~20 minutes of entries.
>
> **Does not change the verdict below.** The measurement further down already showed the repaired
> stack has no directional edge on this tape; the fix makes measurement trustworthy, it does not add
> an edge. G4 is no longer waiting on this item.
>
> Everything below is the original write-up, kept for the reasoning.

**Not a tuning question. The indicator does not measure what its name says.**

`stream_driven_worker._EVAL_INTERVAL` is **1 second**, and `signal_generator._update_history`
appends exactly one price per `check_entry_signal` call. So `price_history` holds one sample per
second and `ema_period: 9` is a **9-second EMA**. `max_history_length = 100` caps the whole buffer
at 100 seconds — under two minutes of history for every indicator built on it.

Measured against the recorded SPY tape (09-02, 09-08, 09-09; 6.5h each, 1s samples):

| | crosses spot | median distance from spot |
|---|---|---|
| **9-second EMA** (what runs today) | **11.9–12.2 / min** (~4,700 a day) | 0.17–0.18 bp |
| 9-minute EMA (what "9-period" implies) | 0.2 / min (~80 a day) | 1.46–1.47 bp |

The gate flips sides about every five seconds and sits ~0.17 bp from price. It is not a weak trend
filter — at 1 Hz evaluation it is satisfiable within essentially any minute, so it removes almost
nothing.

**This refines G1 rather than repeating it.** G1 reads the all-day demand as "the condition is a
state that holds for hours." The measurement says something narrower and more fixable: the EMA
*component* is near-random and near-always passable, so it contributes no selection at all. The
persistence G1 documents is real; the EMA is not the part providing it.

Directional test on the underlying — 1,010 distinct signal-minutes over 4 prod sessions (calls 502,
puts 508), deduped to one observation per minute per direction. Measured on **SPY**, not the option,
so it needs no option quotes and cannot be flattered by stop/target geometry:

| Rule | right at +15m | right at +30m |
|---|---|---|
| Current (9EMA + VWAP + volume) | 45.6% | **43.0%** |
| …calls only | 48.6% | 47.0% |
| …puts only | 42.7% | **39.1%** |
| *Baseline — long at any minute* | *51.0%* | *50.6%* |
| Opening Range Breakout (09:30–10:00) | 58.1% | **59.0%** |

Below a coin flip, and below simply being long. **Caveat: all four sessions drifted upward**, which
flatters anything long and punishes puts — a meaningful share of the put result is direction of tape,
not signal quality. Do not read 39.1% as "the put rule is broken" without a down-tape sample.

**Two traps that make this worse than it looks:**

1. **You cannot fix it by raising `ema_period`.** `_calculate_ema` returns `None` when
   `len(prices) < period`, and `check_entry_signal` **skips the EMA gate entirely when it is
   `None`**. With the buffer capped at 100, any `ema_period > 100` silently *removes* the filter
   instead of lengthening it — no log, no event, strategy still reads Active. Anyone reaching for
   `ema_period: 540` to get nine minutes gets no EMA check at all.
2. **The same buffer feeds VWAP and the volume gate — but they are NOT equally damaged.**
   `volume_ratio` = size of the last single trade ÷ mean of the last 20 sampled trade sizes, about
   20 seconds of history. That is tick noise, not a volume spike, and `min_volume_multiplier: 2.0`
   gates on it.

   **VWAP, however, measures fine — corrected 2026-09-10.** An earlier note here claimed the
   sampling made it "not VWAP". Measured against today's tape it does not:

   | VWAP version | value | vs best estimate |
   |---|---|---|
   | Engine (1 sampled trade/sec) | 758.559 | **+0.117** |
   | Every delivered stream event (~7/sec) | 758.545 | +0.102 |
   | Cumulative-volume weighted (closest to true) | 758.442 | — |

   **12 cents, about 1.5 bp**, and the `price < VWAP` gate returns the same answer as the
   cvol-weighted version **98.6%** of the time (846 disagreements across 61,904 trade events).
   Sampling is uncorrelated with price, so it is an unbiased estimator and the error averages out
   over thousands of samples. Note the stream itself only delivers ~37% of traded volume as
   individual prints, so *no* reconstruction from it is exact — the engine is already close to the
   best that feed supports.

   **This is the key distinction: the EMA problem is a TIMESCALE error, VWAP's is a sampling error.**
   A 9-second EMA is a different object from a 9-minute EMA, not a noisy version of one. A sampled
   VWAP *is* a noisy version of VWAP, and the noise is small. Do not spend effort "fixing" VWAP
   expecting a behaviour change.
3. **Both indicators FREEZE while a position is open.** `_check_entry_signals` returns early on the
   `max_positions` check (`strategy_executor.py:277`) and on the 30s `_check_reentry_cooldown`
   *before* calling `check_entry_signal` — and `_update_history` is the first line inside it. So for
   the entire duration of every trade, no price enters the deque and no volume enters the VWAP
   accumulator.

   Two consequences that matter:
   - The EMA's 9 samples can straddle the hole. Immediately after a 20-minute hold, the "9-second
     EMA" is comparing now against prices from 20 minutes ago, then collapses back to 9 seconds
     within nine ticks. **Effective lookback is a function of how long the last trade lasted.**
   - **Re-entry decisions are made inside that window.** This is a mechanism G2 did not have: the
     0-for-3 rolled-strike re-entries were each evaluated against an EMA polluted by the hold that
     had just ended. Check this before attributing that result solely to the delta-band roll.

   VWAP's gaps land on the periods active enough to have triggered an entry, which is not random —
   but given the 1.5 bp sampling error measured above, treat this as a correctness wart rather than
   a source of bad decisions until someone measures it costing something.

   It also **gets worse as the account grows** — cash starvation kept the strategies flat most of
   each session, so the holes were small. More funding means more time in a position means larger
   holes. Same shape as G1's warning about E2b.

**Measured 2026-09-10: the fix does NOT improve the signal.** Both stacks were rebuilt from the
recorded SPY tape and asked the same question — when you fire, does SPY then move your way? The
broken reconstruction lands at 44.0% hit at +15m against the live engine's 45.6%, which says the
reconstruction is faithful. The repaired stack (1-minute bars, VWAP from *every* trade, volume
compared minute-to-minute):

| `min_volume_multiplier` | signals / 4 sessions | per day | hit @ +15m | avg bps @ +15m |
|---|---|---|---|---|
| 1.0x | 498 | 124 | 45.9% | +0.02 (CI −0.72 to +0.75) |
| 1.2x | 224 | 56 | 46.0% | +0.49 (CI −0.67 to +1.64) |
| 1.5x | 76 | 19 | 46.4% | +0.37 (CI −1.49 to +2.22) |
| 2.0x (today's value) | **15** | **4** | 50.0% | +0.42 (CI −4.35 to +5.19) |
| *broken stack, for reference* | *1,869* | *467* | *44.0%* | *−0.27* |
| *baseline — long at any minute* | *1,725* | *431* | *51.0%* | *+0.32* |

At the thresholds with real sample size (498 and 224 signals) this is **tightly measured as no
edge**, not merely unproven — the CIs are narrow and centred on zero, and every row still sits below
simply being long. Repairing the timeframe produces *fewer signals of the same quality*, not better
ones. **The defect is in the implementation; the problem is in the premise.** Price-above-EMA-and-
VWAP does not predict SPY direction on this tape at either timeframe.

Caveat: 4 sessions, all up-drifting. A down-tape sample could read differently, and the concept is
not disproven in general — only measured as flat here.

**So fix it, but not for performance.** The reasons that survive: an indicator that does not mean
what its name says is a permanent trap for anyone tuning it; `ema_period > 100` silently deleting the
gate is a live footgun; and no future entry work (ORB, regime, trendlines) can be evaluated on a
buffer that samples once a second and stops during trades. It is foundation work, not an edge.

**Recalibrate `min_volume_multiplier` in the same change.** Today it compares ONE TRADE against 20
recent trades — individual trade sizes are heavily skewed, so 2.0x clears constantly (467 signal-
minutes a day). Barred, it compares ONE MINUTE against 20 recent minutes, and minute volumes barely
vary — 2.0x then clears **4 times a day**. Porting the number across unchanged silences the strategy
without anyone touching a setting. ~1.0–1.2x is the range that reproduces a comparable signal count.

**Fix shape:** two parts, and the second is not optional.
1. Bar `_update_history` into 1-minute candles (OHLC + summed volume per minute) and hold the deque
   in *bars*, so `ema_period: 9` means nine minutes, VWAP sums real per-minute volume, and
   `volume_ratio` compares a minute against recent minutes.
2. **Feed the history unconditionally**, from the tick path rather than from inside the entry gate,
   so it keeps updating while a position is open and during the re-entry cooldown. Barring alone
   still leaves holes the length of every trade.

Contained to `signal_generator` plus the call site that feeds it; changes no exit path and no order
path.

**Before building, three things to settle — this is a live entry-path change:**

- **Warm-up becomes a real cost.** A 9-minute EMA needs 9 minutes of bars. `entry_after_open_minutes:
  30` covers a clean start, but a **mid-session restart currently needs 9 seconds and would then need
  9 minutes** with nothing tradable in between. Seeding from Tradier historical bars
  (`docs/tradier/market/`) is the obvious answer and should land with the change, not after it.
- **The replay cannot validate this.** `scripts/replay_session.py` prices the contracts the engine
  actually armed; a different entry rule arms different contracts, and no quotes exist for those.
  This needs a paper session to generate its own logs, then a replay of *those*. Same constraint
  applies to ORB.
- **Both live strategies change behaviour at once.** Expect the signal count to fall sharply — the
  gate currently removes almost nothing. Fewer signals is the intent, but it interacts with G1/G2 and
  with E2b's sample-size problem: this makes samples *scarcer* while E11 is waiting on n.

**Sequencing.** Same note as G1: this belongs before, or with, the funding decision (E2b). Funding
does not fix a signal that tests below a coin flip; it buys more of it. But given the measurement
above, **do not let this item hold up entry-rule work** — repairing the buffer is a prerequisite for
*evaluating* a new entry rule, not a substitute for finding one. If effort is scarce, the ordering is:
fix the buffer (so measurement is trustworthy) → build a candidate rule with actual directional
information → measure it. Not: fix the buffer and expect the numbers to move.

**Do not treat the ORB row as a recommendation.** n=105 breakouts over 4 sessions, and its **+3.69 bp**
average edge at 30 minutes sits well inside the noise the stop is set against. Measured this session:
a 15% stop on a 10:00 ET contract (avg premium $3.47, delta ~0.70) needs SPY to travel **9.7 bp**
against you, while SPY moves **2.1 bp/min** at that hour — so the edge is smaller than one typical
minute of drift. ORB is the only rule measured so far whose directional information has a CI that
separates from zero, which makes it the first candidate worth *building to measure* — not a setting
to switch on.

**Related measurement worth recording** (same session, recorded tape): contract premium falls ~4x
through the day ($3.47 at 10:00 → $0.89 at 15:30) while SPY's movement only halves (2.1 → 1.2
bp/min). A **fixed** 15% stop therefore sits progressively deeper inside the noise as the session
runs — ~4.6 minutes of typical drift away at 10:00, ~2.1 minutes by 15:30. Relevant to E3 (do not
retune the stop on thin data) and to any future time-of-day entry gate: the stop distance is not
constant in the terms that matter, even though the number never changes.

Tooling for all of the above: `scripts/replay_session.py` (`--sweep window|close|stop|trail|target|
cooldown|losscooldown|maxday`, and `--verify` to check the replay against the fills that actually
happened). Baseline across 4 prod sessions, modelling the engine's own 30s re-entry cooldown:
**98 replayed round trips, 43.9% win rate, −1.40% expectancy per trade (−$110 per contract), 95% CI
−5.57% to +2.78%.** Eight sweeps have been run over that set; every one lands between −1% and −3%.
**No exit-side or throttle-side knob moves the result** — which is what points upstream to this item.

### G4. Candidate entry signals — measure on the tape first *(2026-09-11)*

Full reasoning: **BRAINSTORM.md, "Candidate entry signals — measure on the tape before building"**.
Nothing built. Sequenced behind G3 only because G3 makes the measurement trustworthy, not because
G3 is expected to improve anything (it was measured not to — see G3).

**The standing rule this item exists to enforce: a candidate gets measured against the recorded SPY
tape before any engine change.** A tape test costs ~20 minutes, needs no code and no money, and
needs no option quotes — it runs on the underlying, so it is not limited to contracts the engine
happened to arm, and the stop/target geometry cannot flatter it. Building first is how the current
three gates ended up testing below a coin flip (43.0% right at +30m against a 50.6% always-long
baseline).

Ordered by confidence, highest first.

**G4a. Relative volume by time of day.** *This one is a measured defect, not a hypothesis — the
highest-value item here.* SPY volume is a deep U (median/min: 97,052 at 09:30, **33,950 at 12:30**,
**122,316 at 15:30**). `min_volume_multiplier` divides by a rolling 20-bar baseline that lags the
steep parts of that curve: into the close it trails the ramp, so a typical 15:45 minute scores
**~2.2× with no spike at all** and clears a 1.5× gate on nearly every minute of the last half hour;
at the open the reverse suppresses ratios. **The gate is loosest late and tightest early**, which is
backwards — late is when contracts are cheapest and the fixed percentage stop sits deepest in noise
(see G3's premium-vs-volatility note). Fix: a per-clock-minute profile built from prior sessions
instead of a trailing window. Needs no new data; 8 sessions are on disk.

**G4b. Distance from VWAP rather than side of it.** *(MEASURED 2026-09-15 — BUILT AND LIVE on prod
3/4 since 2026-09-15; watching sessions is what remains)*
The gate is binary, so a penny above and 2% above pass identically. 2026-09-10 spent 97.6% of the
post-10:20 session blocked on it with price **$0.58** above VWAP.

**Result: price 0.5-2 "wiggles" past VWAP tends to come BACK, and chasing it is where the replay's
losses concentrate.** A wiggle is the volume-weighted standard deviation of price around VWAP since
the open (the usual VWAP-band construction). Full reasoning and the ideas around it: BRAINSTORM.md,
"VWAP distance — the rule chases, the tape pulls back". Numbers: JOURNAL.md, 2026-09-15.

- 20 sessions of SPY 1-min bars (`scripts/distance_test.py`): at 1+ wiggles, SPY moves **~3.0 bp
  back toward VWAP** over 30m once each day's drift is removed; shuffle test **p = 0.001**. Same
  direction in both 10-day halves.
- 138 replayed trades (`scripts/distance_trades.py`): entries **1-2 wiggles** past VWAP in the
  trade's direction — **27 trades, 22% won, -10.4% avg, -$534** per contract, more than the whole
  strategy's -$425. Spread over 6 of 7 days, calls and puts both.
- Replay with a **1.0-wiggle block**: ~~**-$425 -> -$54**~~ — **CORRECTED 2026-09-15, do not cite
  -$54.** That number is a POST-FILTER: it deletes the blocked trades from the baseline list and
  keeps the rest. Re-running the strategy with the gate *in the loop* — where a block leaves the
  strategy flat and a later signal takes the freed slot — gives **-$425 -> -$183 on this same 8-day /
  138-trade sample** (09-02..09-14, excluding 09-15). `scripts/replay_session.py --all --max-stretch
  1.0` can now model the gate; the -$425 baseline reproduces to the dollar. The ~$130 difference is
  the replacement effect this section's own note predicted. Win rate 44.9% -> 48.6% was also
  post-filter.
  **Every stretch number here must name its sample.** The two in circulation are the same measurement
  on different spans: the 8-day / 138-trade one above, and the full **9-day / 146-trade** one
  (**-$405 -> -$163**) once 09-15 is included. The whole difference is that one session: 8 trades,
  +$20, unaffected by the gate. Subtract it and the 9-day figures become the 8-day ones exactly.
- **The replay does NOT calibrate the threshold.** Per-day attribution: of the +$242 total benefit
  (on the full 9-day / 146-trade sample, -$405 -> -$163), **+$245 comes from 09-10 and 09-11 alone**;
  the other seven days net -$3. Two of nine sessions carrying 100% of an effect is too fragile to
  calibrate a threshold on, whatever the cause. **This is a sample-size objection, not a data
  objection** — see the next bullet, which retracts an earlier claim that it was the latter.
- 📍 **DIAGNOSED 2026-09-15 — the "wiggle divergence" on 09-10/09-11 was a CORRUPT REFERENCE FILE,
  and an earlier version of this bullet blamed the wrong thing twice.** The 0.69-vs-1.24 and
  0.58-vs-2.44 figures come from the REBUILD CHECK in `scripts/distance_trades.py`, which compares
  **two minute-bar constructions** — our stream rebuild against the Tradier 1-minute file's per-bar
  `vwap` field. Neither side is `engine_wiggle`, so those numbers were never evidence about the
  engine's accumulator, and they are not evidence of a mid-session restart either (there are none;
  see below). The actual defect is in the reference: **a bar's VWAP must lie inside its own
  [low, high], and in `data/backtest/underlying/SPY_1min.json` it frequently does not** —
  1.3% of bars on 09-02 rising to **11.5% on 09-10 and 10.5% on 09-11**, with max |vwap-close| of
  **$7.68 on 09-11, a day whose entire close range was $2.61**. The corruption rate tracks the
  apparent "divergence" exactly: 09-02 at 1.3% bad → wiggles agree (1.16 vs 1.15); the two ~11% days
  → they blow apart. **Our stream rebuild is the sound side**: its bar closes match the file's to a
  mean absolute error of **$0.003 on all 9 days**, total volume to 1.00x, price range exactly, 390
  bars with zero empty minutes. So `session_wiggle` — built from our bars — is trustworthy, and the
  -$163 stands as a measurement.
  **Consequences:** (a) FIXED 2026-09-15 in both consumers — `distance_test.py` and the REBUILD CHECK
  in `distance_trades.py` now read **`price`**, not `vwap`. **With the corrupt field out of the
  comparison the divergence vanishes entirely**, which is the cleanest confirmation in this whole
  thread that our rebuild was always the sound side: 09-10 at 10:30 goes 0.69-vs-1.24 -> **0.69 vs
  0.72**, 09-11 at 15:00 goes 0.58-vs-2.44 -> **0.58 vs 0.56**, and the daily VWAP disagreement drops
  from a $0.006-$0.570 spread to **$0.002-$0.016** across all 9 days. The replayed-trade statistics are
  byte-identical before and after, because they were always built on our bars. Use **`price`**
  (`typ = b.get("price") or b["close"]`): it is the bar MIDPOINT — verified `price == (high+low)/2`
  exactly on 3510 of 3510 bars — so it is a standard typical price (HL2) and less endpoint-biased than
  `close` on a trending minute. Note its in-range-ness is *tautological*, not a validation: a midpoint
  cannot fall outside its own [low, high]. **The drift result is robust to all three conventions**,
  which matters more than the choice: +30m gives -1.54 bp / p = 0.000 on the corrupt `vwap`,
  -1.63 / p = 0.000 on `close`, -1.65 / p = 0.000 on `price` (+15m: p = 0.007 / 0.005 / 0.004).
  Three typical prices are now in play — HL2 from the file, mean-of-prints from our stream rebuild,
  and whatever the engine's per-tick sampling effectively yields; name which one is meant wherever a
  wiggle is quoted. (b) The REBUILD CHECK's label "wiggle ours vs file" reads as ours-being-wrong; it is the
  file that is wrong, and it should say so. (c) **The 24-session drift test SURVIVES the fix** —
  re-run with `typ = b["close"]` it gives **-1.63 bp, p = 0.000** at +30m against -1.54 bp / p = 0.000
  before (and p = 0.005 vs 0.007 at +15m), so the independent support for the IDEA is intact; the
  corruption distorts individual days' absolute wiggle level, not the pooled result.
- **There are also NO mid-session restarts in this sample.** Checked
  2026-09-15 by enumerating every stream file per session dir with its first/last print: all six
  replayed pairs start pre-market and run CONTINUOUSLY for days (the 09-09 process covers 09-09 and
  09-10 without interruption; the small files are single-print pre-market boot failures, not
  restarts). `stream_driven_worker.py:365` drops ticks while the market is closed, so the accumulator
  starts at 09:30 with a full session on all 9 days. Consequently the **30-minute warm-up guard is a
  provable no-op on this sample** — `warmup_blocked = 0`, P&L identical to no guard; it first binds at
  45 minutes (and at 45 the result gets *worse*, -$274). The guard is still right on its own terms
  (never act on a too-young reading — the hazard is real and documented in BRAINSTORM idea 5) but it
  is insurance against a hazard this sample never contained, not a repair for anything observed.
  **`engine_wiggle` vs `session_wiggle` — MEASURED 2026-09-15, and 1.0 transfers.**
  `scripts/measure_engine_wiggle.py` drives the real `_update_history` and `StrategyMarketState.apply`
  at the real eval cadence, RTH-gated, against `session_wiggle` from the clean `price` field.
  72 snapshots, 9 sessions, 8 clock points a day: **ratio engine/session median 0.962**, mean 0.945,
  sd 0.102, range 0.710-1.302. So `engine_wiggle` runs ~4% SMALLER, which means a larger stretch and a
  marginally **stricter** gate than the research intends — the safe direction to be wrong.
  `vwap_max_stretch = 1.0` enforces about **0.962** in research units (and reproducing a research
  1.0 would need `vwap_max_stretch ≈ 1.04`) — this sentence said 1.04 until 2026-09-16, contradicting
  the conversion paragraph two bullets down; `measure_engine_wiggle.py` printed the same inversion and
  is fixed. Derive it rather than remembering it: `engine_wiggle = 0.962·session_wiggle`, the engine
  blocks at `|d| >= T·engine_wiggle`, so `T = 1.0` trips at `0.962·session_wiggle`. **Caveat:** sd 0.102 means the
  effective threshold wanders ~±10% day to day and occasionally 30% (09-15 sat at 0.83-0.92 all
  afternoon), so a recorded stretch should never be read to two decimals. That is a scale wobble, not
  a scale error, and an order of magnitude smaller than the 45-76% gap wrongly inferred from the
  corrupt-field comparison above.
  **Conversion for the replay:** the engine blocks at `|p-vwap| >= engine_wiggle ≈ 0.962·session_wiggle`,
  so reproducing a live `vwap_max_stretch = 1.0` in `replay_session.py` — which measures in
  `session_wiggle` — means `--max-stretch 0.962`, not 1.0. At 1.0 the replay models a slightly LOOSER
  gate than production. **So the live-equivalent replayed figure is `-$405 -> -$193` (115 trades), not
  the `-$163` (116 trades) that `--max-stretch 1.0` prints.** One trade's difference, $30, and in the
  unflattering direction — quote -$193 when the question is "what would production have done".
- **Latent coupling: `_VWAP_WARMUP_MINUTES` (30) == `entry_after_open_minutes` (30).** The first
  in-hours print lands 22-328 ms after 09:30:00 on all 9 sessions, so the live accumulator age at
  10:00:00 is 29.99-30.00 — just under the threshold, daily. A strict `age < 30` blocks the first
  evaluation of the entry window every day, then passes a second later. Harmless now; but lower
  `entry_after_open_minutes` or raise the warm-up and the guard silently eats the start of the entry
  window. Neither constant's file mentions the other.
- **Net position on the threshold.** The 24-session drift test (p = 0.000, and it survives the corrupt
  `vwap` field) supports the IDEA of not chasing, and the measurement above shows **1.0 TRANSFERS to
  the live gate** — `engine_wiggle` tracks `session_wiggle` to a median 0.962, erring strict. What is
  still missing is evidence that **1.0 is the right number rather than a working one**: the replay's
  apparent confirmation rests on 2 of 9 sessions, so it cannot calibrate. 1.0 was fixed before any
  result was seen, which is the right discipline; the honest summary is that it is now known to be
  *implementable as intended*, not known to be *optimal*. Do not tune it against the sessions on disk.
- Two wiggles, two questions, never interchangeable: **engine_wiggle** is tick-accumulated and
  restart-truncated (what the live gate sees; predicts live behaviour) and **session_wiggle** is
  rebuilt from full-session minute bars (what the replay and `distance_trades.py` see; measures
  whether the idea has edge). Any number quoted from one must say which.
- **Distance from the 9-minute EMA carries nothing** (shuffle p = 0.30 / 0.91, halves disagree).
  Dropped.

**It is a leak fix, not an edge.** Still negative after the block, and the replay is optimistic by
about half the spread. Break-even needs ~52% at the payoff the exits actually produce.

**BUILT AND LIVE 2026-09-15/16 — `vwap_max_stretch` (entry gate, off by default).** All in
`signal_generator.py`, as specced:
1. `sum_p2v` (price² × volume) in `_vwap_accumulators`, beside `sum_pv` / `sum_v`.
2. `_calculate_vwap_wiggle()` = sqrt(sum_p2v/sum_v − vwap²); None when not computable.
3. In the VWAP gate, after the side check: when `params_json.vwap_max_stretch` is set, block if
   `|price − vwap| / wiggle >= vwap_max_stretch`, and block when the wiggle is unavailable
   (most-restrictive, same as G3). Records `indicators['vwap_stretch']` either way. **Entries only —
   no exit path touched.**

Two things the spec did not anticipate, both load-bearing:
- **`_VWAP_WARMUP_MINUTES = 30`** blocks while the in-memory tally is younger than 30 minutes, and it
  equals `entry_after_open_minutes` exactly — see the latent-coupling note above before changing
  either.
- **Recording `vwap_stretch` unconditionally would have loosened `confirmation_required`** (an
  always-present observation counting as an indicator). `_OBSERVED_NOT_GATED` is excluded from that
  count in the same change, and `test_vwap_stretch.py` monkeypatches the set empty as a negative
  control so the fix cannot rot silently.

**Before switching it on:**
- [x] Test file in the style of `test_bar_aggregation.py` — `api/tests/test_vwap_stretch.py`.
- [x] Check the engine's **tick-sampled** wiggle against the **minute-bar** wiggle — done via
      `scripts/measure_engine_wiggle.py`; median ratio 0.962. See the conversion paragraph above.
- [x] Use **1.0**. Set on prod strategies 3 and 4 on 2026-09-15.
- [ ] Watch 2+ live sessions: count "not chasing" blocks, and re-run `distance_trades.py` on them.
      `replay_session.py` now also prints the warm-up block count separately, so a warm-up block can
      never be read as the gate declining a chase.
- [x] **Decide whether it ships with the `entry_before` afternoon cutoff — YES, owner confirmed
      2026-09-16.** Both shipped together: prod 3 and 4 carry `entry_before_et: "11:30"`, and all 8
      templates match prod so a cloned strategy behaves like the ones actually running. **The reason
      of record is the lunch gap, not the sweep row** — SPY volume troughs midday (97,052/min at
      09:30 against 33,950 at 12:30, G4a) and theta runs ~2% at 10:00 ET against ~28% at 15:30, so a
      late entry is stopped out by the clock rather than by the signal. Revisit when G4a's
      per-clock-minute volume profile lands, which is what would make midday tradable. Full
      reasoning: `entry_cutoff_time_et`'s docstring. **Two gates changed at once on an account that
      funds ~3 entries a day, so attribution between them will be slow — expect to need weeks, not
      sessions.**
- [x] **`entry_before_et` no longer fails silently** (2026-09-16). It is the only gate in the entry
      chain that fails OPEN, and it stays that way — `_parse_hhmm`'s "None == unset" contract is
      shared with `forced_exit_time_et`, and blocking every entry on a typo would stop the strategy
      outright. But `"11.30"` / `1130` / `"11:60"` now log `logger.error` once per distinct bad
      value. Contrast `_coerce_max_stretch`, which fails CLOSED because its contract is not shared.
      The asymmetry is deliberate; both are now loud.

**Keep the sample growing.** `scripts/fetch_1min_bars.py` tops up
`data/backtest/underlying/SPY_1min.json` (24 sessions, 2026-08-12..09-15 as of 2026-09-16) and `data/`
is untracked. Tradier keeps 1-min history for only ~20 days, so run it weekly or those days are gone
— same perishability argument as C1 Phase 0.

Verified while scoping: the VWAP accumulator only receives ticks while the market is open
(`stream_driven_worker.py:365`), so the wiggle starts at the bell. But it is in-memory, so **after a
mid-session restart both VWAP and the wiggle cover only the time since restart.** That already
affects today's VWAP gate; it belongs with G3's warm-up seeding (Tradier's REST 1-min bars carry a
per-bar vwap).

**G4c. Prior levels** — yesterday's close, overnight high/low, pre-market range. ORB is already one
member of this family and the only one measured (**105 breakouts, 59.0% right at +30m, CI excludes
zero** — the only candidate that does). The data is already captured: stream logs start before the
open, so overnight and pre-market are in the files.

**G4d. Higher-timeframe agreement.** `docs/REGIME_FILTER.md` specifies it and E12 records that
`check_market_regime` ships on every strategy and is read by nothing. Would have silenced the put
side for most of the measured week. **Most likely of the four to be fooled by this sample** — all
four measured sessions drifted upward, which is exactly the tape where a trend filter flatters
itself. Needs a down-tape stretch first.

**Also: `$TICK` is half-built.** The gate is fully implemented at `signal_generator.py:489`
(`use_tick_indicator`, `tick_threshold`, `tick_direction`), but
`StrategyMarketState.to_market_data()` never supplies `tick_value`, so the branch is unreachable
even when enabled, and nothing says so. The missing half is a data feed — Tradier's stream does not
carry breadth — so this is not a few lines. Either wire a source or mark the params dead, but do not
leave a gate that silently cannot fire.

**Not on this list on purpose: implied volatility.** It matters more than any of the four, because
this book only ever buys options — a fall in expected movement costs money even when the direction
call is right, and can never help us the way it helps a seller. Excluded because measuring it needs
option-chain snapshots through the session, which is a collection project rather than a tape test.
Revisit once the four above are settled.

**Evidence limit.** Every number here comes from 4–8 prod sessions, all of them up-drifting.
E11's thresholds govern as they govern everything else, and the tape tests share the underlying
sample — they are not independent confirmations of each other.

---

## H. Recovery-path hardening (from the 2026-08-26 put-support guard passes)

H1 (the orphaned second contract) is fixed and has moved to **RESOLVED**.

### H2. Adoption serialisation is in-process only

`_adoption_lock(user_id, underlying)` (`stream_driven_worker.py`) serialises the adopt-and-commit
critical section so two strategies on one underlying cannot both create a `Position` row for the
same broker holding. It is an `asyncio.Lock`, so it only covers the single-process deployment.
A second engine process would need a partial unique index on `(user_id, option_symbol) WHERE qty > 0`
or a `pg_advisory_xact_lock`. Same class of gap as A2's reservation-ledger concern.

### H3. `elif declined:` leaves `state.option_symbol` unset

When adoption declines a live claim, the strategy arms a *fresh* contract while its own open row
names a different one. Exit pricing is safe (`_check_exit_signals` compares the streamed symbol to
`position.option_symbol` and falls back to REST on mismatch), but that REST fallback then runs on
every 1s eval tick — ~60 quote calls/minute for a position that could have been streamed. The
declined branch could arm the strategy's own open contract instead.

### H4. No broker-side stop exists — a dead engine leaves an open position unprotected *(2026-09-16)*

**Every exit lives in the engine process. Nothing rests at the broker.** Verified 2026-09-16: entries
and exits are both `order_type='market'` (`order_manager.py`), and no path places a `stop`,
`stop_limit`, OCO or OTOCO order. Stop loss, take profit, trailing stop and the 15:45 ET forced exit
are all evaluated by `check_exit_signal` on the streamed **bid**, once a second
(`_EVAL_INTERVAL`), and only then is a market sell sent.

That design is deliberate and mostly right — option stop orders trigger off erratic prints and can
fill far away, and a trail or a clock exit cannot be expressed as one resting order. **But it means
the stop only exists while the process runs.** If the engine crashes, the laptop sleeps, the network
drops or the stream stalls while a position is open, nothing sells it. For a 0DTE contract:

- it rides to the close and expires worthless — a 100% loss on a stop meant to cap it at 15%, or
- it finishes in the money and may be **auto-exercised into 100 shares of SPY (~$75,000)**, which a
  ~$1,460 cash account cannot settle; the broker would force a close-out on its own terms.

**Proposed: a broker-side "disaster stop" as a failsafe, not a replacement.** After an entry fills,
place a resting `sell` `stop` (or `stop_limit`) order well BELOW the engine's stop — e.g. -40% — with
`duration=day`. The engine keeps doing every normal exit; the disaster stop only fires if the engine
has gone silent. Tradier supports `stop` / `stop_limit` on option orders
(`docs/tradier/trading/place_option_order.md`); consult `docs/tradier/` before any code.

**Design hazards — the reason this is not a quick add:**
1. **It can BLOCK the engine's own exit.** A broker will very likely reserve the contracts for an
   open sell order, so the engine's market sell would be rejected for insufficient quantity while
   the disaster stop rests. The engine must **cancel the stop, confirm the cancel, then sell** — and
   a failed or slow cancel must never leave the position unsellable. **Exits are sacred: this is the
   hazard that decides the design.** Verify the reservation behaviour against the docs/broker first.
2. **Double-fire.** Stop and engine both trigger in a fast move. In a cash account the second sell
   should be rejected (no position), but that has to be confirmed, not assumed — and reconcile
   (`_reconcile_position`, `_update_position_exit`) must handle an exit it did not place.
3. **Orphans.** An engine exit that forgets to cancel leaves a resting sell order behind. Needs a
   sweep, likely in the reconcile loop, and a startup check.
4. **Where it sits in the gates.** Placement must go through the same preview / order path as every
   other order (`_preview_or_abort`, no direct `place_order`), and the cash-reservation ledger must
   not count it as a buy.
5. **Level.** Too close and it fires on the same noise the 15% stop already does; too far and it
   protects little. Start from the cost budget's noise figures, not a round number.

**Cheaper alternative worth weighing first:** a watchdog outside the engine process that alerts (or
flattens via the normal exit path) when heartbeats stop while a `Position` row is open. It does not
help if the whole machine is down, which is the case the broker-side stop exists for.

Not started. Engine change — needs sign-off and a design pass before any code.

---

---

## I. Broker-document reconciliation (confirm/statement import + calendar)

Tradier's portal exposes statements, trade confirmations and tax documents under Documents, but
**there is no retail API for them** — the `documents` endpoint (`documentDate`, `documentType` one of
`STATEMENT`/`TAX`/`CONFIRM`, `documentDescription`, `url`) lives in the *Advisor* API, which is
gated to registered RIAs and partners. So the only way to get the clearing firm's record of our
fills is to download the PDFs by hand and import them.

Worth doing because confirms are the one **independent** source of truth we have. `Trade` rows are
written by our own engine, so a bug in the engine corrupts the evidence and the record of it at the
same time — which is exactly what CP-1 is (`scripts/verify_data_checkpoint.sql`, trades id <= 2905
partly untrustworthy). `scripts/reconcile_2026_07_13.py` proved the shape of the fix on a single day
and found four distinct engine bugs from a $232 gap; this generalises that to every day we traded,
sourced from PDFs instead of an API we cannot reach.

**Scale (measured 2026-09-07).** Only *live* days have a counterpart document, so only they are in
scope: PROD holds 16 trades over 3 days (2026-09-02 to 09-04, the live-test window). The 2,841 DEV
trades across 50 ET days (2026-04-23 → 2026-09-01) are all sandbox and can never be reconciled —
see I5. The calendar is therefore a handful of cells growing by one per trading day, so per-day
reconciliation is computed on read and needs no cache.

### I1. ~~PDF parser~~ *(prototype done 2026-09-07 — `scripts/parse_broker_confirm.py`)*

Confirms are **Apex Clearing** "Postedge" documents — Tradier clears through Apex — and the PDFs are
text-based, so `pdftotext -layout` extracts them cleanly with no OCR. Verified against the 2026-09-02
and 2026-09-04 confirms: 6 fills each, both checksum-clean.

Record layout is four lines per fill:

    Type B/S TradeDate SettleDate QTY SYM PRICE Principal COMM TranFee Fees Tag NetAmount Trade# M/K C/A
    1    B   09/02/26  09/03/26   1       3.2700000 327.00  0.00 0.02  0.09 S6637 327.11  TNB0903 5 1
    Desc:  CALL SPY 09/02/26 760 STATE STREET SPDR S&P 500 ETF UNSOLICITED OPEN CONTRACT ... CUSIP: 8GTXKB7
    Currency: USD   ReportedPX:                MarkUp/Down:
    Trailer: UNSOLICITED, OPEN CONTRACT

What the layout forces on the design:

- **The SYM column is blank for options.** The contract is only in the `Desc:` line
  (`CALL SPY 09/02/26 760`), so the OCC symbol has to be reconstructed —
  `SPY` + `260902` + `C` + `00760000`. Verified to reproduce our stored `option_symbol` exactly.
- **Buy/sell open/close is in the `Desc:`/`Trailer:` text**, not the B/S column: `OPEN CONTRACT` vs
  `CLOSING CONTRACT` gives `buy_to_open` / `sell_to_close`.
- **Page 1 is a cover sheet** (clearing-firm address block); fills start on the following page. Parse
  by content, never by page index.
- **The `SUMMARY` block is a free checksum** — `TOTAL DOLLARS BOUGHT`/`SOLD` must equal the sum of
  parsed net amounts. Both test confirms reconcile to the cent. `--strict` makes a mismatch fatal, so
  a silent layout change from Apex cannot import bad data.
- **CUSIP is per contract** (`8GTXKB7` = SPY 09/02 760C) and stable — a candidate secondary key,
  though we do not store CUSIPs today.
- **One confirm covers one trade date.** Filenames carry the account and a generation timestamp, not
  the trade date, so the date must come from the parse.

Remaining: equity fills are handled on inference only (`SYM` populated, no `Desc:` option line) — we
have not traded equities, so that branch is unverified. Monthly **statements** are still unparsed;
take them for the cash/settled-balance roll-forward that cross-checks A1.

### I2. Data model — parse on upload, never store the PDF

Explicit requirement: **no PDF bytes are persisted**, so no S3/blob store and no new infra.
(Why, and what the S3 option would actually have cost: `BRAINSTORM.md`.) The file
is parsed in-request and the bytes are dropped; only extracted rows survive. Consequence to accept
up front: re-importing after a parser fix means re-uploading the file. That is fine at one
document per live trading day (3 so far).

- `BrokerDocument` — one row per imported file: `user_id`, `environment`, `doc_type`, `period_start`,
  `period_end`, `file_sha256`, `source_filename`, `parser_version`, `imported_at`, row counts.
  `file_sha256` is the idempotency key: re-uploading the same file is detected and offered as a
  replace instead of silently double-importing.
- `BrokerFill` — one row per fill line: `document_id`, `user_id`, `trade_date`, `symbol`,
  `option_symbol`, `side`, `action`, `qty`, `price`, `principal`, `commission`, `tran_fee`,
  `fees`, `net_amount`, `settle_date`, `cusip`, `tag_number`, `trade_number`, `raw_line`,
  `matched_trade_id` (nullable FK), `match_status`. Note `tag_number`/`trade_number` are Apex's
  identifiers and are stored for traceability only — they are **not** joinable to our order ids
  (I3), so do not index them as if they were keys.
- **No third table for the calendar.** Per-day status is derived on read — the live-day count is in
  the single digits and grows one row per trading day. Only add a cached `ReconciliationDay` if a
  query actually proves slow.
- **PII:** confirms carry account number, name and address. Store the account's **trailing digits
  only** (the confirm prints five — `70356`); do not persist name or address at all. Not storing the
  PDF is what keeps this cheap — don't undo it by copying the header block into a column.
- **PREREQUISITE — stamp the trading mode on the `Trade` row.** The calendar cannot be built without
  this. A confirm exists only for a fill that actually cleared at Apex, so a *sandbox* day has no
  counterpart document and must render as "not applicable", never as "needs import". Today nothing
  on a `Trade` says which it was: `selected_trading_mode` lives on the **`User`** row
  (`models.py:47`) as a mutable current setting, so it says what the user has selected *now*, not
  what was true when the fill was written. The only way to classify existing rows is the external
  fact that live trading began 2026-09-02 — a hardcoded date in the UI, which is exactly the kind of
  thing that rots.
  - Add `trading_mode` to `trades` (`'paper'` | `'live'`), written at Trade-creation time from
    `user.selected_trading_mode` in `order_manager`. Additive metadata on the write path — it gates
    nothing and changes no order behaviour — but it is still an engine edit, so it needs its own
    stated reason and a look at every site that constructs a `Trade`.
  - Backfill: DEV rows → `'paper'` (all 2,841 are sandbox, see I5); PROD rows from 2026-09-02 →
    `'live'`. After the backfill the 2026-09-02 date lives in a one-off migration, not in the UI.
  - Consider the same stamp on `Position` if the reconcile ever needs to classify open rows.
  - Per `feedback_migrate_before_model_edit`, this is precisely a case where DEV **and** PROD must be
    migrated before `models.py` is edited — `reload=True` means a model save hits the shared DB.

### I3. Matching rules

> **2026-09-07 — the original plan here was wrong and has been rewritten.** It assumed the broker
> order id would be the join key. **There is no order id anywhere on the confirm.** The only
> identifiers Apex prints are its own: a per-fill `Tag Number` (`S6637`, `W2124`) and a batch
> `Trade#` (`TNB0903`), neither of which relates to the Tradier order id we store in
> `Trade.notes['order_id']` (`144248409`). Nothing to join on directly.

- **Match as a per-day multiset**, not row-by-row. The confirm carries **no execution time** — only a
  trade date — and it groups fills by contract rather than chronologically. So the unit of
  reconciliation is: for one ET trade date, does the bag of (option_symbol, action, qty, price)
  from the confirm equal the bag from `trades`? Price to the cent, qty exact.
- **`option_symbol` is NULL on our buy rows** — `notes['option_symbol']` is only written on the sell
  leg. Verified in prod: all six buy rows on 09/02 and 09/04 have it empty. Either backfill it from
  the paired `Position`, or match buys on (date, action, qty, price) and let the contract come from
  the round trip. Worth fixing at the source regardless.
- **Round-trip pairing is ours, not theirs.** On 09/02 two buys (3.27, 4.23) and two sells
  (4.11, 5.28) hit the same 760C. The confirm never says which sell closed which buy; our DB asserts
  a pairing. Reconcile the legs independently and treat pairing as an unverifiable assumption.
- **Fees are the one field that will not match today — and that is a real finding, not noise.**
  Apex charges a Tran Fee (0.02 buy / 0.04–0.05 sell) plus 0.09 Fees per contract. Our prod rows
  record `commission = 0` and `fees = 0` on **every** fill, despite the `models.py` comment claiming
  fees are populated from `/account/history type=fee`. So P&L is overstated by the full fee load:
  09/02 booked +143.00 against a broker net of +142.27, 09/04 booked +96.00 against +95.28 — about
  $0.24 per round trip. Small per trade, but it is unidirectional and never nets out. See I6.

### I4. Calendar page + report

New page under `ui/src/app/pages/`, one cell per calendar day, state derived from the above:

| State | Meaning |
|---|---|
| neutral | no trades and no fills that day — nothing to do |
| **needs import** | we have `Trade` rows for that ET day and no confirm covering it |
| **reconciled** | every trade matched a fill; qty and price agree within tolerance |
| **review** | broker-only fills (a fill we never wrote down), DB-only trades (phantom), or a qty/price disagreement |

Clicking a day opens the per-day report: matched rows, the three mismatch buckets, and the net
cash/P&L difference for that day — the same output `scripts/reconcile_2026_07_13.py` prints, per day.

- **Day boundary is ET, not UTC** — see `project_pnl_day_boundary_tz`. The confirm's trade date is
  the broker's ET session; group `trades.timestamp` the same way, never on `utcnow()` midnight.
- **RBAC:** upload is a write → `Depends(require_can_write_own)`; hide the upload control for
  `viewer`/`auditor` off `authService.currentUserValue?.role`. Not an order path, so
  `require_can_place_orders` does not apply. Cross-user read stays admin/auditor observe-only.
- **Theming:** do not encode day state in colour alone. Green/red here means match/mismatch, which
  collides with the profit/loss semantics of `--color-profit` / `--color-loss` — and colourblind mode
  remaps that palette to blue/orange, so a "green = good" cell stops reading as good. Pair every
  state with a glyph or label and check it in CB mode.

### I5. ~~CP-1 backfill sweep~~ — **not possible, see why**

Originally scoped as "import the confirms covering trades id <= 2905 and settle CP-1 from broker
records." **That cannot be done.** Apex only issues confirms for fills that actually cleared, and
every pre-checkpoint trade is a *sandbox* fill: `docs/live-test-2026-09-02.md` states the 09-02 run
existed to "get the first honest fill data this engine has ever produced," because "sandbox
fabricates fills, so every price-derived metric to date is meaningless." All 2,841 DEV rows —
including the 2,480 pre-CP ones and the 253 on 2026-07-13 — are sandbox. No confirm exists for any
of them, and none ever will.

So CP-1 is not settleable from broker documents. It stays what it already was: an invariant check
(`scripts/verify_data_checkpoint.sql`) that earns confidence only as clean post-checkpoint live data
accumulates.

**What this feature actually is, then: a forward check.** Confirms exist from 2026-09-02 onward
(3 live days, 16 trades so far). Reconcile each live day as it happens, so a recording bug is caught
against Apex within a day of occurring instead of being discovered months later the way CP-1 was.
That is also why the calendar only ever needs to cover live days — a sandbox day has no counterpart
document and should render as "not applicable", never as "needs import".

### I6. Fees and commissions are not recorded on live fills

Surfaced by the first confirm import (2026-09-07), listed separately because it is an **engine data
bug, not a reconciliation feature** — and it is writing wrong numbers into `trades` right now.

Every prod fill has `commission = 0` and `fees = 0` while the confirm shows a real per-contract
charge on both legs. `Trade.fees`' comment says it is "populated from /account/history type=fee",
so either that backfill never runs, runs before the fee rows post, or fails silently. A1 already
noted that Tradier *sandbox* reports zero fees — this is the **live** account, so that explanation
does not cover it.

Consequences: reported P&L is overstated on every closed trade; win/loss classification flips for
any round trip inside ~$0.25; the A1 cash ledger reserves slightly less than a buy actually costs
(net 327.11 vs principal 327.00). None of it is large, all of it is one-directional.

**Investigate first:** confirm whether the `/account/history type=fee` backfill exists and runs at
all before changing anything — per `feedback_engine_filter_consumer`, find the consumer before
touching the producer. Fee rows may post T+1, in which case the fix is a next-day sweep, not a
change on the fill path.

---

# FUTURE CONSIDERATIONS

- **THERE ARE NO BROKER-SIDE STOPS. If the engine dies holding a position, nothing protects it.** Every exit — stop loss, take profit, trailing stop, time exit — is *simulated in-engine* and issued as a market sell when our own logic decides to fire (`order_manager.py:425`, market orders hardcoded). **Nothing rests at Tradier.** If the process crashes, the host reboots, the WebSocket wedges, or the eval loop stalls while a 0DTE position is open, that position simply sits there unmanaged until someone notices. The `stop_loss_pct` you configure is a number the engine checks — not an order the broker holds.
    - **This is the single largest live-trading risk in the system** and it is independent of every other item here. It survived the 2026-07-13 session only because nothing crashed.
    - **Tradier supports the fix.** It has OTO / OCO / OTOCO order classes, so an entry can carry an attached stop and target that live at the broker. `docs/tradier/trading/` documents them; **no code path calls them** — `place_option_order` hardcodes `class: "option"` (single-leg) and only ever sends market orders.
    - **The tension to resolve first:** broker-side brackets and engine-side trailing stops fight each other. A resting stop can't trail, and the engine can't trail a position the broker might close underneath it. Options: (a) resting *disaster* stop at the broker (wide — e.g. −50%), engine keeps managing the tight/trailing exits inside it; (b) full broker-side bracket, drop engine trailing entirely; (c) engine cancels/replaces the resting stop as it trails (most correct, most API traffic, most ways to desync). **(a) is the cheapest real safety win** — it bounds the catastrophic case without touching the strategy logic.
    - **Do this before any meaningful live capital.** Everything else on this list is money-losing-slowly; this one is money-gone-in-one-event.

- **Configurable server port + first-class multi-instance (per-environment) runs.** `api/app.py` hardcodes `uvicorn.run(..., port=8000)`, so a dev (`APP_ENV=dev`) and a live (`APP_ENV=prod`) instance can't run at the same time — they collide on port 8000. Make the port env-driven (`PORT`, default 8000) so both can run side by side (e.g. dev on 8000, live on 8001), each with its own engine worker / Tradier stream / email scheduler and each pinned to its launch `APP_ENV`. This is the safe model — trading is pinned to the process env, not the UI toggle (the toggle only reroutes *reads*; see JOURNAL.md 2026-07-10/11 and `docs/monday-runbook.md`). Follow-ups: the Angular `apiUrl` is fixed per build, so driving two backends means pointing the UI at the target instance's port (or running two UIs / adding an instance picker); optionally add a `scripts/` launcher ("start-dev", "start-live"). Low risk — two lines in `app.py`.

- **~~Daily-profit cutoff (positive-P&L halt for the day).~~ PROMOTED — this is now D2.** The sketch that lived here (mirror `_check_user_daily_loss_limit` on the upside, block `side='buy'` only, `_check_user_daily_profit_target`, a `User.daily_profit_limit_pct` column + migration, a `PROFIT_HALTED` session status, and the open equity-vs-risked-capital threshold question) is carried in full by **D2**, which now also has live data to size it against and a stated reason for sitting behind G2. Kept as a pointer so the cross-reference from older notes still lands somewhere.

- **Broker-state reconciliation on engine startup (the right fix for restart + multi-process).** Relates to A2 but takes a different angle: instead of moving the in-process ledger to Redis / DB / sticky routing, **rebuild the ledger from Tradier itself** at `StreamDrivenWorker.start()` before allowing any new signals through. Premise: Tradier's `/orders` (open + pending) + `cash.cash_available` are the real source of truth — the in-process dict is just a milliseconds-window bridging hack between `place_order()` returning and Tradier registering the order in `cash_available`. Reconciling against broker state survives every restart scenario (process, host, future Redis) without introducing new infra.
    - **Sketch:** on startup, for each user with active strategies, call `trading_client.get_open_orders(user)`, filter to `side='buy'` with non-terminal status, and call `OrderManager._acquire_buy_reservation(user.id, expected_cost)` for each. Key the reservation by `broker_order_id` (not just UUID) so the existing fill-handler can release by the order_id Tradier returns. TTL stays as the safety belt.
    - **Why not just rely on Tradier's `cash_available`?** It does reflect registered orders, but there's a sub-second post-`place_order` window where it's stale — that's the entire reason the in-process ledger exists. Reconciliation moves that bridging logic from "in-process memory of orders we placed" to "explicit query for orders the broker knows about", which is restart-safe.
    - **Promote when EITHER becomes true:** (1) deployment moves to multi-process (gunicorn `--workers >1`, multi-replica), so A2's cross-process gap becomes real; or (2) order frequency rises enough that the sub-second post-place window starts statistically coinciding with crashes. Today: single-process + ~19 trade cycles/day = effectively zero risk, the 5-second `_auto_restart` delay already covers the registration window in practice.
    - **Effort:** ~30–50 lines + a startup test. Smaller than the Redis/DB-row alternatives in A2 because it doesn't add a new state store.

- **🚨 TRADIER SANDBOX FILLS ARE FABRICATED — no strategy metric measured in sandbox means anything.** Discovered 2026-07-14. The engine **must** read LIVE market data (sandbox has no market-data WebSocket, so quotes always come from the live endpoint), but orders **fill in sandbox**. Those are two different price universes and the engine straddles both.
    - **Proof (the simplest possible invariant): an option cannot trade below its intrinsic value** — that would be free arbitrage. SPY's real tape at 10:34 ET on 2026-07-14 was **752.02**, and the engine's streamed price agreed (751.98). A **749 call** therefore has **$3.00 of intrinsic value**. Tradier sandbox priced and filled it at **$1.84–$2.14**. Impossible.
    - **Consequence:** entry is recorded at a sandbox fill; the exit is then evaluated against a LIVE quote. `pnl_pct = (3.49 − 1.84) / 1.84 = +89.67%` → *"Take profit hit!"* → the exit fills in sandbox at 1.81 → **actually −1.6%**. A *"Stop loss hit: −15.58%"* realised **+5.1%**. **Exits are effectively random.**
    - **Measured:** 2026-07-13 — **120 of 121** TSLA exits fired at a price we did not get (mean gap $0.92). 2026-07-14 — **20 of 22** SPY exits, same story. **The engine's logic is correct; the data is fake.**
    - **This retroactively invalidates** the 31% win rate, the −1.08% mean per-trade return, the −0.146 Sharpe, the "−9.15% expectancy", the 69/31 exit-reason split, and the conclusion that the signal "fires on noise". All were computed from fabricated fills. **We do not know whether these strategies are profitable.** See the corrected `docs/negative-expectancy.md`.
    - **What sandbox CAN test:** order placement, fill confirmation, reconciliation, the streams, contract selection/reselection, risk gates, not crashing. All verified working 2026-07-14.
    - **To actually evaluate a strategy** you need real fills and real quotes in ONE price universe: either the **backtester (C1)** against historical option data, or **live with minimal size** — and the latter must not happen before broker-side stops exist (item #1 above).

- **The stop-wider-than-target flaw was real, and fixing it was right — but the specific 15/30 ratio was tuned to a fake win rate.** `SL / (SL + TP)` is the win rate you need just to break even; it is arithmetic and does not depend on any data. TSLA ran **SL 20 / TP 15** (needs **57.1%**) and SPY ran **SL 50 / TP 25** (needs **66.7%**) — both indefensible regardless of what the fills say. Both are now **SL 15 / TP 30** (needs 33.3%).
    - **Revisit the exact ratio** once real fill data exists. The *direction* (target wider than stop) is unambiguous; the magnitude was chosen to sit below an observed "31% win rate" that turned out to be an artifact.
    - **Churn is real and is NOT a pricing artifact** — timing data doesn't depend on fill prices. Median gap between consecutive TSLA entries on 2026-07-13 was **38 seconds**; 106 of 119 entries came within 90s of the previous one. `MIN_ORDER_INTERVAL_SECONDS = 5.0` blocked **108 of ~233 attempted orders (46%)**. That rate limiter is a governor pinned to the floor, not a safety margin. A re-entry cooldown is still worth adding.

- **Cold-start latency blows the first orders' fill-confirmation window.** Both `ORDER_UNCONFIRMED` events on 2026-07-13 fired at 13:45:48 and 13:46:20 — within the first 80 seconds of the session's first order (13:45:01), and ~4.5 hours before anything was touched by hand. Both orders **filled anyway**. `_await_terminal_order` (`api/engine/order_manager.py`) polls `get_order` every 1.5s for 30s; the first Tradier round-trips of a session appear slow enough to exhaust it.
    - **Now survivable, not fixed:** the account event stream (added 2026-07-13, `api/engine/tradier_account_stream.py`) pushes fills so the poll usually wakes in milliseconds, and unconfirmed orders now block further entries + get backfilled on the reconcile tick. But if the stream is down, the same 30s window applies.
    - **Cheap follow-ups:** warm the Tradier connection at worker startup (one throwaway `get_clock`/`get_profile` before the first signal can fire), and/or give the FIRST order of a session a longer `timeout_s`. Confirm the cold-start theory first by logging poll-loop duration per order — it may just be sandbox latency.

- **The unconfirmed-order ledger is in-process (same blind spot as A2's cash ledger).** `OrderManager._unconfirmed_orders` is a class-level dict. It gates new entries while an order's fill is unknown and drives the reconcile-tick backfill — but a restart empties it, so a process bounce mid-timeout silently drops both the entry block and the Trade-row backfill. The broker stays the source of truth (`_reconcile_position` still adopts the position), so this cannot produce a *wrong* position — only a missing trade record and a briefly unguarded entry path.
    - **Fix alongside A2 / the startup-reconciliation item**, not separately: the same "rebuild in-process state from broker orders at startup" pass that repairs the cash ledger can repopulate this one from Tradier's open/pending orders. Doing it twice would be waste.

- **`TODO.md`'s DONE entry "Fee tracker on the performance page" (2026-05-09, Part 2) is now partly stale.** It concluded "No additional work needed" — but the tile it describes was reading Tradier's `/gainloss`, whose cost basis is corrupt (see the Sharpe/P&L note below). The commission/fee *attribution* logic it describes is probably still fine; the P&L basis underneath it was not. As of 2026-07-13 the page reads `/performance/closed-trades` (engine fill records) instead. Re-verify the fee tile against the new source before trusting it.

- **Tradier's `/gainloss` is not a safe P&L source — treat it as untrusted, in live as well as sandbox.** Its FIFO lot matcher does not retire closed buy lots when the same contract is round-tripped repeatedly in one session: it keeps pairing new sells against early, already-closed, more expensive lots. On 2026-07-13 a single 0DTE contract (`TSLA260713C00405000`, bought and sold 50 times as it decayed 6.10 → 0.39) reported cost 34,908 against a real 14,244 — same 150 contracts, same proceeds, cost inflated 2.45×. The report showed **−21,057** for a day that actually lost **−1,851** (confirmed against `close_pl`, order-fill cash flow, and account equity, which all agree).
    - **Consequence beyond the dashboard:** if Tradier's LIVE gainloss shares this lot bug, live P&L/tax reporting is equally suspect. The money is always right (fills are fills) — the *report* is not. Compute P&L from fills, never from `gainloss`.
    - **Still exposed:** `GET /account/gainloss` (`api/tradier_integration/router.py`) and `TradierClient.get_gainloss` remain, and the client hardcodes `page=1, limit=25` with no pagination loop. Either delete the route or paginate it and label it clearly as broker-reported-and-unreliable, so nobody wires a metric to it again.

- **Unify the delta / open-interest defaults across the three places that read them.** The same param keys are defaulted to three different values, so a strategy created *without* `delta_min` / `delta_max` gets silently different criteria depending on which code path is asking. Contract selection defaults to `0.40 / 0.90` (`stream_driven_worker.py:738-740`), the drift re-check to the same `0.40 / 0.90` (`:905-907`), the SignalGenerator entry gate to `0.0 / 1.0` (`signal_generator.py:211-212` — i.e. accepts everything), and the confidence calc to `0.60 / 0.85` (`:568-569`). `min_open_interest` at least agrees on `0` everywhere.
    - **Not a live bug today:** both current strategies (id=2 TSLA, id=3 SPY) define `delta_min`, `delta_max` and `min_open_interest` explicitly in `params_json`, so all four call sites read identical numbers and the defaults never fire. This is latent — it bites the first strategy created (or seeded from a template) that omits those keys, and it will fail *open*, not closed: the entry gate's `0.0 / 1.0` default accepts any delta.
    - **Fix shape:** hoist the defaults to one module-level constant dict (or onto the Strategy model as column defaults) and have all four sites read from it. Prefer failing *closed* — a missing delta band should reject, not wave through.
    - **While you're there:** the entry-gate and confidence blocks in `signal_generator.py` are now genuinely live (they were inert until 2026-07-13, see below), so a wrong default there actually changes trading behavior for the first time.

- **Subscribe reconcile-adopted contracts to the market stream.** `_reconcile_position` adopts a contract straight off the broker when a position is opened outside the engine — manual fill in the Tradier UI, or an app restart mid-trade — by setting `state.option_symbol = occ` (`stream_driven_worker.py:614`; `_startup_sync` does the same at `:524`/`:528`). Neither path calls `stream_mgr.subscribe()`, so no option quotes flow in for that position: `state.option_bid` / `option_ask` stay `0.0` and exit pricing silently falls back to the per-tick REST fetch (`strategy_executor._fetch_option_price`).
    - **⚠️ CORRECTED 2026-08-25 — it DID hurt, badly. This is the mechanism behind the $223,119 phantom.** The original analysis was right that `_check_exit_signals` falls back to REST, but it only checked the *exit-signal* path. The **mark-to-market** path had no such fallback: `strategy_executor.execute_exit_tick` kept `current_price` as the **UNDERLYING** whenever `ask == 0.0` (exactly the state an unsubscribed adopted contract is in) and wrote it straight to `position.current_price` / `unrealized_pnl`. `_reconcile_position` then used that field as a closing fill price, booking SPY's 747.03 as an option premium. Fixed at both ends 2026-08-25 (marks now come from the held contract's resolved price; the reconcile fallback sanity-checks every candidate against the underlying) — **but the underlying subscription gap this item describes is still open**, so adopted contracts still run on the slower REST path.
    - **Also true, and still true:** the position's bid/ask never appear in the 30s heartbeat log, which makes a recovered position look half-dead when it isn't.
    - **Fix shape:** route both adoption sites through the same `_arm_contract` helper the normal path now uses (`:868`), so subscribe + router-add + `streamed_symbols` bookkeeping happen together. The bookkeeping is the part that matters — `_disarm_contract` (`:876`) deliberately refuses to unsubscribe a symbol it never subscribed, precisely because these two paths can hand it one.
    - **Care required:** this touches the restart-recovery path, which is the one path that can't be safely tested during market hours. Do it deliberately, with a paper restart-mid-position rehearsal, not as a drive-by.

- **Watch for band-edge churn on drift-driven contract reselection** *(added 2026-07-13 alongside the reselection change — observation item, not yet a known bug)*. While a contract is armed but not yet bought, `_check_contract_drift` (`stream_driven_worker.py:886`) re-prices it every `_DRIFT_CHECK_INTERVAL` (30s, `:36`) and disarms it if delta has left the strategy's band, so the next tick selects a fresh strike. The drift check reads greeks from Tradier's **quotes** endpoint; contract *selection* reads them from Tradier's **chains** endpoint. Same vendor and same underlying greeks source, so they should agree — but if they disagree by a hair on a contract sitting exactly on the band edge, the engine can disarm and immediately re-arm the *same* strike, every 30 seconds, indefinitely.
    - **Bounded, not dangerous:** worst case is one chain pull + one re-subscribe per 30s per strategy. It cannot cause a bad trade — a contract only ever gets bought if it passes the band at entry time. It's a noise/efficiency concern, and a signal that the band is mis-sized.
    - **Where it would show up first:** TSLA (strategy id=2) has a **0.15-wide** band (0.50–0.65) and SPY (id=3) a 0.25-wide one (0.60–0.85). Those are narrow for 0DTE, where gamma walks delta quickly — expect reselection to fire *legitimately* and often, especially on TSLA.
    - **The tell:** grep the logs for `drifted out of criteria` (`:935`). Strike actually changing = working as designed. Same symbol repeating every 30s = churn.
    - **If it churns:** widen the band rather than lengthen the interval (a longer interval just means buying a staler contract). A hysteresis margin — only disarm once delta is outside the band by some epsilon — is the fallback if widening isn't acceptable. Note that selection already scores by *closest to band midpoint*, which is what makes a fresh pick start far from both edges, so churn should be self-limiting unless the band is genuinely too tight.
    - **Open-interest half is effectively a no-op:** OI barely moves intraday, so the drift check's OI comparison will essentially never trip. Delta is the part doing real work.

- **Verify drift-driven reselection actually fires — it ran in production on 2026-07-13 and we never checked.** Row 3 (`_check_contract_drift`, added that morning) is supposed to disarm a contract whose delta leaves the strategy's band and pick a fresh strike. It ran live all day and **its behaviour was never confirmed**. The suspicious signal: TSLA round-tripped ONE contract (`TSLA260713C00405000`) **50 times** while it decayed from 6.10 to 0.39 — which is what you would see if reselection was NOT swapping strikes.
    - **How to check:** grep the engine log for `drifted out of criteria`. Strike actually changing = working. Silence across a day where a contract decayed 94% = the drift check never fired, and we should find out why (delta band too wide to ever trip? quote endpoint returning no greeks? the `elif` never reached because the contract stays armed only while flat?).
    - **Until confirmed, treat Row 3 as unverified in production.** It is tested in isolation but has never been observed doing its job on real market data.

- **⚠️ All `ORDER_PREVIEW_DRIFT` events logged before 2026-07-14 are garbage — DISCARD them before any B2 analysis.** The emit site passed `signal.price` as the "signal price", but on an entry `Signal.price` is the **UNDERLYING** (SPY ~751), not the option premium. So every event compared a stock price against an option premium and logged a "drift" of ~**−99.4%** — which is just `4.83 / 751.22`. **Fixed 2026-07-14** (`order_manager.py` now passes `estimated_price`, the option mid it actually sized from), but the ~149 historical rows (127 on 07-13, 22 on 07-14) are unusable.
    - **This is the dataset B2 has been waiting on**, so B2's clock effectively restarts from 2026-07-14. Filter on `event_data.signal_price` being option-scale (< ~50) to separate good rows from bad.
    - Silver lining: this bug is what cracked the sandbox-fills case — it was the only place the underlying price and the option price sat side by side in one record.

- **174 post-cutoff churn trades remain in the history and drag every strategy metric.** Between 2026-07-15 and 08-21 the engine placed 174 entries *after* the 15:45 forced-exit time (12 of them at or after 16:00 ET, when the market was shut — `is_market_open()` let them through on a 60s-stale Tradier clock). Each was sold within seconds by the forced exit; net **−$1,064.46** in pure spread. The entry gate was fixed 2026-08-25 (`forced_exit_time_et()` is now the entry cutoff), but the trades are real records at real prices and were deliberately **left in place**.
    - **They are separable:** all sit in the 15:45–16:00 ET band. Filter them out before measuring expectancy, win rate or Sharpe, or the numbers understate the strategy by ~$1,064 across ~87 fake round trips.
    - **Decide:** either tag them (`notes.excluded_from_metrics = true`) so the performance endpoints can filter automatically, or accept the drag and remember to filter by hand. Tagging is the better answer if strategy evaluation is ever automated.

- **`routers/performance.py:174` labels trades with the wrong contract.** It reads `position.option_symbol` to name a closed trade — but `_update_position_entry` **reuses a `qty=0` position row for the next entry**, overwriting that field. Trade 2408 closed `SPY260731C00745000`; its position row now reads `SPY260825C00764000`, a month-later strike. Every historical row on the performance page can therefore be labelled with whatever contract was bought most recently.
    - `notifications/reports.py` was fixed 2026-08-25 to read `notes.option_symbol` first and fall back to the position row only for older rows. **Apply the same precedence here.**
    - `close_position` now records `option_symbol` in its notes, so rows written from 2026-08-25 onward are self-describing; the ~1,225 older closes are not and can only ever be labelled approximately.

- **~~A re-entry cooldown after a stop-out.~~ SUPERSEDED 2026-09-09 by G2 — a blanket cooldown is the wrong lever.** The original reasoning below still reads well and is still wrong on this data: five of the six same-contract re-entries came back within **90 seconds** and that bucket made **+$309**, including the +$153 and the +$126. An elapsed-time cooldown blocks those along with the three losers. What separates the buckets is not the gap, it is whether the engine had to **select a different strike** — see G2. Kept for the reasoning:
    - *Not a data question — a design one. Re-entering 30 seconds after being stopped out is a bet that the thing which just went against you will now go for you. Combined with the 38-second median cadence and a rate limiter that is already rejecting 46% of attempts, the engine is trading as fast as it is permitted to rather than as fast as it has edge for.*
    - The **cadence half of that is confirmed** and G1 restates it in live terms: on 09-02 the engine wanted to be in a position continuously from 10:22 to 15:43 ET and took 3 trades. It is still trading as fast as it is permitted to — permission is just now denominated in settled cash rather than in seconds.

- **`TradierClient` has no 429 / rate-limit handling.** `_RETRY_STATUSES = {502, 503, 504}` only (`client.py:24`); the `Retry-After` and `X-Ratelimit-*` headers Tradier sends are ignored entirely. POST is deliberately never retried (correct — avoids double-submits), but a 429 on a GET currently just raises. Not urgent at ~19 trade cycles/day; becomes real the moment order frequency or strategy count rises.
    - **Three modules bypass the client with raw `requests` and inline API keys**, so they'd miss any retry/limit logic added there: `strategy_executor._fetch_option_price` (`:555-591`, plus dead `live_url` at `:563`) and `utils/market_hours.py:138`. Route them through `TradierClient` when touching either.

- **`api/engine/trading_safeguards.py` is dead code — decide whether to wire it up or delete it.** `PaperTradingSafeguards.validate_strategy_params` is never called by anything (the similarly-named `RiskManager.check_live_trading_safeguards` at `risk_manager.py:487` is a different function). It checks position sizing, that a stop loss exists and is ≥ 10%, that take-profit is < 100%, and warns when there is no time-based exit — all things we *want* enforced, and none of which are.
    - **If wiring it up:** it rejects any strategy whose `stop_loss_pct` is absent or < 10. Both current strategies now set it (15), so they pass — but confirm before enabling, or strategy creation starts failing.
    - **It would have caught the 2026-07-13 config.** Not the inverted risk/reward (it doesn't compare SL to TP — worth adding: reject `stop_loss >= take_profit`, the exact flaw that guaranteed the loss), but it *is* the natural home for that check. See `docs/negative-expectancy.md`.

- **~~`scripts/update_account_size.py` is broken and untracked.~~ RESOLVED — verified 2026-09-09.** It now writes `user.account_size_usd`, which is the real column (`models.py:18`), and the file is tracked. `scripts/test_user_update.py` is tracked too. The original report — that it wrote a non-existent `User.account_size` and would `AttributeError` on first run — was accurate when written; the script has since been corrected.

- **Economic-event awareness — record first, gate later.** Log every scheduled macro release (CPI, PPI, NFP, FOMC, ISM) with its **exact ET release timestamp**, plus a 09:00 ET morning summary of what is scheduled today. Report-only: no signal consumption, no auto-disable, engine untouched. Same data-first pattern as B2 (entry-drift) and A1 (GFV reservations). **Design is settled — see BRAINSTORM.md, "Economic-event awareness".** Promote to the numbered list once the release-tier question below is answered.
    - **A calendar, not a news feed.** SPY dilutes single-name news to nothing; macro hits every position in the same second. The upstream source (Fed FOMC dates, BLS release schedule) publishes a year ahead and is free, so v1 seeds ~20 entries in a repo YAML rather than taking a vendor key and a network dependency. Narrative-news vendors (Benzinga / Polygon / Finnhub / Marketaux) are **deferred, not rejected** — their real value is *unscheduled* events, a category that is essentially empty for an index ETF, and becomes real the day the book holds single names.
    - **Windows, not days — and the ranking is backwards from intuition.** Danger to *this* book is **FOMC 14:00 > 10:00 releases (ISM/sentiment/JOLTS) >> CPI 08:30**. We enter after `entry_after_open_minutes` and are flat by 15:45, so an 08:30 print resolves *before* we ever have a position — we buy after the IV crush, not into it. The Fed is the one we hold long premium straight through.
    - **Store timestamps, not dates.** A row saying "today had CPI" can never test a window size. With exact release times we can go back through fills and ask whether entries within 15 / 30 / 60 min of a release did worse, and let the data pick the window — and since MFE/MAE is captured per trade, measure *how hard* they went against us, not just whether they lost.
    - **Verdict is per-DAY, not per-strategy.** A CPI print is true for every strategy at once. Any future per-strategy column reads the day's row rather than computing its own. New table ⇒ **migrate dev *and* prod before editing `models.py`** (`reload=True` hits the shared DB instantly).
    - **Scheduler:** copy the two-stage anchor in `services/email_report_scheduler.py` — 03:00 ET cron reads Tradier `markets/calendar`, then a one-shot at `open.start − 30min`. Holidays fall out for free; a flat `CronTrigger(hour=9)` fires on them.
    - **~~Strategy-direction mapping~~ — already solved.** `engine/signal_generator.py:60` `resolve_direction()` is the single resolver and `schemas.py:211` validates it on write. No `bias` column needed. (Moot for a per-day verdict; unblocks the story-news half if ever built.)
    - **Deferred gate — `avoid_economic_news` is a lie today.** All eight templates set it (`strategy_templates.py:99,148,198,247,297,346,395,444`) and nothing reads it; the engine advertises the behavior and does not have it. Wiring it up is a **blackout window**, which inherits the engine rules: compose most-restrictive-wins with `signal_generator.py:289` (`entry_after_open_minutes` ∧ `user.trading_window_start` ∧ forced-exit time), never widen them, and let `side='sell'` through so a blackout cannot trap an open position.
    - **Open:** which release tiers to seed (Fed-only, the big four, or the full ~20 including 10:00 second-tier prints); whether to cross-check the annual seed against a free vendor or trust the published schedules. **Note the evidence limit:** CP-1 makes trades ≤ 2905 untrustworthy and the 174 churn trades drag everything until filtered, so clean history starts 2026-08-25 — roughly one CPI and one FOMC. This cannot be answered retroactively; the value of v1 is starting the clock.

---

# RESOLVED — kept for the reasoning

Items that were live to-dos, are now fixed, and whose write-up is worth keeping: the reasoning that
justified each change, and in several cases an explicit *do not "fix" this back* note. Moved here
from the numbered streams on 2026-09-09 so those streams contain only open work. Nothing was
deleted — every word below stood in A–I before the move, and the item numbers are unchanged so
existing cross-references still resolve.

One-line summaries of older completed work live in **DONE** below; this section is for items that
carry an argument.

### D3. ~~The drawdown gate was a latch, not a limit~~ *(FIXED 2026-09-05)*

> `RiskManager._check_max_drawdown` compared the **worst drawdown ever recorded** against the
> limit. A running maximum only rises, nothing reset it, and the query had no date filter — so one
> bad stretch retired the strategy permanently. It kept reading as **Active**, kept evaluating,
> kept generating signals, and silently refused every entry, with no alert and nothing on screen
> to explain it. The only way to clear it was to edit the database.
>
> **Caught at $2.43 of margin.** Measured on prod 2026-09-05:
>
> | | worst-ever dd | current dd | limit (10% of $1,214.25) | headroom |
> |---|---|---|---|---|
> | strategy 3 (calls) | $119.00 | $119.00 | $121.43 | **$2.43** |
> | strategy 4 (puts) | $71.00 | $71.00 | $121.43 | $50.43 |
>
> **What changed.** The gate now measures the **current** distance below the strategy's own
> high-water mark, so winning the drawdown back lifts the block. Trades are also now read
> `ORDER BY timestamp` — a cumulative running total was previously computed over whatever order
> the database happened to return, which made `peak` (and therefore the drawdown) arbitrary.
>
> This is deliberately **more permissive** than before: current drawdown can never exceed
> worst-ever. That is the point — the old bound was not a risk control, it was a latch.
>
> **It does not remove the near-miss.** Strategy 3 is currently sitting *at* its trough, so
> current dd == worst-ever dd == $119.00 and the $2.43 headroom is unchanged. The next losing
> trade still pauses it. The difference is that it now **un-pauses on recovery** instead of
> retiring. Open question: 10% of a $1,214 account is ~2 losing trades — decide whether
> `max_drawdown_pct` is tuned for an account this size.
>
> **The recovery path is narrower than it first looked.** Current drawdown only shrinks when a
> trade CLOSES, a trade can only close if it was OPENED, and opening is exactly what the block
> prevents. A blocked strategy holding nothing therefore *cannot* trade its way out — the only
> escapes are a position that was already open when the block tripped, or `account_size_usd`
> growing until 10% of it clears the drawdown (from $1,168 that needs $1,650, +41%, and it would
> have to come from another strategy). So the fix converted "blocked forever because you EVER had
> a bad stretch" into "blocked forever because you are CURRENTLY in one" — strictly better, and
> still a latch while enforcement is on.
>
> **Hence two settings, not one:**
>
> | key | meaning |
> |---|---|
> | `max_drawdown_pct` | threshold as % of account. **`<= 0` disables everything** — no alert, no block, and no DB query. |
> | `max_drawdown_block` | `True` (default) crossing it stops entries; `False` it only raises an alert and the strategy keeps trading. |
>
> Alert-only is the useful mode on a small account: the strategy keeps trading, so it can climb
> out on its own and the alert is genuinely self-clearing. `max_drawdown_block` defaults to `True`
> so nothing that has not explicitly opted out changes behaviour.
>
> Reading the settings now happens BEFORE the trade query, so a disabled gate costs nothing. That
> query loads the strategy's entire history and runs on every entry attempt — 321 times on
> 2026-09-02.
>
> Bleed alerts (`notify_strategy_bleeding` / `notify_strategy_recovered`) fire once on the
> transition over the threshold, and clear with **hysteresis at 80%** so a strategy sitting on the
> line does not alternate messages.
>
> **Still deferred:** the lookback window and a manual clear. Both only matter with
> `max_drawdown_block=True`, which nothing currently uses.
>
> Tests: `api/tests/test_max_drawdown_recovery.py` (28 cases: recovery to a new high, recovery to
> flat, still-in-the-hole, insertion-order independence, badge/gate agreement, account-size
> scaling, notification safety, the off switch, absent-means-default, alert-only mode, re-alert
> suppression across 50 evaluations, and the hysteresis band).

---

### D4. ~~A blocked strategy looked identical to a healthy one~~ *(FIXED 2026-09-05)*

> Every silent entry block had the same symptom: an account that quietly stops trading, which is
> indistinguishable from a market with no setups. Now surfaced two ways.
>
> **Discord** — `notify_strategy_blocked` / `notify_strategy_unblocked`, gated on a new
> `notification_preferences.discord.notify_risk` (defaults True). Fired **once**, on the
> transition into the blocked state, and once again on recovery with the count of entries skipped
> in between. Throttling is not optional here: 2026-09-02 produced **321 entry signals in one
> day**, and this gate is evaluated on every one of them. Mirrors the
> `OrderManager._cash_block_state` idiom — announce the transition, count the repeats quietly.
>
> **UI** — the strategies table shows a `Blocked` chip beside `Active`, with the reason on hover.
> Backed by `RiskManager.get_entry_block_status`, a read-only evaluation that runs the same
> private checks in the same order as `validate_pre_trade`, so the badge cannot disagree with the
> engine. It writes nothing and commits nothing; a failure is swallowed and the page renders
> without a badge rather than 500ing.
>
> Covered codes — the blocks with no other symptom: `mode_mismatch`, `account_daily_loss`,
> `strategy_daily_loss`, `max_drawdown`. Deliberately **excluded** as self-evident: an inactive
> strategy, the manual "done for the day" halt, and the position cap (normal operation, fires
> constantly). Out-of-cash entries already have their own `ENTRY_SKIPPED_NO_CASH` event.

---

### D5. ~~`_log_risk_event` raises TypeError — a tripped cap DEACTIVATES the strategy~~ *(FIXED 2026-09-07)*

> **Fixed exactly as prescribed below, verified 2026-09-07.** `_log_risk_event` now writes
> `details={"reason": message}` instead of `message=`, and wraps the write in the same try/except
> as `_log_account_risk_event` — with a rollback — so a logging failure can never decide whether a
> trade happens. The `logger.warning` is outside the try, so the event is still visible even when
> the row cannot be written.
>
> The test the item asked for exists: `api/tests/test_risk_event_logging.py` trips all three gates
> **through `validate_pre_trade`** (not the private checks), asserts a failed write still returns a
> clean `rejected`, and asserts a SELL is approved on every one of the four gates. All passing.
>
> ~~Uncommitted as of 2026-09-07~~ — **committed since**; `api/tests/test_risk_event_logging.py` is
> tracked. Verified 2026-09-09.

`RiskEvent` has no `message` column (`models.py`) — it carries `details` JSON. `_log_risk_event`
passes `message=message` to the constructor anyway, and unlike its sibling
`_log_account_risk_event` it has **no try/except**. Reproduced:

```
TypeError: 'message' is an invalid keyword argument for RiskEvent
```

The docstring on `_log_account_risk_event` already names this ("the legacy `_log_risk_event`,
which references a `message` column that doesn't exist on the model") — the newer writer was
written correctly and the old one was left in place.

**Three gates route through it:** the per-strategy daily loss limit, max drawdown, and the
position cap. So a *clean rejection* becomes an *exception*, and then:

```
cap trips -> TypeError -> caught at strategy_executor.py:229 -> state.error_count += 1
          -> repeats on every entry attempt
          -> at 20 consecutive errors: strategy.is_active = False   (:238)
```

**Hitting a daily loss cap does not pause the strategy for the day — it turns the strategy OFF,
and it stays off tomorrow.** 2026-09-02 produced 321 entry signals in a day; 20 consecutive
errors is a couple of minutes.

**Reachable on the next session.** The per-strategy default is 5% of account = **$60.71**, about
two typical losing trades ($46/$39/$34 observed).

Knock-on: the D4 alerts never fire on these paths — `_note_entry_block` is called *after*
`_log_risk_event`, so the exception pre-empts it. A strategy that deactivates itself this way
sends nothing.

Not caused by the D3/D4 work; it predates it. Contained in one respect: exits are unaffected,
because a strategy holding a position runs the exit-only tick, which never calls
`validate_pre_trade`.

**Fix:** make `_log_risk_event` match `_log_account_risk_event` — write `details={"reason": ...}`
instead of `message=`, and wrap it in the same try/except so a logging failure can never decide
whether a trade happens. Needs a test that trips each of the three gates through
`validate_pre_trade` (the existing tests call the private checks directly and miss this).

---

### E1. ~~The trailing stop is unreachable by construction~~ *(FIXED 2026-09-03 — exercised live 2026-09-04)*

> **Fixed in `signal_generator.check_exit_signal`.** Order is now stop loss -> trailing stop ->
> take profit, and critically the **take profit is SUPPRESSED while the trail is armed**.
> Reordering alone would not have worked: at the tick where price touches +TP the trail is not yet
> hit, so it falls through to the target regardless — the target has to stand down for the trail to
> govern. Unchecking `trailing_stop` restores the old behaviour exactly.
>
> **Exercised live 2026-09-04 — the branch fires, and it pays.** Two `Trailing stop hit:` exits,
> both on strategy 4 (puts, `SPY260904P00774000`):
>
> | entry | trail level | exit fill | realised | |
> |---|---|---|---|---|
> | $2.97 (10:29:30 ET) | $4.44 (peak ~$4.93) | $4.50 | **+$153** | the flat +30% target would have sold at $3.86 = +$89 |
> | $2.88 (10:16:39 ET) | $3.02 (peak ~$3.35) | $3.02 | **+$14** | armed just past +15%, then reversed |
>
> The $153 trade is the proof this item was waiting for. `take_profit_percentage=30` was correctly
> suppressed while the trail was armed, so the position ran to a ~$4.93 peak instead of being sold
> at $3.86 — **+$153 against +$89**; the flat target would have surrendered 42% of the move.
>
> The $14 trade is the other side of the trade-off, exactly as predicted below: armed at ~+16%,
> reversed, exited at +4.5% rather than running to the target. A small win instead of a probable
> stop-loss — the cost of letting winners run.
>
> Source: `logs/livetest-2026-09-03/engine-20260903-061605.log` lines 28859 and 29072 (the 09-03
> log file spans into the 09-04 session).

The original finding, kept for the reasoning:

> **2026-09-02 — FIXED, and option (a) as written below does NOT work.** Reordering the branches
> changes nothing: the flat target fires on the way UP, at the tick price first crosses +25%, when
> no pullback yet exists for the trail to be hit by. At that tick the trail falls through and the
> target sells regardless of which is checked first. For both to be true on one tick the peak must
> reach 1.25/0.90 = +38.9%, which the target already prevented the position from reaching.
>
> What shipped instead — `signal_generator.check_exit_signal`, order now SL → trail → TP:
> 1. **Arming latches on the peak.** It re-tested the live `pnl_pct` every tick, so the trail
>    switched itself off during the pullback it exists to catch; nothing could fire below a peak of
>    1.15/0.90 = **+27.8%**, not the +15% configured. Now armed off `position.peak_price` /
>    `trough_price` (with a 1e-9 tolerance — `(2.30-2.00)/2.00` is 14.999999999999998).
> 2. **The flat take-profit stands down while the trail is armed.** The two rules are mutually
>    exclusive above the activation threshold; the target has to yield or the trail cannot govern.
>    Consequence on strategy 3 (`activation 15`, `take_profit 25`): the target is now dead — every
>    position that arms the trail exits via the trail.
>
> Stop loss is untouched and still outranks the trail. Below activation, and with `trailing_stop`
> unchecked, behaviour is identical to before — **unchecking the box in the strategy form is the
> revert**, live within ~30s via `db.refresh(strategy)`, no deploy. Tests:
> `api/tests/test_trailing_stop_arming.py` (18 cases: arm/disarm boundaries, the 09-02 runner
> replay, SL precedence, shorts, trail-off regression).

> 📜 **Everything from here to the end of E1 is the original 2026-09-02 analysis, preserved for the
> reasoning that justified the fix. It describes the PRE-FIX engine and is no longer true — the
> trail is reachable, has fired live, and neither fix option below is what shipped.** Current state
> is at the top of this item.

Prod strategy 3 is configured `trailing_stop=true, activation=15%, distance=10%,
take_profit=25%`. `signal_generator.check_exit_signal` evaluates in a fixed order, each branch
returning immediately:

```
1. take profit    (25%)   -> return
2. stop loss      (15%)   -> return
3. trailing stop  (arms at 15%)   <- never reached
4. max hold time
```

The trail arms at +15% but take profit fires at +25% and returns first, so **any position that
would arm the trail is sold before the trail can act.** It has never executed and cannot at these
numbers. A configured feature that is dead code — not a tuning preference.

**Fix options.** (b) is preferred as the first move: it is a data change, reversible from the
portal, needs no code, and is therefore testable without touching the exit path.

- **(a) Reorder** — evaluate trailing before the flat target. Once up 15% the trail governs and the
  flat 25% only fires on a gap through it. Changes behaviour most aggressively.
- **(b) Raise `take_profit_pct`** above the trail's useful range (e.g. 60%), leaving the trail as
  the normal exit and the target as a ceiling.

**What it affects — this is a real trade-off, not a free win.** Winners run further and exit below
their peak; hold time rises; round-trip count falls. But a position that reaches +15% and then
reverses now exits near +5% instead of at +25%, converting some current winners into smaller ones.
Every exit the engine makes is affected, so it wants tests, not a quick edit.

**Evidence (2026-09-02).** `SPY260902C00760000` ran 3.27 -> session high 6.40. The engine took
+25.7%, immediately re-entered the same contract, and took +24.8% again:

| | settled cash used | P&L | return on cash |
|---|---|---|---|
| actual: two 25% round trips | $750 | +$189 | 25% |
| one position with a working 10% trail (exit ~5.76) | $327 | ~+$249 | 76% |

The P&L difference is modest (~+$60). **The cost that matters is the cash** — see E2.

---

### E5. ~~Capture MFE/MAE per trade — the data is being destroyed~~ *(DONE 2026-09-05)*

> **Shipped.** `trades.mfe_price` / `mae_price` added (migration `a1b2c3d4e5f6`, applied to **DEV
> and PROD**), and `order_manager` snapshots `position.peak_price` / `trough_price` onto the SELL
> leg at close — before any re-entry can reset them. Covered by
> `api/tests/test_mfe_mae_capture.py`, whose load-bearing assertion is that a reopen wipes the
> position's peak while the already-closed leg keeps its own.
>
> Note the reset only fires on the **reopen** path (a row already at `qty=0`). With `qty>0`
> `_update_position_entry` averages into the open position and legitimately keeps the peak.
>
> **Migration gotcha for next time:** the first PROD attempt stalled 4.5 min and had to be
> cancelled. The running engine holds connections `idle in transaction`, which keeps an
> `AccessShareLock` on `trades`; the `ALTER` queued for `AccessExclusiveLock`, and a queued
> exclusive request makes every later reader queue behind it too. **Stop the app before DDL on
> `trades` / `positions`.** Nothing was half-applied — the transaction rolled back clean.
>
> Data starts accumulating from the next live session. Historical trades stay NULL.

The original finding, kept for the reasoning:

`Position.peak_price` / `trough_price` are Maximum Favorable / Adverse Excursion in all but name,
and they are the single most useful diagnostic for exit-rule quality. **They are currently
unrecoverable after the fact.**

Two problems:

1. `Trade` has **no** `peak_price` / `trough_price` columns — MFE is never written to the
   immutable record.
2. `order_manager.py:1348` resets `position.peak_price = price` on every reopen, and position rows
   are reused for re-entries. So MFE survives only for a row's **most recent cycle**.

On 2026-09-02 that already cost us: trade 1's peak was overwritten by trade 2's re-entry into the
same contract, hours after the fact. Only pos2's peak survived long enough to be read — and it is
the evidence that the day's only loser was +22% before it reversed
(`docs/live-test-results-2026-09-02.md` §F7b). **Every future session loses this silently.**

**Fix:** add `mfe_price` / `mae_price` to `Trade`, and copy `position.peak_price` /
`trough_price` onto the sell-leg Trade row in `_update_position_exit` before the reopen path can
reset them.

**Sequencing — this is not a UI change.** Model change -> Alembic migration on **DEV *and* PROD**
before the model edit lands (`reload=True` means a models.py save hits the live shared DB
instantly) -> `order_manager` write (engine code, so it needs the usual care and a test) -> then
the metric is computable and the UI can show it.

**Do this before E1.** E1's whole case rests on MFE, and right now the argument can only be made
from one surviving row. A week of captured MFE turns "it cost a winner on 09-02" into a
distribution.

**Metric it unlocks:** *MFE capture ratio* = realized P&L / MFE. 09-02 was `100%, 100%, -70%`. A
persistently low ratio means the exit rule is systematically leaving the move behind; a negative
one means a position that was well in profit closed at a loss.

---

### F1. ~~The account event stream watches the SANDBOX account during live trading~~ *(FIXED 2026-09-07)*

> **Fixed and verified in the live process the same evening.** Connect line now reads
> `wss://ws.tradier.com/v1/accounts/events (env=live account=6YB***56)` — the account the orders
> actually go to.
>
> Three changes: `TradierAccountStreamManager` takes a client provider, injected by `app.py` from
> the same per-user routing the order path uses; `reconcile_user_history` uses
> `TradingClientManager.get_client(user)`; and six market-data callers moved to a new
> `get_market_client()` that forces the live endpoint, so paper mode reads real prices and a live
> process never reads market data over a sandbox host.
>
> Two things that let it hide are now closed: the connect log prints `env=` and a masked account,
> and a missing provider logs a WARNING rather than falling back silently. `get_tradier_client()`
> carries a docstring saying it is only safe for non-account calls.
>
> Tests: `api/tests/test_account_stream_account_routing.py` — live provider gets the live socket,
> paper still gets sandbox (not force-live), no provider falls back, a throwing provider cannot
> take the stream down.

`tradier_account_stream._create_session_sync` calls `get_tradier_client()` — a module-level
singleton built from `settings.TRADIER_ENV` in `.env`, currently `sandbox`. Orders route
per-user through `TradingClientManager.get_client(user)` on `user.selected_trading_mode`,
currently `live`. The two disagree, and nothing reconciles them:

```
orders            -> LIVE account 6YB70356
account WS stream -> wss://sandbox-ws.tradier.com  (sandbox account)
```

Confirmed in the 09-02 and 09-06 engine logs: `Account event stream connected:
wss://sandbox-ws.tradier.com/v1/accounts/events` while the session traded real money.

**Effect:** live fills are never pushed. Confirmation falls back to the 30s REST poll — the
exact path this stream was built to backstop after 2026-07-13, when two orders filled while
the poll expired and left the engine holding 6 unrecorded contracts. All 09-02 fills
reconciled correctly via REST, so this is latent rather than broken, and the code comment at
`tradier_account_stream.py:130` asserts the opposite of what happens.

**Second site, same bug:** `services/tradier_reconcile.reconcile_user_history` (line 118) also
calls `get_tradier_client()`. It pulls account history and writes commission/fees onto local
`Trade` rows — so run against a live account it reads SANDBOX history and reconciles fees from
the wrong account. Only reachable from the manual `POST /account/reconcile-fees` endpoint, not
the engine loop, so it misfires only when someone calls it.

**The fix already exists in the router.** `tradier_integration/router.py:29` added `_client(user)`
for exactly this reason — its docstring says the singleton "always hit sandbox regardless of the
user's live/paper selection". Both remaining sites need the same treatment.

**Market data is NOT affected — verified 2026-09-07.** Sandbox and live return byte-identical
quotes, greeks and open interest (`SPY 769.42/769.55`, `SPY260908C00768000 bid 3.00 ask 3.03
oi 1193 delta 0.6736` from both). Tradier's sandbox serves real market data and only fabricates
fills, so the six singleton callers that read quotes, chains, the clock and greeks are correct.
Only the two account-touching sites above are wrong.

**Fix:** the stream needs the same per-user client the order path uses, not the env singleton.
That means giving `TradierAccountStreamManager` a user (or a client factory) rather than
letting it resolve its own — worth care, since it is a singleton shared across strategies and
the market stream is deliberately always-live.

---

### H1. ~~`held[0]` + `_flatten_other_contracts` orphans a second contract~~ *(fixed 2026-08-26)*

`_flatten_other_contracts` now takes `broker_holds` and zeroes only rows the broker does **not**
report, and both recovery paths pass the adoptable set in. `_startup_sync` additionally sorts `held`
so a contract this strategy already has an open row for is adopted ahead of one it does not — the
choice no longer depends on Tradier's response ordering.

Was deferred as out-of-scope on 2026-08-26, then fixed the same day because the F3 change (adoption
no longer defers to a *dead* strategy's claim) moved the trigger from "hand-buy a second strike in
the portal" to "any strategy auto-stops while holding", which the 20-consecutive-error auto-stop
makes routine.

**Residual:** a strategy can now legitimately hold two open rows when the broker holds two
contracts. That is fine — `_check_exit_signals` (`strategy_executor.py:368`) iterates **every** open
row for `(user, strategy, symbol)`, and the forced-EOD block sits inside that same loop, so both
rows get stop-loss, take-profit and EOD handling. Only the *armed/streamed* contract is one at a
time; the second is REST-priced. Single-contract operation (`max_positions: 1`) is unaffected.

(An earlier version of this note claimed the second row was "not actively managed for SL/TP". That
was wrong — do not "fix" the code on the strength of it.)

---

# DONE

- [x] **Phantom P&L eliminated — the $223,119 "close" on a Saturday, and three siblings.** `_reconcile_position` books a closing Trade when the broker shows flat but the DB holds qty; when `_broker_close_fill()` found nothing (Tradier `/orders` covers only the **current session**, so any previous-day close is invisible) it fell back to `position.current_price` — which held **SPY's underlying price**, because `strategy_executor.execute_exit_tick` wrote the raw tick price to the position whenever the option quote hadn't arrived. `(747.03 − 3.30) × 3 × 100 = 223,119`. **This silently disabled the daily-loss cap**: `Position.unrealized_pnl` feeds `risk_manager.py:248`/`:448` and the phantom `Trade.pnl` feeds `realized` at `:241`. Fixed at both ends — positions are now marked off the **held contract's** resolved price (never the underlying tick), and `_fallback_exit_price()` walks broker fill → REST quote → own mark, sanity-checking every candidate against the underlying and booking **at cost with an ERROR log** rather than inventing a figure. Four historical rows corrected to expiry settlement (`max(0, SPY close − strike)`, closes from `/v1/markets/history`); all-time P&L **+$220,942 → −$3,035.37**. Originals in `scripts/backups/`, correction in `scripts/fix_phantom_expiry_pnl.sql`, each row stamped `notes.corrected_at`. Prod was empty. Also fixed a missing `×100` in the partial-close `unrealized_pnl` and a `multiplier` scoped inside a sibling branch (a latent `NameError`). _(2026-08-25, Part 2)_

- [x] **Forced-exit time is now the ENTRY cutoff — 174 pointless round trips per the last six weeks, stopped.** `check_entry_signal`'s time gate had an upper bound **only when `user.trading_window_enabled`**, which was off. So the 15:45 forced exit sold, and the engine bought again at 15:46 — every day, 174 entries after the cutoff for **−$1,064.46** in spread, 12 of them placed at/after 16:00 ET on a 60s-stale market clock. One straddled the bell (2026-07-31 16:00:41), never exited, expired, and became the phantom above. The gate now reuses `forced_exit_time_et()` as its upper bound so entries stop exactly when exits start and the two can never drift apart. **Note: the EOD exit itself was never broken** — it is the single most common exit reason in the history (71 of the last 60 days' closes). What was missing was its entry-side counterpart. _(2026-08-25, Part 2)_

- [x] **`exit_before_close_minutes` floor of 15, enforced in three layers.** Previously opt-in and falsy at `0`, with the strategy form defaulting to `0` and a hint that read *"0 = disabled"*. Now: the engine clamps anything below 15 (`FORCED_EOD_EXIT_FLOOR_MINUTES`, unconditional, composes most-restrictive-wins so a strategy asking 30 still gets 30); the API rejects 0–14 with a 422 (`schemas.py`, deliberately on `StrategyCreate`/`StrategyUpdate` and **not** `StrategyBase` — `StrategyResponse` inherits Base, and a legacy row must stay *readable* even when no longer *writable*); the form defaults to 15 with `Validators.min(15)` and loads a legacy `0` as `15` via `Math.max` (`??` does not fire on `0`, so it would otherwise be permanently unsaveable). The rule is **minimum 15, not "not zero"** — the value counts backwards from the bell, so 5 would be later than the floor and equally broken. _(2026-08-25, Part 2)_

- [x] **Notifications report dollars, not premium.** `notifications/reports.py` computed `multiplier = 100 if is_option_symbol(trade.symbol)` — but **`Trade.symbol` is the underlying** (`"SPY"`), never the OCC symbol, so that was **always False** and email Cost/Proceeds were **100× too small** ($2.23 where $223 was committed). Now joins `Position` and prefers `notes.option_symbol`, adds Capital-deployed / Proceeds / Return-on-capital totals computed over **all** trades rather than the 50 that fit the table, and is restyled to the flat-terminal language (hero P&L, stat tiles, zebra rows, tabular numerals, zero `box-shadow`). Discord embeds moved from a 3-across field grid to an aligned monospace table with `premium → dollars` on one line, Cost / Proceeds / Return %, and readable contract names via new `parse_occ_symbol()` / `format_contract()` (`SPY260825C00745000` → `SPY $745 CALL 8/25`). `close_position` now records `option_symbol` in its notes so a close can be attributed to a contract at all — the position row cannot answer that, since closed rows are reused. Both channels test-sent and verified. _(2026-08-25, Part 2)_

- [x] **Data-accuracy checkpoint system.** `scripts/verify_data_checkpoint.sql` asserts seven invariants the 2026-08-25 fixes guarantee, scoped to post-checkpoint rows so historical damage can't mask a regression. It is self-validating — run it with `cp_trade_id=0` and checks 2/3/5 **fail** against history (186 / 4 / 1225 rows), which is how a PASS is known to mean something. Registry at the top of `JOURNAL.md` (grep `DATA ACCURACY CHECKPOINT`) with instructions for adding CP-2. **CP-1 (`trades.id > 2905`) is PENDING** — it opens at the first engine start after these fixes deploy, not on the date they were written. _(2026-08-25, Part 2)_

- [x] **Tradier is now the only broker — Alpaca and Schwab fully removed (91 files).** Deleted `api/alpaca/` (a vendored copy of the alpaca-py SDK, committed to the repo — which is why `import alpaca` resolved even though `alpaca-py` was never in the venv), `api/schwab_integration/`, the whole `api/services/market_data/` tree (`chain_fetcher`, `enhanced_service`, `realtime_aggregator`, `service` — all Alpaca-backed), `api/utils/multi_stream.py`, `api/services/strategy_worker.py` (the dead legacy polling worker), the Schwab auth/token scripts, `api/debug/check_chain_data.py`, nine Alpaca test scripts, and `ui/src/app/services/schwab.service.ts`. Unmounted the Schwab router from `app.py`, dropped all eight `ALPACA_*`/`SCHWAB_*` keys from `config.py`, deleted `TradingClientManager._get_schwab_client()` (never called — `get_client` routed both modes to Tradier anyway), and stripped the dead Alpaca/Schwab branches from `order_manager`'s three `_extract_*` parsers. **The UI was naming the wrong broker in the real-money confirmation dialog** ("Live trading uses REAL MONEY via Schwab API!", "Paper trading with Alpaca") — corrected to Tradier Sandbox / Tradier Live, as was the live-switch logging in `system.py`. Verified: app boots, 89 routes, **zero** Alpaca/Schwab modules loaded, Tradier contract selection intact, UI typechecks. Architecture diagram updated. _(2026-07-13)_
- [x] **Alpaca removed from the live engine greeks path.** `_refresh_greeks` was calling Alpaca's option-snapshot endpoint every 5 minutes per strategy — a *blocking* HTTP call on the shared event loop — and Alpaca's free tier returns **no greeks**, so it wrote `None` over `None` forever. Because both gates in `SignalGenerator` are guarded on `is not None`, the **delta band and `min_open_interest` filters were silently skipped on every entry, permanently, since the day they were written**. Greeks now come from the Tradier chain at contract selection (zero extra API calls — selection already reads them). _(2026-07-13)_
- [x] **Drift-driven contract reselection.** A contract was armed once and then held — sometimes for hours — while 0DTE gamma walked its delta out of the strategy's band, and it was bought anyway. `_check_contract_drift` now re-prices the armed contract every 30s via `get_quotes(greeks=True)` and disarms it if it has left the band, so the next tick selects a fresh strike. Disarming (rather than just rejecting the entry) is what avoids a deadlock: selection only runs when `option_symbol is None`. Also fixed a **subscription-accounting bug found in the re-audit** — teardown used a stale startup snapshot, so a strategy that swapped contracts would unsubscribe a symbol another live strategy was holding, killing its market data. Each strategy now tracks its own `streamed_symbols`. _(2026-07-13)_
- [x] **Unconfirmed-order safety + fill backfill.** On 2026-07-13 two orders filled at the broker while `_await_terminal_order` timed out at 30s; the engine wrote no Position row and believed it was flat while holding 6 TSLA contracts — no stop, no take-profit, free to stack another entry. Now: an unconfirmed order **blocks further BUYS** for that strategy (never sells — an exit must always run), and the reconcile tick re-polls it and backfills the Trade row at the broker's real `avg_fill_price`. `_reconcile_position` also writes a Trade row when a position is closed **outside** the engine (a hand-close in the Tradier portal previously zeroed the position but dropped its −$104 from P&L history entirely). _(2026-07-13)_
- [x] **Tradier account/order event stream.** `api/engine/tradier_account_stream.py` subscribes to order lifecycle events so fills are **pushed** instead of polled — `_await_terminal_order` now sleeps on the stream and wakes in milliseconds. It is an *accelerator, not a replacement*: REST polling remains the fallback, so if the stream drops the engine behaves exactly as before. Confirmed a market stream and an account stream **run concurrently** (Tradier's "one session at a time" is per stream-type; separate session endpoints and sockets) — verified live against sandbox. Note the account event carries **no symbol and no side**, and names its quantity `executed_quantity` (not REST's `exec_quantity`), so it is only ever a notification keyed on order id. _(2026-07-13)_
- [x] **Performance page P&L no longer comes from Tradier's `/gainloss`.** That report's FIFO lot matcher does not retire closed buy lots when a contract is round-tripped repeatedly, so it reported **−$21,057** for a day that actually lost **−$1,851** (one 0DTE contract bought and sold 50 times as it decayed 6.10 → 0.39: real cost 14,244, reported cost 34,908). It is also paginated, so a busy day was truncated on top of being wrong. New `GET /performance/closed-trades` computes from the engine's own `Trade` rows, which pair each exit with the entry that opened it at fill time — correct by construction, no lot matching. Added the missing **1D** period filter. Also fixed `calculate_performance_metrics`, which read `t.entry_price` and `t.asset_class` — **neither column exists on `Trade`** — and had been returning HTTP 500 for any strategy with trades. _(2026-07-13)_
- [x] **Negative-expectancy fix + 2026-07-13 P&L reconciled to the cent.** Both strategies ran a stop loss WIDER than their take profit (TSLA 20/15 → needed a 57% win rate; SPY 50/25 → needed 66.7%) — and SPY's `params_json` carried **both** key spellings with different values, with `signal_generator.py:355` reading `_pct` first, so **the UI showed a 15% stop while the engine enforced 50%**. Both now 1:2 (SL 15 / TP 30, break-even 33.3%), with all four keys and both columns written together so nothing can silently disagree again. `scripts/reconcile_2026_07_13.py` backfilled the three fills the engine dropped and repriced one adopted-position exit, bringing the DB to **−1,851.00**, matching the broker exactly. **⚠️ Corrected 2026-07-14:** the original claim that "the strategy is still negative-EV at its measured 31% win rate (−1.08%/trade, Sharpe −0.146)" was **wrong** — those numbers came from Tradier sandbox fills, which are fabricated (sandbox filled a 749 call at 1.84 while SPY was at 752, i.e. **below intrinsic value**). The *structural* fix (stop wider than target) was right; the *performance* claims were built on fiction. See the corrected `docs/negative-expectancy.md`. _(2026-07-13, corrected 2026-07-14)_
- [x] A view in performance that shows a calendar with each day being green or red with the gain/loss inside the data block. _(2026-05-03)_
- [x] Dark mode + colorblind mode (blue/orange palette) toggleable from the user menu. CSS custom properties (`--color-profit`, `--color-loss`, `--surface`, `--text`, `--border`, etc.) drive theming; future UI work should use these tokens instead of hardcoded colors. _(2026-05-03)_
- [x] Account-level trading window. Toggleable per-user start/end time (ET, "HH:MM") in the user menu; layers on top of per-strategy `entry_after_open_minutes` / `exit_before_close_minutes` with most-restrictive-bound-wins semantics so users can never widen past strategy defaults. _(2026-05-05)_
- [x] Time-exit visibility & editability — open positions appearing to auto-close at fixed intervals were strategy-defined (`params_json.max_hold_time_minutes`), not engine-defined. Added a 30s INFO heartbeat per active strategy in `stream_driven_worker.py` so the loop is never silent. Surfaced `max_hold_time_minutes`, `entry_after_open_minutes`, `exit_before_close_minutes`, and trailing-stop fields in the strategy edit form so the value can be tuned without DB pokes. Strategy 3's value remains 30 — user judgment call whether to set 0 / 90 / 120. _(2026-05-06)_
- [x] Per-user Discord notifications for trade opens and closes. Replaced the "SMS notifications" idea after weighing Twilio cost / A2P 10DLC overhead against existing Discord patterns — Discord is free, instant, and formats embeds nicely. Per-user webhook URL stored in `User.notification_preferences.discord` (JSON column), opt-in toggles for open/close, "Send test message" button in the dialog. SSRF-guarded: schema validator + dispatcher both reject anything that isn't an official Discord webhook host. Fire-and-forget daemon thread so a slow webhook never blocks the post-fill path. _(2026-05-06, Part 2)_
- [x] Discord close-notification audit: confirmed exactly one fire per real fully-closed position across all three call sites (`close_position` post-terminal-filled, `_update_position_exit` post-fully-closed, runtime `_reconcile_position` for broker-UI manual closes). Every bailout (throttle/preview-fail/broker-reject/unconfirmed/non-filled-terminal) returns before notify. Reconcile early-returns on local qty<=0 so it can't double-fire after a strategy-driven close. `apply_trade` referenced in the original TODO doesn't exist in the code; startup-sync manual-close path stays silent by design. _(2026-05-09)_
- [x] End-of-period email reports (daily/weekly/monthly/quarterly/yearly) via Resend. Two-stage scheduler: 03:00 ET cron pulls `markets/calendar` for today's actual close (handles early-close days), schedules a one-shot DateTrigger at close+30min. Dispatcher iterates opted-in users and per-user fires daily always, weekly/monthly/quarterly/yearly only on the period's last trading day (next-open lookup against the live calendar). Daily/weekly skip empty periods; monthly+ always send. Aggregation reads `Trade` rows (closing legs only, anchored on `exit_timestamp` in ET-localized windows). Self-contained inline-styled HTML email + plain-text fallback. Per-user prefs in `User.notification_preferences['email_reports']`; opt-in dialog in the user menu with per-period checkboxes, "Send test report" button (real-shaped daily report), and an "off" banner when disabled. _(2026-05-09)_
- [x] User profile editing — name, email and password change in a "Profile" entry on the user menu. Email-uniqueness check on PATCH so a collision returns a clean 400 instead of a DB unique-violation 500. Password change requires `current_password` + `new_password ≥ 8 chars`. JWT subject migrated from email → user id (`str(user.id)`) so an email change mid-session no longer invalidates the access token; existing tokens require one re-login after deploy. Email change automatically re-targets email reports because the dispatcher reads `User.email` at send time. _(2026-05-09)_
- [x] Fee tracker on the performance page. Confirmed already in place: `Trade.fees` + `Trade.commission` are populated from Tradier `account/history` (regulatory fees joined per close day, commission joined per open/close day with symbol+date matching). Performance page surfaces a dedicated "Costs (Commission + Fees)" tile with the breakdown sub-line, plus a "Net P&L" tile that subtracts costs from realized P&L (`performance.component.ts:186-189, 226-239`). Per-position attribution writes `commission`/`fees`/`net_pnl` onto every closed-position row (`performance.component.ts:455-462`) so the trade table can show them. No additional work needed. _(2026-05-09, Part 2)_
- [x] Account-wide daily loss cap + dashboard visibility. New `User.daily_loss_limit_pct` (default 5%, bounded 0.5–20). `RiskManager._check_user_daily_loss_limit` sums realized+unrealized PnL across all of a user's strategies for the day and halts new entries account-wide once breached; sells stay open so existing positions remain closeable. Wired before per-strategy checks in `validate_pre_trade` (most-restrictive-bound semantics). New `GET /risk-events/account-status` powers an overview-page session-status tile (PnL with realized/unrealized split, % cap consumed, $ remaining before halt, status badge OK / WARNING / HALTED at 0/80/100, progress bar that switches color via SCSS class). Refreshes every 30s so unrealized ticks don't go stale. Profile dialog gained a Risk-limits section. New `--color-warning*` tokens added to `styles.scss`. See journal 2026-05-09 (Part 3). _(2026-05-09, Part 3)_
- [x] Role-based access (RBAC). Five roles defined in `auth.py`: `user`, `admin`, `viewer`, `auditor`, `strategy_author` (Pydantic-validated). Layered enforcement: router deps `require_can_write_own` (blocks viewer/auditor), `require_can_place_orders` (blocks viewer/auditor/strategy_author), `get_current_active_admin_or_auditor` (read-cross-user), `get_current_active_admin` (admin-only writes). Engine-level gate at the top of `order_manager.execute_signal` blocks `side='buy'` for non-trading roles so a strategy worker that survived a role demotion can't bypass the router gate; sells go through. New `routers/admin.py` with read-only `/admin/users` list/detail/dashboard/strategies/positions/trades and admin-only `PATCH /admin/users/{id}/role` (with self-demotion guard). New Angular admin Users page (table + slide-in detail panel + role dropdown for admin / read-only pill for auditor), `adminGuard`, role badge in user menu, role-aware sidenav. Admin scope is observe-only by deliberate decision — no act-as-user path. See journal 2026-05-09 (Part 3). _(2026-05-09, Part 3)_
- [x] UI auth-header fix on new services. `risk.service.ts` (broke the overview's session-status tile with a 401) and `admin.service.ts` (would have 401'd every admin page request) were calling the backend without `Authorization: Bearer <token>`. Both now build their own `getHeaders()` returning the token from `localStorage('access_token')`, matching the convention used by every other service in the codebase. The Angular UI does NOT use an `HTTP_INTERCEPTORS` provider — `app.config.ts` calls `provideHttpClient()` without `withInterceptors([...])`, so each service is responsible for attaching the token manually. Future refactor opportunity: switch to `withInterceptors([authInterceptor])` so this class of bug can't recur (~8 files to touch). _(2026-05-09, Part 4)_
- [x] Reservation-ledger code audit + sandbox concurrency probe + entry-drift logging (A1 forward-progress). Audited `_preview_or_abort` and the reservation helpers — release-path try/finally is sound, no `await` between cash check and reservation acquire (same-loop concurrent signals atomically serialized), `cost` field correctly used per Tradier docs, sells correctly skip the gate. Wrote `api/debug/probe_buy_reservations.py` — fires N concurrent `_preview_or_abort` calls via `asyncio.gather` and asserts only `floor(effective_cash / required_per_order)` succeed. Default mode is preview-only (no real orders placed). Wired `ORDER_PREVIEW_DRIFT` event on every option buy (signal_price vs preview_per_contract) — observation only, no cancel logic. A1 still pending the actual sandbox probe run. B2 cancel-on-drift decision pending data + A1. See journal 2026-05-09 (Part 4). _(2026-05-09, Part 4)_
- [x] Per-strategy equity curve charts on the strategies page. New `GET /performance/equity-curves` returns `[{strategy_id, name, points: [{t, cum_pnl, trade_pnl}]}]` — running sum of `Trade.pnl` over closing trades (`exit_timestamp` + `pnl` not-null), ordered ascending, realized only (open-position unrealized intentionally excluded so the curve is stable). New "Equity" column on the strategies table renders an inline Chart.js sparkline (no axes, no tooltip) plus the lifetime-cumulative dollar amount, color-keyed via `themeService.chartColors()` so it follows theme/CB toggles live. Click → `EquityCurveDialogComponent` with full Chart.js line, hover tooltip (trade #, full timestamp, this-trade PnL, cumulative), and four stat tiles (total realized, best trade, worst trade, win rate). Strategies with zero closed trades show "—" — the canvas only renders for non-empty curves. Route ordering matters: `/equity-curves` is registered before `/{metrics_id}` so the path-param doesn't capture the literal. _(2026-05-09, Part 5)_
- [x] Broker routing fix — live trading mode now uses Tradier Live instead of Schwab (E1). Modified `TradierClient.__init__()` to accept optional `env` parameter (defaults to `settings.TRADIER_ENV` for backward compatibility). Updated `TradingClientManager` to route both `paper` and `live` modes to Tradier (sandbox vs live respectively), removing Schwab from the normal client selector path. All trading methods (`place_order`, `preview_order`, `get_account`, `get_history`, `get_positions`) now use Tradier for both modes. Schwab integration remains mounted but is no longer reachable through standard trading flows. Fully backward compatible — existing code continues to work. _(2026-07-08)_

---

# TO DO

Items are grouped into work-streams so related changes can be tackled together. Within each stream, sub-items are ordered by sequence (A1 before A2, etc.).

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
> The categorisation work (cluster exits by reason) is still open, and see the B2 note below on why
> the data will not mean anything until fills are live.

Observed 2026-05-07 — some SL exits realized at ~50% loss when the configured SL was tighter, while others felt premature. Traced two compounding causes:

- **Late exits:** SL signal evaluates against the option **bid** (`strategy_executor.py:382`); the exit then submits as a market sell (`order_manager.py:342`). On a fast SPY 0DTE drop, price keeps falling between trigger and fill, so realized loss exceeds the trigger %. Compounded by `_EVAL_INTERVAL = 1s` (`stream_driven_worker.py:40`) dropping ticks — by the next allowed eval the bid can already be several % past the threshold.
- **Early exits:** bid-based eval on a wide bid/ask fires SL at a worse-than-mid loss; trailing-stop snap on a transient bid spike (peak_price pinned high) and the account `trading_window_end` cutoff are also suspects.
- **Investigate first:** categorize today's SPY exits — `position.avg_entry_price`, `Trade.exit_price`, `position.peak_price`, exit `Signal.reason` (`strategy_executor.py:423-427`), wall-clock time. Cluster by reason to see how much is slippage vs. 1s-debounce vs. trailing-snap vs. window-cutoff before changing anything.
- **Add exit-drift logging while you're here:** mirror the entry-drift `ORDER_PREVIEW_DRIFT` event in `close_position` (pass `signal_price` from SL/TP signals). One-line change, feeds directly into B2's cancel-rule data. Held back from the original entry-drift change to keep scope tight; pick it up now.
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

### C1. Backtesting feature

We need to add a feature for backtesting data. What im thinking is what if we were able to use an available api call from tradier or a different broker to be able to help us collect data and test strategies. We could make it so when backtesting we can give params or constraints such as account size or other things to see how it might behave based on different things? Equity curves landed 2026-05-09 (DONE) — backtest results can now share the chart shape and overlay against live performance.

---

## D. ~~A standalone button so we can say hey we are finishing trading today~~ *(built 2026-08-31)*

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

## E. Exit rule structure *(from the 2026-09-02 live session)*

Full write-up: `docs/live-test-results-2026-09-02.md`.

### E1. The trailing stop is unreachable by construction *(structural bug)*

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

### E2. Settled cash is the binding constraint, and the flat target doubles its consumption

The 09-02 session generated **321 entry signals**, executed **3**, and produced **214 rejected
previews** (`Tradier preview rejected: You do not have enough buying power`). T+1 settlement on a
cash account: $1,060 settled at the open, $13.46 by 11:48 ET, proceeds unusable until the next day.

No GFV was incurred — every buy was funded from settled cash and the ledger reconciles to the
broker exactly (results doc §F3). But the ceiling is roughly **three trades per day**, and E1's
flat target spends two of them on one move.

**Two separate items follow:**

- **E2a. Stop previewing when out of buying power.** The engine should recognise it has no settled
  cash and stop issuing previews rather than being refused 214 times. *Affects log readability,
  broker request volume, rate-limit headroom — **no change to trading behaviour**, those orders
  were already refused.* Low risk, purely additive. Adjacent to A1, whose probe still has never
  run: today's protection came from Tradier's check, not ours.
- **E2b. Funding is a precondition for strategy measurement.** Three samples/day cannot support any
  read on win rate. Not a code change — a decision about whether the next test measures the
  strategy or measures the cash constraint again.

### E3. Do NOT retune the stop loss on 09-02 data

Trade 3 stopped at 2.50 (−15.5%); the contract recovered to 2.98 (high 3.13) by 12:00 and was back
to **2.50 by 13:00**. It reads as a shakeout at twelve minutes and as a correct exit at the hour.
One ambiguous trade. Listed explicitly so it is not quietly retuned.

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

# FUTURE CONSIDERATIONS

- **THERE ARE NO BROKER-SIDE STOPS. If the engine dies holding a position, nothing protects it.** Every exit — stop loss, take profit, trailing stop, time exit — is *simulated in-engine* and issued as a market sell when our own logic decides to fire (`order_manager.py:425`, market orders hardcoded). **Nothing rests at Tradier.** If the process crashes, the host reboots, the WebSocket wedges, or the eval loop stalls while a 0DTE position is open, that position simply sits there unmanaged until someone notices. The `stop_loss_pct` you configure is a number the engine checks — not an order the broker holds.
    - **This is the single largest live-trading risk in the system** and it is independent of every other item here. It survived the 2026-07-13 session only because nothing crashed.
    - **Tradier supports the fix.** It has OTO / OCO / OTOCO order classes, so an entry can carry an attached stop and target that live at the broker. `docs/tradier/trading/` documents them; **no code path calls them** — `place_option_order` hardcodes `class: "option"` (single-leg) and only ever sends market orders.
    - **The tension to resolve first:** broker-side brackets and engine-side trailing stops fight each other. A resting stop can't trail, and the engine can't trail a position the broker might close underneath it. Options: (a) resting *disaster* stop at the broker (wide — e.g. −50%), engine keeps managing the tight/trailing exits inside it; (b) full broker-side bracket, drop engine trailing entirely; (c) engine cancels/replaces the resting stop as it trails (most correct, most API traffic, most ways to desync). **(a) is the cheapest real safety win** — it bounds the catastrophic case without touching the strategy logic.
    - **Do this before any meaningful live capital.** Everything else on this list is money-losing-slowly; this one is money-gone-in-one-event.

- **Configurable server port + first-class multi-instance (per-environment) runs.** `api/app.py` hardcodes `uvicorn.run(..., port=8000)`, so a dev (`APP_ENV=dev`) and a live (`APP_ENV=prod`) instance can't run at the same time — they collide on port 8000. Make the port env-driven (`PORT`, default 8000) so both can run side by side (e.g. dev on 8000, live on 8001), each with its own engine worker / Tradier stream / email scheduler and each pinned to its launch `APP_ENV`. This is the safe model — trading is pinned to the process env, not the UI toggle (the toggle only reroutes *reads*; see JOURNAL.md 2026-07-10/11 and `docs/monday-runbook.md`). Follow-ups: the Angular `apiUrl` is fixed per build, so driving two backends means pointing the UI at the target instance's port (or running two UIs / adding an instance picker); optionally add a `scripts/` launcher ("start-dev", "start-live"). Low risk — two lines in `app.py`.

- **Daily-profit cutoff (positive-P&L halt for the day).** Mirror of the existing account-wide daily *loss* cap, but on the upside: once the day's P&L reaches +X%, pause **new entries** for the rest of the session so a green day can't be given back. Today the engine is one-directional — `RiskManager._check_user_daily_loss_limit` (`api/engine/risk_manager.py:221`) and the per-strategy `_check_daily_loss_limit` (`:305`) only gate `today_pnl < -limit`; the session-status helper even floors gains to zero (`loss_consumed = max(0.0, -today_pnl)`), so a positive day triggers nothing. `take_profit_pct` in `trading_safeguards.py` is a **per-position** option-price exit, not an account/day-level halt — unrelated.
    - **Exits stay sacred.** This gate blocks `side='buy'` only. Open positions keep running SL/TP/trailing — a profit halt must never force-close, or it converts paper gains into realized ones and kills the trailing stops (per the engine rules in CLAUDE.md).
    - **Sketch:** add `_check_user_daily_profit_target` alongside `_check_user_daily_loss_limit`, computing the same realized + unrealized `today_pnl`, rejecting buys when `today_pnl > +limit`. Wire into `check_entry` right after the loss gates (most-restrictive-bound composes cleanly — it's an additional entry block, never a widening). Add a `_log_account_risk_event(... "user_daily_profit_target" ...)` and optionally a `PROFIT_HALTED` status in the session-status block (~risk_manager.py:453–482) so the overview tile can surface it.
    - **Config surface:** parallel `daily_loss_limit_pct` — new `User.daily_profit_limit_pct` column (`models.py:28`) + Alembic migration + `schemas.py` fields (`:76`, `:103`), and/or a `strategy.params_json['daily_profit_limit_pct']` key. Account-level, per-strategy, or both — TBD.
    - **Open design question (decide before building):** measure the threshold against **account equity** (e.g. +3% of account) or against the **day's risked/deployed capital** (e.g. +50% of what was put at risk today)? They behave very differently on a small-position day. Also decide: does hitting the target also imply we're "done for the day" (ties into idea **D**, the standalone "finish trading today" button)?

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

- **A re-entry cooldown after a stop-out.** Not a data question — a design one. Re-entering 30 seconds after being stopped out is a bet that the thing which just went against you will now go for you. Combined with the 38-second median cadence and a rate limiter that is already rejecting 46% of attempts, the engine is trading as fast as it is permitted to rather than as fast as it has edge for.

- **`TradierClient` has no 429 / rate-limit handling.** `_RETRY_STATUSES = {502, 503, 504}` only (`client.py:24`); the `Retry-After` and `X-Ratelimit-*` headers Tradier sends are ignored entirely. POST is deliberately never retried (correct — avoids double-submits), but a 429 on a GET currently just raises. Not urgent at ~19 trade cycles/day; becomes real the moment order frequency or strategy count rises.
    - **Three modules bypass the client with raw `requests` and inline API keys**, so they'd miss any retry/limit logic added there: `strategy_executor._fetch_option_price` (`:555-591`, plus dead `live_url` at `:563`) and `utils/market_hours.py:138`. Route them through `TradierClient` when touching either.

- **`api/engine/trading_safeguards.py` is dead code — decide whether to wire it up or delete it.** `PaperTradingSafeguards.validate_strategy_params` is never called by anything (the similarly-named `RiskManager.check_live_trading_safeguards` at `risk_manager.py:487` is a different function). It checks position sizing, that a stop loss exists and is ≥ 10%, that take-profit is < 100%, and warns when there is no time-based exit — all things we *want* enforced, and none of which are.
    - **If wiring it up:** it rejects any strategy whose `stop_loss_pct` is absent or < 10. Both current strategies now set it (15), so they pass — but confirm before enabling, or strategy creation starts failing.
    - **It would have caught the 2026-07-13 config.** Not the inverted risk/reward (it doesn't compare SL to TP — worth adding: reject `stop_loss >= take_profit`, the exact flaw that guaranteed the loss), but it *is* the natural home for that check. See `docs/negative-expectancy.md`.

- **`scripts/update_account_size.py` is broken and untracked.** It writes `User.account_size` — **that column does not exist** on the model. Either add the column or delete the script; right now it will `AttributeError` on the first run. Same review needed for `scripts/test_user_update.py` (untracked, unread).

- **News-outlook column on the strategies table.** Per-strategy "today's news outlook" chip combining news sentiment for the strategy's symbol(s) with the strategy's direction (long-call/long-stock strategies use raw sign; long-put/short-call invert). Pure observation column — no signal consumption, no auto-disable. Same data-first pattern as B2 (entry-drift) and A1 (GFV reservations): would collect "outlook said X / strategy did Y" pairs before deciding whether news ever feeds a real gate. Promote to the numbered list once a provider is picked and the direction-mapping question below is answered.
    - **News source — pick before building:** Tradier does not return narrative news, need an external provider. Candidates: Benzinga (paid, sentiment included), Polygon (cheap, sentiment on Stocks Starter), Finnhub (free tier with sentiment), Marketaux (cheap). Lean toward starting on a free tier — observation-only column is hard to justify paid spend on until correlation with PnL is shown.
    - **Strategy-direction mapping is the real design problem.** Raw symbol sentiment isn't useful — a long-put on bearish news is a *good* outlook, not bad. Either infer direction from `strategy_type` / `params_json` legs, or add an explicit `bias: 'long' | 'short' | 'neutral'` field on the strategy. Decide this before any UI work, otherwise the chip lies.
    - **Outlook computation:** average today's per-article sentiment for each symbol in the strategy's symbol list, then orient against strategy direction. Multi-symbol strategies show worst-case symbol so the chip is conservative. Bucket into Good / Neutral / Bad with a dead band so neutral noise doesn't flicker.
    - **Backend sketch:** new `GET /strategies/news-outlook` returning `[{strategy_id, outlook, score, top_headlines: [{title, url, ts}]}]`. Cache per (symbol, ET-date) so reload doesn't re-bill the news API; in-process refresh every ~15 min during market hours.
    - **UI sketch:** new "Outlook" column rendered as a colored chip themed via existing `--color-profit` / `--color-warning` / `--color-loss` tokens (no new palette work). Tooltip = top 2–3 headlines; click → drawer with all of today's articles + per-article sentiment so the chip is auditable.
    - **Open questions:** does "today" mean ET-calendar-day or last-24h-rolling? Should pre-market news flip the outlook before open, or only RTH?

---

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

## H. Recovery-path hardening (from the 2026-08-26 put-support guard passes)

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

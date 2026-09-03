# Sandbox Shakedown — Tue 2026-09-01

Dry run before the live test on **Wed 2026-09-02**. Sandbox, paper mode, no real money.

**Purpose:** prove the mechanics of three engine changes that have never run anywhere, and confirm
the instrumentation fires. **Not** to measure P&L, win rate, drift magnitude or anything else —
sandbox fills are fabricated and every metric derived from them is meaningless (JOURNAL 2026-07-14).

What sandbox legitimately tests: order placement, fill confirmation, reconciliation, the streams,
contract selection, the risk gates, and not crashing. That is exactly this list.

## What we are shaking down

| Change | Landed | Ever run? |
|---|---|---|
| Stale-quote guard on the **exit** path | 2026-08-27 | no — written after the session |
| "Done for the day" halt (`ride` / `flatten`) | 2026-08-31 | no |
| Stale-quote guard on the **entry** path | 2026-08-31 | no |

The entry guard is the one to watch. It can now **skip** an entry tick when the streamed quote is
stale and REST returns nothing. If that path is wrong, the failure mode is silent: no entries, no
error.

---

## Setup

The engine normally runs already. Restart it with logging on so the JSONL hooks fire:

```bash
# stop whatever is running (pgrep -f app.py), then:
LIVE_TEST_LOGGING=1 venv/bin/python api/app.py
```

No `APP_ENV` → dev DB + sandbox broker. Confirm on startup that the log line reports the **dev**
database. Strategies 3 (calls) and 4 (puts) are already active on dev.

Optional second terminal:

```bash
cd api && ../venv/bin/python -m live_test.monitor --env dev --interval 60
```

Logs land in `logs/livetest-2026-09-01/`.

---

## Checks

### 1. Entries still fire  ← the important one

The entry guard's failure mode is silence, so absence of entries is the thing to look for.

- [ ] At least one entry places during the session.
- [ ] `grep 'ENTRY SIGNAL' logs/livetest-2026-09-01/engine-*.log` — the line now carries
      `quote_age=Ns`. Sanity-check those ages are small (single-digit seconds) most of the time.
- [ ] `grep 'Stale stream quote.*at entry' engine-*.log` — count them. **This is the number that
      tells us whether the entry path was ever actually broken in live conditions.** Zero means
      streamed quotes stay fresh at entry and the guard is belt-and-braces. Many means it was
      sizing off frozen prices all along.
- [ ] No burst of `No option price available, skipping entry` — a few is fine, a wall of them means
      the REST fallback is failing and the guard is starving the entry path.

### 2. Contract arming works at all

`min_open_interest: 3000` vs the 0.60–0.85 delta band is structurally tight (TODO §2, 08-27).
If nothing arms, Wednesday produces no trades regardless of anything else.

- [ ] A contract arms. `grep -i 'arm\|selected contract' engine-*.log`
- [ ] Note the strikes and their OI — if it only just clears 3000, Wednesday is a coin flip.

### 3. Exit-drift events now emit on sells

- [ ] After a round trip, query for `side='sell'` drift rows:
      `select event_data->>'side', count(*) from system_events where event_type='ORDER_PREVIEW_DRIFT' and created_at::date='2026-09-01' group by 1;`
- [ ] **Read `event_data->>'order_cost_raw'` on a sell.** Its sign is undocumented
      (`docs/tradier/trading/preview_order.md` shows only a buy). Record whether it comes back
      positive or negative — until that is known, no exit-drift number means anything.

### 4. The halt works, both modes

Do this near the end of the session, with a position open.

- [ ] `ride` — click Done for the day. New entries stop; the open position keeps running and still
      exits on its own stop/target/EOD. **Nothing should be sold at the moment of clicking.**
- [ ] Resume, confirm entries come back.
- [ ] `flatten` — with a position open, click and choose sell-all. The position closes at market on
      the next eval tick, with exit reason `Trading stopped for the day...`.
- [ ] Confirm the halt auto-clears: it is stamped with the ET date, so it should be gone by
      Wednesday morning without anyone clearing it.

### 5. Exit pricing does not fire on stale quotes

- [ ] `grep 'Stale stream quote' engine-*.log` for the **exit**-path wording ("pricing exit from
      REST"). Any hits are the 08-27 fix doing its job.
- [ ] Exits do not all cluster at absurd claimed percentages. Sandbox realized numbers are fake, so
      only the *claimed* side is worth reading here.

### 6. Nothing crashed

- [ ] `grep -iE 'traceback|ERROR' engine-*.log | head -40` — read them, don't just count.
- [ ] Engine still alive at the close; no auto-stop from the 20-consecutive-error rule.

---

## Wednesday prep (do it once today's checks are green)

- [ ] **Set `risk_per_trade_pct` on PROD strategy 3.** At `1.5` a $1,000 account sizes **zero
      contracts at every price** and the day produces nothing. 40% caps deployment at $200/trade
      (20% of account); 30% caps it at $150 but skips contracts over $1.50. Decide and set.
- [ ] Leave `daily_loss_limit_pct: 10%` ($100) alone — it allows roughly 15–25 round trips before
      halting, which is the sample size the exit-pricing question needs, with a real stop under it.
- [ ] Load the dashboard in prod so `account_size_usd` syncs from the broker (still reads `70`).
- [ ] Keep strategy 3 **inactive** until the moment the session starts.
- [ ] Launch Wednesday with `APP_ENV=prod LIVE_TEST_LOGGING=1` — the engine follows `APP_ENV`, not
      the UI toggle. The UI toggle only reroutes *reads*.

## Wednesday's actual question

Only one: **does a claimed exit percentage match the realized one?** A take-profit claiming +36.96%
that realizes −2.1% is the failure this whole chain of fixes has been chasing, and it is the one
thing sandbox structurally cannot answer.

Everything else — B1 exit-drift analysis, B2's cancel threshold, expectancy, win rate, the 15/30
stop-target ratio — is downstream of having a single day of honest fills.

## Known limits, so nothing here is over-read

- Sandbox fills are fabricated; `avg_fill_price` comes back null, so `filled_price` falls back to
  the estimate. Expected, not a bug.
- **There are still no broker-side stops.** If the process dies holding a position, nothing protects
  it. The flatten button is a manual kill switch and only works while the engine is alive. At 1–2
  contracts on Wednesday that exposure is ~$150–300, which is what makes going live acceptable
  without the resting stop — not the absence of the risk.

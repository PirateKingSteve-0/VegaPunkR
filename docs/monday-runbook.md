# Monday Live Test — Runbook (2026-07-13)

Living doc — edit freely. Goal: one controlled live SPY round-trip (tiny size, heavy logging) to
settle which P&L number is real and prove the order→fill→ledger path works live.

---

## The two processes (this answers "do I run app.py and Claude monitors?")

**YES.** Two separate things:

1. **`app.py` — the trading app (YOU run it).** API + engine + market stream. Nothing evaluates or
   trades unless this is running. It runs in the foreground in a terminal on your machine.
2. **The monitor — read-only watcher (Claude runs it, or you).** A separate process that polls
   broker-vs-local every 60s and flags anomalies (position mismatch, missing fill price, drift).
   **It never places or cancels orders.** It just observes what `app.py` does.

They're independent. You start the app; the monitor (and the log files the app writes) let Claude
watch in real time.

---

## Commands cheat-sheet

```bash
# --- Weekend sandbox dry-run (safe, no real money) ---
LIVE_TEST_LOGGING=1 venv/bin/python api/app.py

# --- MONDAY live test app (real money) ---
APP_ENV=prod LIVE_TEST_LOGGING=1 venv/bin/python api/app.py

# --- Monitor (separate terminal; run from the api/ dir) ---
cd api && ../venv/bin/python -m live_test.monitor --env prod --interval 60
#   sandbox dry-run monitor:  ../venv/bin/python -m live_test.monitor --env dev
```

Logs are written to `logs/livetest-<ET-date>/`:
`broker_http-*.jsonl` (raw calls), `orders-*.jsonl` (fills — the gold), `stream-*.jsonl` (ticks),
`reconcile-*.jsonl` (monitor), `engine-*.log` (human-readable).

---

## Pre-market checklist (before 09:30 ET)

- [ ] **Account funded and cash SETTLED** (cash account — unsettled cash can't buy; check in Tradier).
- [ ] Start the app pinned to prod + logging:
      `APP_ENV=prod LIVE_TEST_LOGGING=1 venv/bin/python api/app.py`
- [ ] Confirm the startup log shows: `Process DB environment: APP_ENV=prod → prod` and
      `LIVE_TEST_LOGGING on`.
- [ ] Log into the UI. Switch trading mode to **LIVE** (this also moves you to prod).
- [ ] **Load the dashboard** so `account_size_usd` syncs to the real funded balance
      (otherwise the daily-loss cap is computed off the $70 placeholder).
- [ ] Strategies page shows **only the SPY strategy** (prod) — and it's **INACTIVE**.
- [ ] Safety: `max_positions = 1`, a tight daily-loss cap, a narrow trading window.
- [ ] Start the monitor (Claude runs it, or you): `../venv/bin/python -m live_test.monitor --env prod`.

---

## Sandbox smoke-test FIRST (at the open, before going live)

The real end-to-end dry-run (engine places an order → fill polled → recorded → logged) can't run
when the market is closed, so do it Monday at the open in **sandbox** before flipping to live:

- [ ] Start the app in sandbox with logging: `LIVE_TEST_LOGGING=1 venv/bin/python api/app.py`
      (no `APP_ENV` = dev/sandbox).
- [ ] Activate a **sandbox** SPY strategy; let it do **one** round-trip.
- [ ] Confirm `logs/livetest-<date>/orders-*.jsonl` shows a `filled` record produced by the engine
      (the full path fired: place → poll → fill → Trade). In sandbox `broker_avg_fill_price` will be
      null and `filled_price` falls back to the estimate — expected; we're validating the *plumbing*.
- [ ] Deactivate, stop the app.
- [ ] Only then proceed to the live launch below.

## During the session (LIVE)

- [ ] Wait for the window to open (≈10:00 ET, past the opening noise).
- [ ] **Activate the SPY strategy.**
- [ ] **After the FIRST fill, STOP and check** `logs/livetest-<date>/orders-*.jsonl`:
      is `broker_avg_fill_price` populated (a real number, not null)?
      - ✅ real fill → continue.
      - ❌ null/estimate → deactivate and diagnose before any more real orders.
- [ ] Let it run a few round-trips (**cap ~5–10**), watching the monitor for 🚩 flags
      (position-count mismatch = possible stacking; realized drift).
- [ ] **Deactivate the strategy** when done.

---

## Post-close (after 16:00 ET)

- [ ] Claude runs the 4-way reconcile: local ledger vs `close_pl` vs `gainloss` vs order
      `avg_fill_price` → conclude which source is truth.
- [ ] **Tuesday AM:** re-pull `gainloss` (it's a nightly batch) and compare again.
- [ ] **Revert the daily-loss cap** on the prod user from 10% back to ~5% (10% was a one-off
      test setting for headroom — not a steady-state cap).

---

## 🛑 Kill switch (if anything looks wrong)

1. **Deactivate the strategy** in the UI → stops new entries immediately (exits still allowed).
2. **Ctrl-C the `app.py` terminal** → stops the engine entirely.
3. If a position is open and must be closed: **close it manually in the Tradier dashboard**.

---

## What Claude watches in real time

- Monitor output (broker vs local, every 60s) + `reconcile-*.jsonl`.
- `orders-*.jsonl` (each fill: estimate vs real `avg_fill_price`).
- `broker_http-*.jsonl` if anything needs forensics.
- Reports anomalies as they happen.

---

## Notes / open items (edit as we go)

- Restart the app to load all the changes made 2026-07-10/11 before any test.
- Lower-priority still-sandbox: the reconcile service + email reports (not in the live order path).
- Reconcile→price/pnl auto-repair: deferred until after we see live data on Monday.
- Sandbox leaves `avg_fill_price` null, so the dry-run proves the *plumbing*, not fill values —
  real fills only show up live.

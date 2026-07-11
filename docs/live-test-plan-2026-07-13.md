# Live Trading Test Plan — Monday 2026-07-13

Status: DRAFT for review. Today = Fri 2026-07-10. Test day = **Mon 2026-07-13** (US market: 09:30–16:00 ET).
Goal in one line: **use one real live session, with tiny size and heavy logging, to settle which P&L number is real and to prove the order→fill→ledger path works in live.**

---

## 0. HEADLINE FINDING — a prerequisite fix before ANY live order

`api/engine/order_manager.py:716-718`:
```python
trading_mode = user.selected_trading_mode or "paper"
if trading_mode != "paper":
    return None            # live/schwab: no terminal polling
```
In **live mode**, `_await_terminal_order` returns `None`, so `execute_signal` (`:544-562`) treats **every live order as `ORDER_UNCONFIRMED`**:
- It never reaches the fill-recording code (`:605-655`) → **no real fill price captured, no Trade row, no local Position update.**
- It relies on the 60s `_reconcile_position` tick to notice the broker holding.

Two consequences that make live UNSAFE as-is:
1. **The test's whole purpose (capture the real `avg_fill_price`) can't happen** — we never poll for the fill.
2. **Order-stacking risk:** for up to 60s the engine believes it's flat (no local Position) while actually holding a live position. Ticks eval every 1s → it can fire **another real entry** before the reconcile catches up. Real money, duplicated.

**REQUIRED PREP (engine change — needs explicit sign-off):** enable live fill-confirmation. `_await_terminal_order` already polls Tradier `get_order` correctly; the fix is to let it run in live (Tradier live populates `avg_fill_price`/`exec_quantity` on a filled order). Mirror the same change in `close_position` (`:1207`). Test thoroughly in sandbox first; confirm the entry-lockout still holds and no double-fire. **This fix is also what solves the fill-capture problem we've been chasing.**

---

## 1. The question live must answer

Sandbox gave three contradictory numbers for a day (local ledger −$72, `close_pl` −$72, `gainloss` +$1,531) and no way to break the tie (`history` is empty in sandbox). Live should reconcile. For the test day we produce a per-lot + aggregate comparison of:

| Source | What it is | When available |
|---|---|---|
| `order.avg_fill_price` (via `get_order`) | the actual execution price, per order | at fill time |
| local `Trade.pnl` | our ledger, now built from real fills | at fill time |
| `history` per-fill `price` | broker's per-fill record | intraday/post (live only) |
| `balances.close_pl` | broker realized, current day | intraday (live) |
| `gainloss` | broker realized, **nightly batch**, filter by `close_date` | next morning |

**Conclusion we want:** which of these agree, and therefore what the dashboard tile + the reconcile service should source from.

> Note on the websocket: the stream is **market data only** (`wss://ws.tradier.com/v1/markets/events`, subscribes `["trade","quote"]`). **It carries NO order/fill/account events.** Fills are learned only via REST `get_order`. So "what the stream captures" = quotes and underlying trade prints, not fills — set expectations accordingly.

---

## 2. Instrumentation — what to log and where

Today there is **no file logging at all** — only `logging.basicConfig(INFO)` to stdout (`api/app.py:7-10`). For the test we add a dedicated, date-stamped, file-based setup. Keep it behind a `LIVE_TEST_LOGGING=1` env flag so it's off by default.

### Log files (dir: `logs/livetest-2026-07-13/`, each line ISO-8601 UTC + ET, correlation id where relevant)

| File | Source hook (file:line) | Contents | Volume |
|---|---|---|---|
| `engine-<ts>.log` | root logger file handler (add in `app.py`) | human-readable app log (all modules) | med |
| `broker-http-<ts>.jsonl` | `client._request_with_retry:79` / `_post:124` | **every raw Tradier request** (method, url, params, body) **+ response** (status, body, latency_ms) | high |
| `orders-<ts>.jsonl` | `order_manager.execute_signal` + `close_position` | per-order lifecycle keyed by `order_id`: preview req/resp, place req/resp, each `get_order` poll, `avg_fill_price` vs `estimated_price`, Trade row written, Position before/after | low (gold) |
| `stream-<ts>.jsonl` | `tradier_stream_manager.py:94` (`json.loads(line)`) | **raw WS payloads.** Keep ALL `trade` events for our symbols; **sample** `quote` events (high volume) e.g. 1/sec/symbol. Also log the currently-swallowed `JSONDecodeError` (`:96`) and `QueueFull` drops (`stream_router.py:73`) | high |
| `reconcile-<ts>.jsonl` | monitor script + `_reconcile_position` (`:524/:571`) | periodic snapshots (balances close_pl/open_pl/equity, positions, open orders, local ledger) + broker-vs-DB drift + the final 4-way comparison | low |

### Naming / IDs
- `logs/livetest-2026-07-13/<concern>-<YYYYMMDD-HHMMSS>.jsonl`.
- Every record: `{ "ts_utc", "ts_et", "concern", "order_id"?, "symbol"?, ... }`.
- **Separate by concern** (different volumes and audiences). The two you'll actually read are `orders-*.jsonl` and `reconcile-*.jsonl`; cross-reference them by `order_id` + timestamp. `broker-http-*.jsonl` is the full audit trail if anything looks wrong. `stream-*.jsonl` is for tick/timing forensics only.

### Blind spots to fix while instrumenting
- Swallowed WS decode errors — `tradier_stream_manager.py:96-97`.
- Dropped ticks on `QueueFull` — `stream_router.py:73-74` (count them).
- Live had no terminal polling — covered by §0.

---

## 3. Monitor tooling (how I help watch it live)

New read-only script `api/debug/livetest_monitor.py` (scaffold off `debug/probe_buy_reservations.py`):
- Every 60s: pull `get_balances` (close_pl/open_pl/equity), `get_positions`, `get_orders`; read local ledger (today's `Trade.pnl`, open `Position` rows).
- Print a live diff table (broker vs local) + append to `reconcile-*.jsonl`.
- Flag anomalies: broker holds something local doesn't (or vice versa), duplicate positions (stacking), `avg_fill_price` missing on a filled order, ledger vs `close_pl` divergence.

**Monitoring options for Monday:**
- **(a)** I run this in the background from here (read-only) if live Tradier creds + `DATABASE_PROD_URL` are reachable in this environment, and report anomalies as they happen.
- **(b)** You run it and paste output, or we tail the log together.
Decide which; (a) needs the live token available to my shell.

---

## 4. Safety rails (REAL MONEY — cash account, GFV is the real constraint)

- **One** strategy, **one** symbol, **1 contract**, a low-priced option.
- `max_positions = 1`. Narrow `trading_window` (e.g. 10:00–10:30 ET) to bound the test.
- Set account `daily_loss_limit_pct` to a small dollar cap so the loss-halt is a real backstop.
- **Hard trade-count cap:** stop after ~5–10 deliberate round-trips. Do NOT run the 300-trade scalper.
- **Kill switch (document exact steps):** deactivate the strategy → stop the worker → flatten manually via broker if needed.
- **Settlement/GFV:** cash account, no margin. Selling then rebuying the same lot with unsettled proceeds risks a Good-Faith Violation (3 in 12 mo → 90-day settled-cash restriction). Keep enough **settled** cash for the handful of trades; prefer spacing round-trips.
- Confirm `account_size_usd` is real (the account endpoint syncs it).

---

## 5. Timeline

**Sat–Sun (build + dry-run, all in sandbox):**
1. §0 live fill-confirmation fix (sign-off) → verify in sandbox: fills confirm, lockout holds, no double-fire.
2. §2 logging instrumentation behind `LIVE_TEST_LOGGING` → verify all 5 files write, JSONL parses, timestamps correct.
3. §3 monitor script → verify diff output in sandbox.
4. §4 safety config staged (small size, caps, window, kill-switch rehearsed).
5. Sun night: freeze code, final review.

**Mon pre-market (by ~09:00 ET / 06:00 PT):**
- Switch to **live + prod** (confirm the paper→live+prod switch does what's expected).
- Verify `logs/livetest-2026-07-13/` is writable and files open.
- Verify tiny size + caps + window + one strategy/one symbol + settled cash.
- Start the monitor.

**Session:**
- Let the window open (~10:00 ET, past open noise). Allow a handful of controlled round-trips.
- After the first 1–2 fills: **pause and eyeball `orders-*.jsonl`** — is `avg_fill_price` populated and non-estimated? If NO, stop and diagnose before more real orders.
- Continue to the trade-count cap, then disable the strategy.

**Post-close (after 16:00 ET):**
- Run `tradier_reconcile` (now extended to price/pnl if we build that) + pull `close_pl`, `history`, `gainloss`.
- Produce the §1 four-way comparison table.

**Tue morning:** re-pull `gainloss` (nightly batch settled) and re-compare — confirms whether the nightly number matches intraday `close_pl` + our ledger.

---

## 6. Success criteria

- Live orders **confirm with a real `avg_fill_price`** (not the estimate).
- **No order stacking**, no duplicate entries; entry-lockout holds in live.
- Local ledger, `close_pl`, and (Tue) `gainloss` **reconcile within tolerance** — or, if they don't, we have the full request/response trail to see exactly why.
- Logs are complete, timestamped, and cleanly analyzable.

---

## 7. Open decisions before Monday

1. **Approve the §0 engine fix** (live fill-confirmation)? It's required for a meaningful/safe test.
2. **Monitoring mode:** I run the read-only monitor from here (needs live creds in my env) vs. you run it.
3. **Which strategy/symbol/size** for the test.
4. **Do we also build the reconcile→price/pnl extension** before Monday, or just capture raw data Monday and reconcile after?
5. Trade-count cap and trading-window for the test.

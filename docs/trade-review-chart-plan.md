# Trade Review Chart — plan

Written 2026-09-23. Replaces the position chart dialog for option trades with a four-panel trade
review built on our own recorded quotes. **No engine changes anywhere in this plan.**

---

## 1. The problem

Clicking a position on the Performance or Positions page opens
`ui/src/app/pages/positions/position-chart-dialog/position-chart-dialog.component.ts` (605 lines,
lightweight-charts candlesticks, data fetched live from Tradier). For a 0DTE option trade it is
unreadable, for three separate reasons:

1. **Tradier has no intraday data for an option contract.** `docs/tradier/market/historical_pricing_security.md`:
   `/markets/history` accepts an OCC symbol but serves `daily` / `weekly` / `monthly` bars only, and
   `/markets/timesales` does not accept option symbols at all (the component disables those ranges
   and says so in a tooltip). A 0DTE contract's entire life is **one daily candle**.
2. **Underlying mode hides the trade.** It charts the stock correctly, then calls `fitContent()`,
   which fits the whole session — 390 one-minute bars. Our trades last 1–30 minutes, so the trade is
   2–3 bars wide in a 390-bar view.
3. **The markers contradict the axis.** In underlying mode the entry marker still reads
   `Entry @ $3.66` (the option price) against a price scale showing ~$770 (the stock).

### Why a different chart library does not fix it

- **lightweight-charts is already TradingView's library** — the same renderer, without the drawing
  tools and indicator menu.
- **TradingView Advanced Charts** is free for non-commercial use but requires an access request plus
  a datafeed adapter we would write. It would draw the same missing data.
- **TradingView embed widgets** render TradingView's own data; our entries cannot be overlaid.

The constraint is the data, not the renderer. Sites that show intraday option charts (Yahoo,
thinkorswim) buy the options tape (OPRA). Our broker API does not expose it.

### What we already have that is better

With `--log` on, the engine records the armed contract's **every quote tick** to
`logs/livetest-<ET-date>/stream-*.jsonl`. That is the exact bid/ask stream the exit logic acted on,
at ~1 second resolution — finer than any vendor chart, and aligned to our own decisions to the
second. Every session from 2026-09-02 to today has one.

---

## 2. Data inventory

### Recorded (files)

| Source | Shape | Use |
|---|---|---|
| `logs/livetest-*/stream-*.jsonl` | `{ts_et, kind:"quote", event:{symbol, bid, ask, …}}`, also `trade` events carrying `cvol` (cumulative volume) | contract price path; underlying path; volume |
| `logs/livetest-*/engine-*.log` | `ENTRY SIGNAL: … reason=Entry conditions met (call): ema, vwap, volume_ratio, delta, open_interest, bid_ask_spread`, `EXIT SIGNAL: … reason=…`, `Greeks REFRESHED … delta X` | which gates passed; exit reason; broker delta |
| `logs/livetest-*/orders-*.jsonl` | fill events | fill price cross-check (**buys only** — sells are not written; separate defect, see §7) |
| `logs/livetest-*/exit_shadow-*.jsonl` | one record per close, six alternative exit rules | "what other exits would have done" panel (later) |

### Database (prod)

| Table | Fields that matter |
|---|---|
| `trades` | `id, side, qty, price, exit_price, pnl, timestamp, exit_timestamp, mfe_price, mae_price, strategy_id, position_id` — all 80 rows have `position_id`, no dangling references |
| `positions` | `option_symbol` (the OCC contract), `avg_entry_price`, `opened_at`, `peak_price`, `trough_price` |
| `strategies` | `params_json` → `stop_loss_pct`, `take_profit_pct`, `trailing_stop_activation`, `trailing_stop_distance` — needed to draw the exit levels |
| `system_events` | `POSITION_OPENED` / `POSITION_CLOSED` with `{qty, price, exit_price, pnl, order_id}` |

### Not stored anywhere

**The indicator values at entry.** The engine logs *which* gates passed, never their values — no
stretch, no volume ratio, no VWAP. Two options, and the plan takes the second:

- log them at entry → an engine change, rejected for this work;
- **recompute them offline** from the recorded ticks, using the same construction as
  `scripts/measure_engine_wiggle.py` / `distance_test.py`. Recomputation is the house rule
  (`feedback_recompute_dont_reread`) and it costs the engine nothing.

Recomputed values are labelled as such in the UI, because the tick-accumulated `engine_wiggle` and an
offline `session_wiggle` differ by ~4% (measured; `replay_session.py` docstring).

---

## 3. The view

```
 ┌─ contract: SPY260923P00772000 ───────────┬─ underlying: SPY, 1-min ─────────────┐
 │  per-second bid, our own recording       │  candles + VWAP                       │
 │  ▲ entry 2.51   ▼ exit 3.02              │  ▲ entry   ▼ exit                     │
 │  ─ ─ stop 2.13   ─ ─ target 3.14         │  shaded hold band                     │
 │  ·  peak 3.37  ·  trough 2.22            │                                       │
 ├─ what the engine saw ────────────────────┼─ trade facts ─────────────────────────┤
 │  gates passed: ema, vwap, volume_ratio,  │  +$51.00 · 1 contract · held 30m      │
 │  delta, open_interest, bid_ask_spread    │  exit: trailing stop                  │
 │  stretch 0.62 wiggles (recomputed)       │  best 3.37 (+34%) · worst 2.22 (−12%) │
 │  volume ratio 1.8x (recomputed)          │  entry 11:13:02 ET · exit 11:43:28 ET │
 │  broker delta 0.77 (age 14 min)          │  strategy 4 · SPY 0DTE Momentum (Puts)│
 └──────────────────────────────────────────┴───────────────────────────────────────┘
```

- **Shared time axis and linked crosshair** between the two price panels (lightweight-charts
  `subscribeVisibleLogicalRangeChange` + `subscribeCrosshairMove`), so hovering 11:23 on the contract
  highlights 11:23 on SPY. This is the call/put correlation view: a $0.60 move in SPY against a 20%
  move in the option.
- **Zoomed to the trade** by default — entry −20 min to exit +20 min — with a control to widen to the
  full session. Never `fitContent()` on a whole day again.
- Stacks to one column under ~900px (the dialog is used on a phone over the LAN).
- Panels are independent: any panel with no data renders an empty state, never a broken chart.
- **Opens as a dialog, with an expand control** that takes it to the full window (and back). Decided
  2026-09-23: dialog first, because that is how the chart is reached today from both Positions and
  Performance; the expand is for actually studying a trade.

### Open positions — the chart must work before the trade is closed

A replay file only exists for a trade that has closed, but a position being *watched* is exactly when
a chart matters. Three sources, in priority order, all feeding the same two panes:

1. **Live ticks.** `ui/src/app/services/market-stream.service.ts` already streams arbitrary symbols
   from `/tradier/stream/events` (SSE) — the same feed `stream-drawer.component.ts` uses. Subscribe
   to the position's `option_symbol` and append ticks as they arrive. This is the only source that is
   current to the second, and it needs no new backend.
2. **Today so far.** The replay builder run against an *open* trade produces a partial path from the
   session log up to now, so opening the dialog mid-trade shows the history before you opened it
   rather than starting blank. Same endpoint, `partial: true` in the response.
3. **The completed replay.** Once the position closes, a rebuild replaces the partial file and the
   exit marker, exit reason and final numbers appear.

So: open position → live ticks (+ partial history if the builder has been run today); closed
position → the full recorded path. The panel labels which source it is showing.

---

## 4. Architecture

```
  logs/livetest-*/            (unchanged, written by the engine)
        │
        │  scripts/build_trade_replays.py      ← new, read-only, offline
        ▼
  data/trade_replays/<trade_id>.json           ← new (note: `data/` is untracked but NOT in .gitignore — see §8)
        │
        │  GET /api/v1/trades/{id}/replay      ← new endpoint, own-data-only
        ▼
  ui  TradeReplayService → TradeReviewDialogComponent (4 panels)
```

**Why files rather than a new table.** A new model means a migration on DEV *and* PROD before the
model is edited (`feedback_migrate_before_model_edit`), and `reload=True` means a stray model save
hits the live shared database. A JSON file per trade needs none of that, is trivially re-buildable,
and `data/` is already untracked. If this proves useful, promoting it to a table is a later,
separate decision.

**Size.** A 30-minute trade holds ~1,000–1,800 recorded quotes, ~40 KB of JSON. All 26 positions to
date ≈ 1 MB. No pagination needed; the endpoint returns one trade's file.

**Freshness.** The script is idempotent and re-runnable: `--since 2026-09-01`, or `--trade 79`. Run
**by hand** after a session (owner's call, 2026-09-23) — logs are the source of truth and a rebuild
is safe, so a cron job can be added later if running it by hand gets annoying.

### The endpoint

```
GET /api/v1/trades/{trade_id}/replay
  → 200 { contract: {symbol, points:[{t, bid, ask}], levels:{stop, target, trail_arm, trail_from_peak}},
          underlying: {symbol, bars:[{t,o,h,l,c,v}], vwap:[{t,v}]},
          entry: {t, price, qty, gates:[…], stretch, volume_ratio, delta, delta_age_s, recomputed:true},
          exit:  {t, price, reason},
          facts: {pnl, hold_s, mfe_price, mae_price, strategy_id, strategy_name}
        }
  → 404 when no recording exists for that session (pre-2026-09-02, or logging was off)
```

RBAC: `Depends(get_current_user)` and filtered to the caller's own trades, same as
`GET /trades/{id}`. Read-only, no write path, no admin cross-user reads (`?user_id=` impersonation is
deliberately absent repo-wide).

---

## 5. Phases

| # | Work | Output | Risk |
|---|---|---|---|
| 1 | `scripts/build_trade_replays.py` — walk logs, join to `trades`/`positions`, write per-trade JSON | all 40 closed round trips replayable offline | none; read-only script |
| 2 | `GET /trades/{id}/replay` + response schema + a test | API serves one trade | low; new read-only endpoint |
| 3 | Two linked price panels, zoomed to the trade | **the readability fix** | low; UI only |
| 4 | Engine-context and trade-facts panels | the full quadrant | low; layout over data already in place |
| 5 | *(optional)* shadow-exit overlay: where the six alternative rules would have sold | feeds TODO E14 | low |

Phases 1–3 are the substance. Phase 4 is mostly layout once phase 1 has the numbers.

**Acceptance for phase 3:** open today's 772 put (trade 79/80) and see the option rise 2.51 → 3.37 →
3.02 against SPY falling over the same 30 minutes, with the stop line at 2.13 never touched and the
trail firing 10% under the peak.

---

## 6. Non-goals

- **No engine changes.** Not the entry path, not the exit path, not the post-fill path. If the price
  path is ever written live by the engine instead of rebuilt from logs, that is a separate proposal
  with an engine review.
- **No new data vendor.** OPRA intraday history is not being bought to make this work.
- **Not a backtester.** This shows one trade that happened. TODO C1 covers backtesting.
- **No changes to the existing dialog for stock positions** — it works there; the new view is used
  when the position is an option contract and a recording exists, with the old dialog as fallback.

## 7. Known gaps this work will surface

- **`orders-*.jsonl` records buys only** — no sell has been logged there on any session since at
  least 2026-09-14, although the sells themselves are fine (broker-confirmed, position closed
  correctly, and `trades.exit_price` is right). It is a logging gap in `order_manager._lt_emit_order`'s call sites, not a
  trading defect. The replay builder should read fills from the database, not that file.
- **Sessions before 2026-09-02, or any session run without `--log`,** have no recording. The endpoint
  returns 404 and the UI falls back to the current dialog.
- **Log retention.** `logs/` is 1.6 GB and grows ~200 MB per session, dominated by the stream files.
  Once replays are extracted, compressing sessions older than a week is safe (the extracted JSON is
  what the UI reads).

## 8. Decisions (2026-09-23)

1. **Rebuild is manual** — run the script after a session. No cron for now.
2. **Plot the bid, with a mid toggle.** The bid is the price a buyer will actually pay you, and it is
   what every exit rule reads (stop, trail, target are all evaluated on the bid). The mid is the
   midpoint of bid and ask — a price nobody trades at, but the line most vendor charts draw because
   it is smoother. Consequence of plotting the bid honestly: the line **starts below the entry
   marker**, because we buy at the ask and are immediately marked at the bid. That gap is the spread
   and it is real money: ~0.3-0.5% on SPY contracts over $1, ~2.4% on IWM's (measured 2026-09-23).
   The mid toggle exists so the shape can be compared against an outside chart.
3. **`data/` added to `.gitignore`** — done 2026-09-23, alongside `logs/`.
4. **Dialog with a full-window expand** — not a separate route. Reached from Positions and
   Performance exactly as today; the expand control opens it full-window for study.

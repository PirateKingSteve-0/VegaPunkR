# Sizing and risk limits without the dashboard number — design

Written 2026-09-29, revised the same night after owner review. **Status: approved by the owner
(2026-09-29), sizing mode B (§3). Not built yet; timing to be agreed. Tests and engine-guard review
before it runs live.**
Related: TODO D6 (risk bands — out of scope), TODO A2 (reservation ledger), CLAUDE.md "Trading
Engine Integrity".

---

## In plain words

Today the engine decides **how many contracts to buy**, and sets its **daily loss** and **drawdown**
limits, from one saved number: `user.account_size_usd`. Nothing in the engine updates it; the
dashboard writes it when its account page loads (`routers/trading.py:40`). So the engine's risk
decisions depend on when someone last opened the dashboard.

On Monday 2026-09-28 it read **$1,757.84**, saved at 10:49 ET while a put worth ~$576 was open. At
11:18 ET it sized trade 3 at **2 contracts ($358)** with only **$551** of settled cash left. No rule
was broken (the separate buy gate caps every order at settled cash), but size did not shrink as the
day spent cash.

**The change (owner's design):**
1. The engine keeps one shared number per account: **cash left** (settled cash minus today's buys).
2. It is **set once at the start of the ET day** from Tradier, and again after any restart.
3. **When a buy fills, its cost comes off immediately** (fill price × quantity × 100). Sells change
   nothing, since that money settles tomorrow (T+1).
4. **A few seconds after each fill, one balance check**; keep the **lower** of Tradier's figure and
   our count, which catches fees and a lagging broker.
5. **Every strategy sizes from the start-of-day account value** (the same formula and 50% as
   today), **but never buys more than cash left can pay for** (minus buys still in flight).
6. **Daily loss and drawdown limits** use the **start-of-day account value**, fixed all day.

**Monday under the chosen rule (mode B)** — 50% of the start-of-day value (~$1,468), capped by cash left:

| Trade (ET) | Price | Formula on start-of-day | Cash left can pay for | Contracts today | Contracts new |
|---|---|---|---|---|---|
| 10:19 SPY 770P | $2.87 | 1 | 5 | 1 | 1 |
| 10:56 SPY 770P | $6.30 | 1 | 1 | 1 | 1 |
| 11:18 SPY 766P | $1.79 | 2 | 3 | 2 | **2** |

**Mode B barely changes Monday's sizes, on purpose.** What it fixes: sizing and the limits no longer
depend on when the dashboard was opened, every limit check sees one value all day (the Friday
two-caps problem), and cash left is enforced from the engine's own count before the preview, not
only by the broker after it.

**Mode A (not chosen, kept as a future setting, §8):** 50% *of what's left*. Monday would have been
1 / **skipped** (half of $1,181 can't cover a $630 contract) / 1. It gets more cautious as the day
spends cash.

**Broker calls:** 1 per account per ET day, plus 1 per restart, plus 1 check per fill (~6 on a
3-trade day). **Zero per blocked signal.**

---

## 1. What reads `account_size_usd` today

| Where | Use | New source |
|---|---|---|
| `risk_manager.calculate_position_size` (:261) | sizing base | start-of-day value (upper bound), then capped by cash left (§3) |
| `risk_manager._check_user_daily_loss_limit` (:543) | account daily loss cap | start-of-day value |
| `risk_manager._check_daily_loss_limit` (:619) | per-strategy daily loss cap | start-of-day value |
| `risk_manager._check_max_drawdown` (:715) | drawdown cap | start-of-day value |
| `risk_manager` risk status (:861) | UI risk bar | start-of-day value |

Any of them falls back to `account_size_usd` (today's behavior) only if the start-of-day value is
unknown, and logs a warning when it does.

**Likely cause of Friday's two "account-wide" caps** ($73.76 and $77.53 in the same second): each
strategy worker holds its own `User` row. If the dashboard rewrote `account_size_usd` between their
refreshes, they computed from different values. One shared start-of-day value ends that; a test
pins it (§6).

## 2. The shared account state — new `engine/account_state.py`

A small in-process store, one entry per **(user, trading mode)**, keyed by ET date
(`market_day_start_utc()`). Paper and live are different broker accounts and the mode can be
switched mid-day, so they never share an entry (engine-guard review H1, 2026-09-29).

```
cash_left          float  settled cash minus today's buy fills (never plus sells)
day_start_equity   float  total equity − today's realized − today's unrealized P&L
et_date            str    the ET day these belong to; a new day forces a refresh
```

- **Refresh** (async, one `get_balances` call): sets `cash_left = cash.cash_available` and
  `day_start_equity = total_equity − realized_today − unrealized_open` (both from the DB, the same
  queries the loss cap already runs). It runs before the first buy of an ET day and on the first
  buy after a restart. After a restart Tradier's settled cash already reflects the day's buys, and
  the start-of-day formula gives the same value it gave in the morning. **Restart-safe, nothing
  persisted, no migration.**
- **Buy fill** (§4): `cash_left −= price × qty × 100`, then schedule the check.
- **Check after a fill, the owner's "careful update" (2026-09-29).** 5 s after the fill, one
  `get_balances`:
  - broker figure **≥** our count: keep ours (the broker may be lagging);
  - **another buy in flight** (a reservation or an unconfirmed order): don't adopt, because that
    order's broker-side hold would be counted twice once it fills;
  - lower by **≤ $5** (fees/rounding): adopt;
  - lower by more: read again **30 s later**, and adopt only if the drop is still there. One
    glitchy reading can't block entries for the rest of the day.
- **Start-of-day sanity band:** rejected (→ old source, with a warning) if it is ≤ 0, more than 50%
  from total equity, or below the settled cash just read. Stale `Position` rows must not poison a
  day (review M2).
- **Deliberately one-way within a day:** it only goes down until tomorrow's refresh. A mid-day
  deposit is ignored until the next ET day. That's conservative, and the right way round.
- Single process only (like the reservation ledger). If the engine ever runs multi-process, this
  moves with A2.

The risk manager stays synchronous and only *reads* this store.

## 3. Sizing: start-of-day value, capped by cash left (mode B, buys only)

**Where:** `order_manager.execute_signal`, buys only, **before** `_preview_or_abort`, so the preview
describes the real order (CLAUDE.md: never skip the preview).

The day's **refresh** runs earlier, in the executor before sizing and `validate_pre_trade`, because
sizing and the loss caps read it. So a blocked signal *can* be the one that triggers it, but only
**once per account per ET day** (or once per 60 s while the broker is down). Every later signal,
blocked or not, is served from memory.

1. `await account_state.ensure_fresh(user)`: refreshes only if today's entry is missing.
2. `available = cash_left − _active_reservations_total(user.id)`: in-flight buys come off.
3. `affordable = floor(available / (price × 100 + $0.65))`: how many contracts cash left can
   actually pay for. The $0.65 per-contract fee allowance applies in prod too; otherwise an order
   sized to the last dollar would be refused whole by the post-preview gate instead of going
   through one contract smaller. An option order with no option price is left unchanged (never
   sized off the underlying's ~$750).
4. `final_qty = min(qty_from_executor, affordable)`, where `qty_from_executor` is the unchanged
   formula run on the start-of-day value. **Most-restrictive-bound wins.**
5. `final_qty == 0` → abort before preview: "cash left $X can't fund 1 contract at $Y". Logged once
   per blocked stretch (existing `_record_cash_block` pattern).

**Sells:** never sized here, never capped. Exits are sacred.

The authoritative post-preview settled-cash gate and the reservation ledger are unchanged; they
still run on every buy.

## 4. Where a buy fill updates cash left

Fills arrive two ways: the account stream (`tradier_account_stream`, order events only; Tradier's
account stream carries **no balances**, see `docs/tradier/streaming/ws_account_data.md`), or the
30 s REST poll when the stream is down. Both end in `order_manager` recording the fill (the Trade row
write in `execute_signal`, and the late-fill backfill path). **The update goes there**, so it covers
both routes and uses the engine's own side/qty/price. The stream event has no side or symbol.

**Late fills (backfill):** the cost is subtracted only if today's cash figure was read **before**
the order was placed (`placed_at`). Read after, the broker figure may already include the fill, so
the count is left alone and the careful check reconciles it. No double count (review M1b).

Orders the engine didn't place (e.g. a manual trade in the Tradier app) aren't recorded by the
engine, so they don't move the count. The post-fill check and the next day's refresh correct it,
and the pre-order gate still reads the broker. **Follow-up, not in v1:** an unknown-order fill on
the stream triggers a check.

## 5. If the broker doesn't answer

- **Refresh fails** (no entry for today): fall back to today's behavior (sizing on
  `account_size_usd`) with a warning. The post-preview settled-cash gate still protects, so
  nothing can overspend. (Recommended in review; the alternative was skipping the entry.)
- **Check after a fill fails:** keep the count; it's already been reduced by the fill.

## 6. What does not change

- The 50% setting, `max_contracts`, `max_position_size_usd`, the formula (D6 owns those).
- The post-preview cash gate, reservation ledger, idempotency, preview, rate limiter.
- Every exit path (SL/TP/trail/time), reconciliation.
- The dashboard still writes `account_size_usd` for display.

## 7. Tests (offline, broker mocked, in `scripts/run_tests.sh`)

1. Monday replay: $1,468 start, fills $287 / $630 → 1 / 1 / 2 (mode B). Same fills with cash left
   $300 at trade 3 → capped to 1.
2. Sell fill leaves cash left unchanged.
3. Reservation in flight is subtracted: $551 with $300 reserved → sized on $251.
4. Cash left can't fund 1 contract → no preview call, no order.
5. Post-fill check keeps the lower value; a higher broker value doesn't raise it.
6. New ET day → refresh; restart mid-day → refresh gives the broker's (already reduced) cash and
   the same start-of-day value.
7. Loss caps: two workers with different in-memory `User.account_size_usd` get the **same** cap
   (the Friday case); unknown start-of-day → old behavior plus a warning.
8. Blocked signals (risk check fails) → zero balance calls.

`engine-guard` review on the diff before merge.

## 8. Future setting: sizing mode A

Owner, 2026-09-29: *"we should definitely note that A is a thing and make it a setting maybe one
day."* Mode A = the risk percentage applies to **cash left** instead of the start-of-day value, so
sizes shrink as the day spends cash and a contract costing more than `risk% × cash left` is skipped
(the "at least 1" floor needs `risk% × cash left ≥ one contract`). Shape if built: a per-user or
per-strategy `sizing_basis: "day_start" | "cash_left"`, default `"day_start"`. With this design in
place it's a one-line change in which base the formula receives. Tracked in TODO D6.

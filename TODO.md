# TO DO

1. **(Code complete — pending live verification, 2026-05-05)** We need a way to track T+1 on day trading cash that way we cannot execute trades for money we don't have access to and acrue penalties for. Cash-only account, so GFV is the real constraint — three violations in 12 months and the broker restricts to settled-cash-only for 90 days. Took the strict approach: never use unsettled funds. In-process pending-buy reservation ledger layered on top of Tradier's `cash.cash_available`; reservations released when orders reach a terminal broker state. Sandbox-vs-live fee parity handled with a per-contract fee buffer in non-prod envs (Tradier sandbox returns commission/fees as 0). See journal 2026-05-05 (Part 2).
    - **Remaining:** verify against real sandbox traffic (concurrent signals on same account → reservations correctly subtract); verify against a live preview probe so we know `cost`/`order_cost`/`commission`/`fees` line up with what we assumed; refine `SANDBOX_FEE_BUFFER_PER_OPTION_CONTRACT` once a few live trades produce real `Trade.commission`+`Trade.fees` rows.
2. Per-strategy equity curve charts on the performance dashboard (and a multi-line roll-up on the overview). Useful for comparing live strategies against each other and against backtest results.
    - **Data source:** our own `Trade` rows (strategy_id + pnl + exit_timestamp). Not Tradier history (symbol-keyed, no strategy attribution) and not `SystemEvent` (activity log, not financial truth).
    - **Granularity:** per strategy *instance*, not per strategy *type* — type (`momentum`, `mean_reversion`) is a roll-up we can compute later via `strategy.strategy_type`.
    - **Curve shape:** realized cumulative PnL from zero (matches backtest convention, makes cross-strategy comparison meaningful). Revisit later if we want a true equity curve with allocated-capital baselines.
    - **Endpoint sketch:** `GET /performance/equity-curves` → `[{strategy_id, name, points: [{t, cum_pnl}]}]` for the user's strategies. Single per-strategy variant for the detail view.
    - **UI:** multi-line on overview for at-a-glance, toggleable per-strategy view on performance. Reuse `BaseChartDirective` + `themeService.chartColors()` for theme/CB compatibility.
    - **Gotcha:** x-axis must be `Trade.exit_timestamp` (PnL realized at close), not `Trade.timestamp` (entry). Verify closing-leg trades populate `exit_timestamp` before building.
3. We need to add a feature for backtesting data. What im thinking is what if we were able to use an available api call from tradier or a different broker to be able to help us collect data and test strategies. We could make it so when backtesting we can give params or constraints such as account size or other things to see how it might behave based on different things? Build #2 first so backtest results render in the same chart shape as live equity curves.
4. We need to figure out if we need to preview orders before execution. Whether that would be for slippage or for possible reconsideration in executing a trade for true TP defined. Defer until #2 is in place — without per-strategy equity curves we can't tell whether realized PnL is consistently below modeled (i.e. whether slippage is actually hurting us).
5. Fee tracker. If there is a way I would like to track the fees on the performance page. **Mostly already done** — `Trade.fees` + `Trade.commission` are populated from Tradier history, and the performance page surfaces commission/fees columns, period totals, and per-position attribution (`performance.component.ts:186-187, 236, 455-462`). Revisit only if there's a specific gap; otherwise close out.


# FUTURE CONSIDERATIONS

- A trading news api maybe we can find? Pure nice-to-have unless a strategy actually consumes news as a signal.

# DONE

- [x] A view in performance that shows a calendar with each day being green or red with the gain/loss inside the data block. _(2026-05-03)_
- [x] Dark mode + colorblind mode (blue/orange palette) toggleable from the user menu. CSS custom properties (`--color-profit`, `--color-loss`, `--surface`, `--text`, `--border`, etc.) drive theming; future UI work should use these tokens instead of hardcoded colors. _(2026-05-03)_
- [x] Account-level trading window. Toggleable per-user start/end time (ET, "HH:MM") in the user menu; layers on top of per-strategy `entry_after_open_minutes` / `exit_before_close_minutes` with most-restrictive-bound-wins semantics so users can never widen past strategy defaults. _(2026-05-05)_

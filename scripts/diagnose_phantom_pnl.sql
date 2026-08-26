-- Diagnose the phantom $223k close and the missing EOD exit.
-- Read-only. Run against dev and/or prod:
--   psql "$(grep '^DATABASE_DEV_URL='  .env | cut -d= -f2-)" -f scripts/diagnose_phantom_pnl.sql
--   psql "$(grep '^DATABASE_PROD_URL=' .env | cut -d= -f2-)" -f scripts/diagnose_phantom_pnl.sql

\echo '=== 1. Outsized closes (|pnl| > $5k) — these should not exist ==='
SELECT t.id, t.symbol, p.option_symbol, t.side, t.qty, t.filled_qty,
       t.price AS entry, t.exit_price, t.pnl,
       t.timestamp, t.exit_timestamp,
       t.notes->>'signal_reason'    AS reason,
       t.notes->>'exit_price_source' AS price_source,
       t.notes->>'reconciled'        AS reconciled
FROM trades t
LEFT JOIN positions p ON p.id = t.position_id
WHERE abs(coalesce(t.pnl,0)) > 5000
ORDER BY t.exit_timestamp DESC NULLS LAST;

\echo ''
\echo '=== 2. Everything closed on a weekend (market shut — reconcile-fabricated) ==='
SELECT t.id, t.symbol, p.option_symbol, t.qty, t.price AS entry, t.exit_price, t.pnl,
       t.exit_timestamp,
       to_char(t.exit_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern', 'Dy YYYY-MM-DD HH24:MI') AS et,
       t.notes->>'exit_price_source' AS price_source
FROM trades t
LEFT JOIN positions p ON p.id = t.position_id
WHERE extract(isodow from (t.exit_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern')) >= 6
ORDER BY t.exit_timestamp DESC;

\echo ''
\echo '=== 3. Positions whose current_price looks like the UNDERLYING, not the premium ==='
\echo '    (option position priced >20x its own entry premium = polluted)'
SELECT id, symbol, option_symbol, qty, avg_entry_price, current_price, unrealized_pnl,
       peak_price, trough_price, opened_at, updated_at
FROM positions
WHERE option_symbol IS NOT NULL
  AND avg_entry_price > 0
  AND (current_price > avg_entry_price * 20 OR abs(coalesce(unrealized_pnl,0)) > 5000)
ORDER BY updated_at DESC;

\echo ''
\echo '=== 4. All currently-open positions (should be flat outside a run) ==='
SELECT id, user_id, strategy_id, symbol, option_symbol, qty,
       avg_entry_price, current_price, unrealized_pnl, opened_at
FROM positions WHERE qty > 0 ORDER BY id;

\echo ''
\echo '=== 5. Strategy time-exit params — 0 or null means NO EOD exit fires ==='
SELECT s.id, s.name, s.is_active, s.is_paper_trading,
       s.params_json->>'exit_before_close_minutes' AS exit_before_close_min,
       s.params_json->>'max_hold_time_minutes'     AS max_hold_min,
       s.params_json->>'stop_loss_pct'             AS stop_loss_pct,
       s.params_json->>'take_profit_pct'           AS take_profit_pct
FROM strategies s ORDER BY s.id;

\echo ''
\echo '=== 6. Account trading window (can pull exits earlier, never later) ==='
SELECT id, email, role, selected_trading_mode, account_size_usd, timezone,
       trading_window_enabled, trading_window_start, trading_window_end,
       daily_loss_limit_pct
FROM users ORDER BY id;

\echo ''
\echo '=== 7. Realized P&L by ET market day, last 60 days ==='
SELECT (t.exit_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern')::date AS et_day,
       to_char((t.exit_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern'), 'Dy') AS dow,
       count(*) AS closes, round(sum(t.pnl)::numeric, 2) AS pnl
FROM trades t
WHERE t.exit_timestamp IS NOT NULL
  AND t.exit_timestamp > now() - interval '60 days'
GROUP BY 1, 2 ORDER BY 1 DESC;

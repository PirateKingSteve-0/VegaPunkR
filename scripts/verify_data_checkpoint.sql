-- Data-accuracy checkpoint verification.
--
-- Every check below asserts an invariant that the 2026-08-25 engine fixes are
-- supposed to guarantee. Run it against any environment; rows are scoped to
-- trades recorded AFTER the checkpoint so historical damage does not mask
-- whether the fixes are actually holding.
--
--   psql "$(grep '^DATABASE_DEV_URL=' .env | cut -d= -f2-)" -f scripts/verify_data_checkpoint.sql
--
-- Change :cp_trade_id if you set a later checkpoint.
\set cp_trade_id 2905

\echo ''
\echo '════════════════════════════════════════════════════════════════════'
\echo ' DATA ACCURACY CHECKPOINT — verifying trades with id > 2905 (CP-1)'
\echo '════════════════════════════════════════════════════════════════════'

\echo ''
\echo '1. No fabricated P&L  (|pnl| > $5,000 on a 1-3 contract 0DTE is impossible)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM trades WHERE id > :cp_trade_id AND abs(COALESCE(pnl,0)) > 5000;

\echo ''
\echo '2. No entries after the forced-exit time  (churn gate: 174 such entries pre-CP)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM trades WHERE id > :cp_trade_id AND side='buy'
  AND (timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern')::time >= '15:45';

\echo ''
\echo '3. No exit priced from a guessed mark  (approx_streamed_quote is retired;'
\echo '   valid sources are broker_fill / rest_quote / expired_worthless /'
\echo '   unknown_booked_at_cost, the last of which also logs an ERROR)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM trades WHERE id > :cp_trade_id
  AND notes->>'exit_price_source' = 'approx_streamed_quote';

\echo ''
\echo '4. No position marked at the UNDERLYING price'
\echo '   (an option premium >= 25% of its underlying is contamination, not a premium)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM positions WHERE option_symbol IS NOT NULL AND avg_entry_price > 0
  AND current_price > avg_entry_price * 20;

\echo ''
\echo '5. Every close records WHICH contract it closed'
\echo '   (positions.option_symbol is reused by the next entry and cannot answer this)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM trades WHERE id > :cp_trade_id AND side='sell'
  AND notes->>'option_symbol' IS NULL;

\echo ''
\echo '6. Every strategy has a real time-of-day exit  (>= 15 min, never 0/absent)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' strategies)' END AS result
FROM strategies
WHERE COALESCE((params_json->>'exit_before_close_minutes')::int, 0) < 15;

\echo ''
\echo '7. No position left open across a session boundary  (0DTE must not survive the bell)'
SELECT CASE WHEN count(*)=0 THEN 'PASS' ELSE 'FAIL ('||count(*)||' rows)' END AS result
FROM trades t JOIN positions p ON p.id = t.position_id
WHERE t.id > :cp_trade_id AND t.side='sell' AND t.exit_timestamp IS NOT NULL
  AND p.opened_at IS NOT NULL
  AND (p.opened_at AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern')::date
    < (t.exit_timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'US/Eastern')::date;

\echo ''
\echo '── Post-checkpoint activity (0 rows just means the engine has not run yet) ──'
SELECT count(*) AS trades_since_cp,
       COALESCE(min(id), 0) AS first_id,
       COALESCE(max(id), 0) AS last_id,
       round(COALESCE(sum(pnl),0)::numeric,2) AS pnl_since_cp
FROM trades WHERE id > :cp_trade_id;

\echo ''
\echo '── Corrected historical rows (audit trail, should stay at 4) ──'
SELECT id, notes->>'corrected_from_pnl' AS was, round(pnl::numeric,2) AS now
FROM trades WHERE notes->>'corrected_at' IS NOT NULL ORDER BY id;

-- Correct four expiry settlements that the reconcile fallback booked as sales.
--
-- Root cause: stream_driven_worker._reconcile_position fell back to
-- position.current_price when the broker had no close-fill on record (Tradier's
-- /orders covers only the current session). For trade 2408 that field held the
-- UNDERLYING's price (SPY 747.03 on 2026-07-31), producing a +$223,119 phantom.
-- The other three held stale option marks — plausible, but still last-trade
-- prices rather than settlement, and all recorded as gains on losing positions.
--
-- All four contracts expired IN THE MONEY. SPY options are PM-settled and
-- auto-exercise if ITM by $0.01 at the 4pm close, so the economically correct
-- exit is the intrinsic value at that close: max(0, SPY_close - strike).
-- SPY closes fetched from GET /v1/markets/history (live host) on 2026-08-25.
--
--   id    contract              expiry      strike  SPY close  settle
--   1954  SPY260727C00738000    2026-07-27     738     739.09    1.09
--   2408  SPY260731C00745000    2026-07-31     745     747.03    2.03
--   2758  SPY260807C00771000    2026-08-07     771     773.26    2.26
--   2797  SPY260819C00768000    2026-08-19     768     769.06    1.06
--
-- Pre-correction rows are backed up in
--   scripts/backups/phantom_trades_pre_correction_2026-08-25.json
--
-- Engine fixes that stop this recurring are in the same change:
--   * signal_generator: forced-exit time is now the ENTRY cutoff too, so the
--     engine cannot open a position it must immediately close (174 such
--     entries, one of which straddled the bell and became 2408).
--   * strategy_executor: positions are marked off the HELD contract's quote,
--     never the underlying tick price.
--   * stream_driven_worker._fallback_exit_price: broker fill -> REST quote ->
--     own mark, each sanity-checked against the underlying; books at cost and
--     logs an error rather than inventing a number.

BEGIN;

CREATE TEMP TABLE settlement (trade_id int, settle numeric, spy_close numeric, strike numeric) ON COMMIT DROP;
INSERT INTO settlement VALUES
  (1954, 1.09, 739.09, 738),
  (2408, 2.03, 747.03, 745),
  (2758, 2.26, 773.26, 771),
  (2797, 1.06, 769.06, 768);

\echo '--- BEFORE ---'
SELECT t.id, t.qty, t.price AS entry, t.exit_price, round(t.pnl::numeric,2) AS pnl
FROM trades t WHERE t.id IN (SELECT trade_id FROM settlement) ORDER BY t.id;

UPDATE trades t
SET exit_price = s.settle,
    pnl        = round(((s.settle - t.price::numeric) * COALESCE(t.filled_qty, t.qty) * 100), 2),
    notes      = (
      t.notes::jsonb || jsonb_build_object(
        'corrected_at',            '2026-08-25',
        'corrected_from_exit_price', t.exit_price,
        'corrected_from_pnl',      round(t.pnl::numeric, 2),
        'correction_basis',        'expiry settlement: max(0, SPY close - strike), '
                                   || 'SPY close ' || s.spy_close || ' strike ' || s.strike,
        'correction_source',       'Tradier GET /v1/markets/history (live)',
        'correction_reason',       'reconcile fallback booked an expiry as a sale; '
                                   || 'exit price was not a real fill'
      )
    )::json
FROM settlement s
WHERE t.id = s.trade_id;

\echo '--- AFTER ---'
SELECT t.id, t.qty, t.price AS entry, t.exit_price, round(t.pnl::numeric,2) AS pnl,
       t.notes->>'corrected_from_pnl' AS was
FROM trades t WHERE t.id IN (SELECT trade_id FROM settlement) ORDER BY t.id;

\echo '--- TOTALS ---'
SELECT round(sum(pnl)::numeric,2) AS all_time_pnl_after_correction FROM trades;

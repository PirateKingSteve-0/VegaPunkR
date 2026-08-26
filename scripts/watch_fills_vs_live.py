#!/usr/bin/env python3
"""
Live watch: SANDBOX fill price vs LIVE market quote, per contract.

THE ONE QUESTION THIS ANSWERS
The engine reads LIVE option quotes (sandbox has no market-data stream) but FILLS in
sandbox. If those two prices track each other, sandbox P&L is trustworthy. If they
diverge consistently, entries and exits are priced in different universes and no
strategy metric measured in sandbox means anything. This joins the two — which the
engine itself never does — and prints the divergence for every fill, live.

READ-ONLY. Places no orders. Cannot touch the engine. Safe to run alongside it.

  live_mid   = Tradier LIVE quote for the contract, fetched the moment the fill appears
  fill_price = the sandbox fill the engine actually got (Trade.price / Trade.exit_price)
  divergence = (live_mid - fill_price) / fill_price

A one-off 5% can be latency (fill happened seconds before we polled). A STEADY +50%
across every fill is the two-universe signature.

Usage:
    python scripts/watch_fills_vs_live.py                 # today, strategy 3 (SPY)
    python scripts/watch_fills_vs_live.py --strategy 2    # a different strategy
    python scripts/watch_fills_vs_live.py --date 2026-07-14 --replay   # backtest the watch
                                                          # on a past day (no live quotes)
"""
import argparse
import sys
import time
from datetime import datetime

sys.path.insert(0, "/Users/pirateking/Github/VegaPunkR/api")

from sqlalchemy import text  # noqa: E402
from database import SessionLocals, Environment  # noqa: E402
from models import Trade, Position  # noqa: E402
from tradier_integration.client import TradierClient  # noqa: E402

POLL_SECONDS = 8
FLOW_EVENTS = {  # system_events worth narrating as they happen
    "POSITION_OPENED", "POSITION_CLOSED", "POSITION_MANUALLY_CLOSED",
    "POSITION_ADOPTED_FROM_BROKER", "ORDER_UNCONFIRMED", "ORDER_BACKFILLED",
    "ENTRY_BLOCKED_UNCONFIRMED", "ORDER_RATE_LIMITED", "CLOSE_FAILED",
    "CLOSE_REJECTED", "POSITION_STACKED",
}


def occ_for_trade(db, trade) -> str:
    pos = db.query(Position).filter(Position.id == trade.position_id).first() if trade.position_id else None
    return (pos.option_symbol if pos else None) or (trade.notes or {}).get("option_symbol") or trade.symbol


def live_mid(client, occ) -> float:
    try:
        q = client.get_quotes([occ])
        if not q:
            return 0.0
        bid = float(q[0].get("bid") or 0)
        ask = float(q[0].get("ask") or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        return float(q[0].get("last") or 0)
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", type=int, default=3)
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--replay", action="store_true",
                    help="past-day mode: skip live-quote fetch (market data is stale anyway)")
    args = ap.parse_args()

    db = SessionLocals[Environment.DEV]()
    client = TradierClient(env="sandbox")

    print(f"WATCH  strategy={args.strategy}  date={args.date}  "
          f"{'REPLAY (no live quotes)' if args.replay else 'LIVE'}")
    print("read-only — places no orders\n")
    print(f"  {'time':<9} {'evt/side':<10} {'contract':<22} {'fill':>7} {'live':>7} {'diverge':>8}")
    print(f"  {'-'*9} {'-'*10} {'-'*22} {'-'*7} {'-'*7} {'-'*8}")

    # Cursor = GLOBAL max id at launch, so a live run only ever shows fills that happen
    # AFTER we start watching (not a replay of the day so far). Replay mode starts at 0
    # and reads the whole target day once.
    if args.replay:
        trade_cursor = 0
        trade_date_filter = args.date
        event_cursor = 0
    else:
        trade_cursor = db.execute(text("SELECT COALESCE(MAX(id),0) FROM trades")).scalar()
        trade_date_filter = None
        event_cursor = db.execute(text("SELECT COALESCE(MAX(id),0) FROM system_events")).scalar()
    print(f"  (watching for fills after trade id {trade_cursor}, event id {event_cursor})\n"
          if not args.replay else "")

    divs, last_strike = [], None
    try:
        while True:
            # End any open transaction so the next query sees rows committed by the
            # engine since our last poll. expire_all() alone clears the identity map but
            # keeps the transaction's snapshot — which is why the first watcher missed a
            # fill that committed mid-session. rollback() forces a fresh snapshot.
            db.rollback()
            db.expire_all()

            # --- new fills: the core comparison ---
            q = db.query(Trade).filter(
                Trade.id > trade_cursor,
                Trade.strategy_id == args.strategy,
            )
            if trade_date_filter:
                q = q.filter(text("DATE(trades.timestamp) = :d")).params(d=trade_date_filter)
            trades = q.order_by(Trade.id).all()
            for t in trades:
                trade_cursor = t.id
                occ = occ_for_trade(db, t)
                # Only compare REAL option contracts. If the contract resolves to the bare
                # underlying ("SPY"), we'd be comparing an option fill to the stock quote —
                # meaningless. OCC symbols are long (root+YYMMDD+C/P+strike).
                is_option = len(occ) > 6 and any(ch in occ for ch in "CP")
                fill = (t.exit_price if t.side == "sell" and t.exit_price else t.price) or 0.0
                lm = live_mid(client, occ) if (not args.replay and is_option) else 0.0
                div = ((lm - fill) / fill) if (fill > 0 and lm > 0) else None
                if div is not None:
                    divs.append(div)
                    flag = "  <<< DIVERGED" if abs(div) > 0.15 else ""
                else:
                    flag = ""
                ts = (t.exit_timestamp or t.timestamp)
                strike_note = ""
                pos = db.query(Position).filter(Position.id == t.position_id).first() if t.position_id else None
                strike = (pos.option_symbol if pos else occ)
                if strike != last_strike and t.side == "buy":
                    strike_note = "  [strike changed → reselection]"
                    last_strike = strike
                print(f"  {ts:%H:%M:%S} {t.side:<10} {occ[-22:]:<22} "
                      f"{fill:>7.2f} {(lm if lm else 0):>7.2f} "
                      f"{(f'{div:+.0%}' if div is not None else '  n/a'):>8}{flag}{strike_note}")

            # --- flow narrative ---
            events = db.execute(text("""
                SELECT id, created_at, event_type, title FROM system_events
                WHERE id > :c AND event_type = ANY(:types) ORDER BY id
            """), {"c": event_cursor, "types": list(FLOW_EVENTS)}).fetchall()
            for eid, ts, et, title in events:
                event_cursor = eid
                print(f"  {ts:%H:%M:%S} {'· ' + et:<10}   {title[:52]}")

            if args.replay:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        if divs:
            n = len(divs)
            avg = sum(divs) / n
            big = sum(1 for d in divs if abs(d) > 0.15)
            print(f"\n=== SUMMARY: {n} fills compared to live ===")
            print(f"  mean divergence : {avg:+.1%}")
            print(f"  |divergence|>15%: {big} of {n}  ({big/n:.0%})")
            print(f"  VERDICT: {'SANDBOX FILLS DESYNC FROM LIVE — cannot measure P&L here' if big/n > 0.5 else 'fills track live — sandbox P&L is usable'}")


if __name__ == "__main__":
    main()

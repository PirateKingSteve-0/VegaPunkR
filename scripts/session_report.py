#!/usr/bin/env python3
"""Did the exit-pricing fixes work? Read-only end-of-session report.

    ./venv/bin/python scripts/session_report.py [--date YYYY-MM-DD] [--env DEV|PROD]

Baselines to beat, from the two broken sessions:

    2026-08-26   16 round trips   median hold 2.1s    13/16 exits mismatched
    2026-08-27  100 round trips   median hold ~5s     95/100 exits mismatched
"""
import argparse, os, sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

OK, BAD, WARN, DIAG = "  ok  ", " BAD  ", " WARN ", " diag "
MISMATCH_PTS = 8.0          # claimed vs realised gap that counts as broken

# Checks 1 and 2 compare the price the engine DECIDED on against the price the
# broker FILLED at. On sandbox those come from different systems: quotes stream
# from production (ws.tradier.com, real) while fills are invented by sandbox.
#
# 2026-09-01 verified: engine priced SPY260901P00765000 at ~2.34 at 12:20:45 ET;
# the tape traded it at 2.305 that minute. Sandbox "filled" the entry at 1.20 —
# about half the real price — so every position looked instantly +90% and took
# profit within seconds. The engine was right; the fill was fiction.
#
# So on sandbox these two can never pass, and a red BAD is misleading. They stay
# useful as diagnostics — a big gap is expected, a SMALL one would be news.
SANDBOX = os.getenv("TRADIER_ENV", "sandbox").strip().lower() != "live"


def claimed_pct(reason):
    for key in ("Stop loss hit:", "Take profit hit:"):
        if key in (reason or ""):
            raw = reason.split(key)[1].split("<=")[0].split(">=")[0]
            try:
                return float(raw.strip().rstrip('%'))
            except ValueError:
                return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=date.today().isoformat())
    ap.add_argument('--env', default='DEV', choices=['DEV', 'PROD'])
    a = ap.parse_args()
    url = os.environ.get(f'DATABASE_{a.env}_URL')
    if not url:
        sys.exit(f"DATABASE_{a.env}_URL not set")

    with create_engine(url).connect() as c:
        sells = c.execute(text("""
            SELECT id, strategy_id, price, exit_price, pnl, qty,
                   notes->>'signal_reason'
            FROM trades WHERE side='sell' AND pnl IS NOT NULL
              AND timestamp::date = :d ORDER BY id"""), {"d": a.date}).fetchall()
        legs = c.execute(text("""
            SELECT strategy_id, side, timestamp FROM trades
            WHERE timestamp::date = :d ORDER BY id"""), {"d": a.date}).fetchall()
        adopts = c.execute(text("""
            SELECT created_at, strategy_id, title FROM system_events
            WHERE created_at::date = :d
              AND event_type IN ('POSITION_ADOPTED_FROM_BROKER',
                                 'POSITION_OWNERSHIP_TRANSFERRED')
            ORDER BY id"""), {"d": a.date}).fetchall()
        contracts = c.execute(text("""
            SELECT DISTINCT strategy_id, notes->>'option_symbol' FROM trades
            WHERE timestamp::date = :d AND notes->>'option_symbol' IS NOT NULL
            """), {"d": a.date}).fetchall()

    print(f"=== {a.env} {a.date} ===\n")
    if not sells:
        print("  no closed trades")
        return

    # 1 -------------------------------------------------- exit trigger accuracy
    mism, checked = 0, 0
    worst = []
    for r in sells:
        # r[2] is the ENTRY price: order_manager.py:1720 stores avg_entry_price
        # in trades.price on a sell leg and the actual fill in trades.exit_price.
        # Deriving entry from pnl instead (as this script did until 2026-09-01)
        # fabricates it and makes every realised % wrong.
        cl = claimed_pct(r[6])
        if cl is None or r[3] is None:
            continue
        entry, exit_fill = float(r[2]), float(r[3])
        if not entry:
            continue
        realised = (exit_fill - entry) / entry * 100
        checked += 1
        gap = abs(cl - realised)
        if gap > MISMATCH_PTS:
            mism += 1
            worst.append((gap, r[0], cl, realised))
    pct = (100 * mism / checked) if checked else 0
    tag = DIAG if SANDBOX else (OK if pct <= 10 else (WARN if pct <= 30 else BAD))
    print("1. decision price vs broker fill"
          + ("   [sandbox: expected to diverge]" if SANDBOX else
             "          (was 13/16, then 95/100)"))
    print(f"{tag} {mism}/{checked} exits off by more than {MISMATCH_PTS:.0f} points  ({pct:.0f}%)")
    for gap, tid, cl, rz in sorted(worst, reverse=True)[:3]:
        print(f"        trade {tid}: claimed {cl:+.1f}%  realised {rz:+.1f}%")

    # 2 -------------------------------------------------------------- hold time
    holds, open_at = [], {}
    for sid, side, ts in legs:
        if side == 'buy':
            open_at[sid] = ts
        elif open_at.get(sid):
            holds.append((ts - open_at.pop(sid)).total_seconds())
    print("\n2. how long positions were held"
          + ("           [sandbox: short holds are the fake-fill artifact]"
             if SANDBOX else "           (was 2.1s median)"))
    if holds:
        holds.sort()
        med = holds[len(holds) // 2]
        quick = sum(1 for h in holds if h < 10)
        tag = DIAG if SANDBOX else (OK if med >= 60 else (WARN if med >= 20 else BAD))
        print(f"{tag} median {med:.1f}s   under 10s: {quick}/{len(holds)}   "
              f"max {holds[-1]:.0f}s")
    else:
        print(f"{OK} no completed round trips")

    # 3 ------------------------------------------------------------- churn rate
    print("\n3. round trips                            (was 16, then 100)")
    per = {}
    for r in sells:
        per[r[1]] = per.get(r[1], 0) + 1
    tot = sum(per.values())
    tag = OK if tot <= 25 else (WARN if tot <= 60 else BAD)
    print(f"{tag} {tot} total  " + "  ".join(f"s{k}={v}" for k, v in sorted(per.items())))

    # 4 ------------------------------------------------- cross-strategy adoption
    print("\n4. phantom adoptions                      (was 1 on 08-27)")
    if not adopts:
        print(f"{OK} none")
    for ts, sid, title in adopts:
        print(f"{BAD} {ts:%H:%M:%S} strategy {sid}: {title}")

    # 5 ------------------------------------------------------- did puts trade?
    print("\n5. contracts traded, by strategy")
    if not contracts:
        print("      none")
    for sid, occ in contracts:
        side = 'PUT' if occ and 'P00' in occ else 'CALL'
        print(f"      s{sid}  {occ}  ({side})")

    # ------------------------------------------------------------------- P&L
    tot_pnl = sum(float(r[4]) for r in sells)
    wins = sum(1 for r in sells if float(r[4]) > 0)
    print(f"\nP&L {tot_pnl:+.2f} over {len(sells)} closes, {wins} winners "
          f"({100*wins/len(sells):.0f}%)")
    if SANDBOX:
        print("\n(TRADIER_ENV=sandbox: fills are invented, so 1, 2 and P&L are "
              "not\n meaningful. Checks 3-5 measure engine behaviour and still "
              "hold.)")
    else:
        print("\n(P&L is only meaningful once 1 and 2 look healthy.)")


if __name__ == '__main__':
    main()

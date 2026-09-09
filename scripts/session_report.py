#!/usr/bin/env python3
"""Did the exit-pricing fixes work? Read-only end-of-session report.

    ./venv/bin/python scripts/session_report.py [--date YYYY-MM-DD] [--env DEV|PROD]

Baselines to beat, from the two broken sessions:

    2026-08-26   16 round trips   median hold 2.1s    13/16 exits mismatched
    2026-08-27  100 round trips   median hold ~5s     95/100 exits mismatched
"""
import argparse, os, sys
from datetime import date, datetime

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
#
# Resolved PER SESSION from the database, not from the environment. This used to
# read TRADIER_ENV off .env, which is NOT what the engine routes on: the client
# is picked per user from `users.selected_trading_mode` ('paper' → Tradier
# sandbox, 'live' → Tradier live) at trading_client_manager.py:61. On 2026-09-08
# the engine traded LIVE the whole session while .env still said
# TRADIER_ENV=sandbox, so this report stamped "fills are invented ... P&L not
# meaningful" over three real round trips and a real +$46. Dismissing real money
# is the worse of the two errors, so an ambiguous answer resolves to LIVE.
SANDBOX = False   # assigned by main() from resolve_mode(); never read before that


def resolve_mode(conn, day):
    """Which broker filled this day's trades. Returns (sandbox, note, known).

    Mirrors trading_client_manager.py:61 exactly, including its `or "paper"`
    default for a NULL column, so this can never disagree with the routing the
    engine performed *right now*.

    The catch, and why `users.updated_at` is consulted: this reads PRESENT state
    to describe a PAST session, and nothing on the trade or the ORDER_PLACED
    event records which broker actually filled it. The dev database is the live
    example — its user row reads 'live' with updated_at=2026-09-02, but dev
    stopped trading on 09-01, so every dev session predates the flag it would be
    labelled with. Reporting those sandbox fills as "real money" is precisely the
    bug this function exists to kill, so a row touched on or after the session
    downgrades the answer to SUSPECT rather than asserting it.
    """
    rows = conn.execute(text("""
        SELECT DISTINCT u.email, COALESCE(u.selected_trading_mode, 'paper'),
               u.updated_at
        FROM trades t
        JOIN strategies s ON s.id = t.strategy_id
        JOIN users u      ON u.id = s.user_id
        WHERE t.timestamp::date = :d"""), {"d": day}).fetchall()

    modes = {m for _, m, _ in rows}
    if not modes:
        # Nothing traded, so nothing to attribute. Say so rather than asserting a
        # broker — a confident wrong label is the bug this function exists to fix.
        return False, "no trades to attribute", False

    # Any user row edited on or after the session day could have been a different
    # mode while the session ran. updated_at moves on ANY column change, so this
    # over-warns rather than under-warns — the safe direction for this question.
    day_start = datetime.fromisoformat(f"{day}T00:00:00")
    touched = [(e, u) for e, _, u in rows if u and u >= day_start]

    if modes == {"paper"}:
        sandbox, label = True, "users.selected_trading_mode=paper"
    elif modes == {"live"}:
        sandbox, label = False, "users.selected_trading_mode=live"
    else:
        detail = ", ".join(f"{e}={m}" for e, m, _ in sorted(rows))
        sandbox = False
        label = f"MIXED modes in one session ({detail}) — treating as LIVE"

    if touched:
        when = ", ".join(f"{e} updated {u:%Y-%m-%d}" for e, u in sorted(touched))
        return sandbox, f"SUSPECT: {label}, but {when} — on/after this session", True
    return sandbox, label, True


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
    global SANDBOX
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
        SANDBOX, mode_note, mode_known = resolve_mode(c, a.date)

    print(f"=== {a.env} {a.date} ===\n")
    broker = ("Tradier SANDBOX (paper)" if SANDBOX else "Tradier LIVE (real money)"
              ) if mode_known else "unknown"
    if mode_note.startswith("SUSPECT"):
        broker += "  (?)"
    print(f"broker: {broker}   [{mode_note}]")
    env_raw = os.getenv("TRADIER_ENV", "(unset)")
    if mode_known and (env_raw.strip().lower() != "live") != SANDBOX:
        print(f"{WARN} .env TRADIER_ENV={env_raw} disagrees with the database. "
              f"The engine\n       routes per user from the DB, so this report "
              f"follows the DB.")
    print()
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
        print("\n(Tradier sandbox: fills are invented, so 1, 2 and P&L are "
              "not\n meaningful. Checks 3-5 measure engine behaviour and still "
              "hold.)")
    else:
        print("\n(P&L is only meaningful once 1 and 2 look healthy.)")


if __name__ == '__main__':
    main()

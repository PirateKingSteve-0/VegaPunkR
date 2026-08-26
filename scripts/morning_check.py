#!/usr/bin/env python3
"""Read-only health check for the call/put pair. Writes nothing.

    ./venv/bin/python scripts/morning_check.py [--env DEV|PROD] [--no-broker]

Checks, in the order they matter:

  1. Duplicate open rows for one contract — means the daily-loss gate is
     counting a holding twice and halting the account early.
  2. DB open rows the broker does NOT hold — a position the engine thinks it
     has. Usually benign (closed externally) but worth seeing.
  3. Broker holdings with NO open DB row — the dangerous direction: a real
     contract with no stop loss, no take profit and no forced EOD exit.
  4. Each strategy's configured direction vs the side it actually holds.
"""
import argparse, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
from utils.symbol_helpers import parse_occ_symbol  # noqa: E402

OK, WARN, BAD = "  ok  ", " WARN ", " BAD  "


def side_of(occ):
    p = parse_occ_symbol(occ or "")
    return {'C': 'call', 'P': 'put'}.get(p.right, '?') if p else '?'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default='DEV', choices=['DEV', 'PROD'])
    ap.add_argument('--no-broker', action='store_true',
                    help='skip the Tradier calls, DB checks only')
    args = ap.parse_args()

    url = os.environ.get(f'DATABASE_{args.env}_URL')
    if not url:
        sys.exit(f"DATABASE_{args.env}_URL not set")
    print(f"=== {args.env} ===")

    with create_engine(url).connect() as c:
        strategies = c.execute(text(
            "SELECT id, name, is_active, params_json->>'direction', user_id "
            "FROM strategies ORDER BY id")).fetchall()
        rows = c.execute(text(
            "SELECT strategy_id, option_symbol, qty, unrealized_pnl "
            "FROM positions WHERE qty > 0 ORDER BY strategy_id")).fetchall()

    print("\nStrategies")
    for s in strategies:
        print(f"  id={s[0]:<3} active={s[2]!s:<5} direction={s[3]!s:<5} {s[1]}")

    print("\nOpen position rows")
    if not rows:
        print("  (none)")
    for r in rows:
        print(f"  strategy={r[0]:<3} {r[1]}  qty={r[2]}  unrealized={r[3]}")

    # 1. duplicates
    seen = {}
    for r in rows:
        seen.setdefault(r[1], []).append(r[0])
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    print("\n1. duplicate rows for one contract")
    if dupes:
        for occ, sids in dupes.items():
            print(f"{BAD} {occ} open on strategies {sids} — daily-loss gate is "
                  f"counting this holding {len(sids)}x")
    else:
        print(f"{OK} none")

    # 4. direction vs what is held
    dirs = {s[0]: (s[3] or 'call') for s in strategies}
    print("\n4. configured direction vs contract held")
    if not rows:
        print(f"{OK} nothing held")
    for r in rows:
        want, got = dirs.get(r[0], '?'), side_of(r[1])
        tag = OK if want == got else WARN
        print(f"{tag} strategy {r[0]} is a {want} strategy holding a {got}"
              + ("" if want == got else "  <-- direction was changed while holding"))

    if args.no_broker:
        return
    try:
        from tradier_integration.client import get_tradier_client
        broker = {str(p.get("symbol")): int(float(p.get("quantity", 0)))
                  for p in get_tradier_client().get_positions()
                  if float(p.get("quantity", 0)) > 0}
    except Exception as e:
        print(f"\n(broker check skipped: {type(e).__name__}: {str(e)[:90]})")
        return

    db_syms = {r[1] for r in rows}
    print("\n2. DB says open, broker does not hold")
    extra = db_syms - set(broker)
    print(f"{OK} none" if not extra else
          "\n".join(f"{WARN} {s} — engine thinks it holds this" for s in sorted(extra)))

    print("\n3. broker holds, no open DB row  (the dangerous direction)")
    missing = {s for s in broker if s not in db_syms and parse_occ_symbol(s)}
    print(f"{OK} none" if not missing else
          "\n".join(f"{BAD} {s} qty={broker[s]} — live contract with NO stop loss, "
                    f"take profit or EOD exit" for s in sorted(missing)))

    # 5. The realistic overnight hazard. strategy_executor auto-stops a strategy
    # after 20 consecutive errors WITHOUT closing its position, and a stopped
    # worker runs no SL/TP/EOD. A broker holding owned by an inactive strategy
    # is the one state where a real contract has no exit manager in any process.
    inactive = {s[0] for s in strategies if not s[2]}
    print("\n5. broker holding owned by an INACTIVE strategy")
    orphans = [r for r in rows if r[0] in inactive and r[1] in broker]
    if orphans:
        for r in orphans:
            print(f"{BAD} {r[1]} qty={r[2]} owned by strategy {r[0]}, which is "
                  f"stopped — nothing is running its stop loss or EOD exit")
    else:
        print(f"{OK} none")


if __name__ == '__main__':
    main()

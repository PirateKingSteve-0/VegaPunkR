#!/usr/bin/env python3
"""Bring PROD to the configuration the live test needs. Dry-run by default.

    ./venv/bin/python scripts/prep_prod_live_test.py            # show diff, write nothing
    ./venv/bin/python scripts/prep_prod_live_test.py --apply    # write it

Why each change — see docs/live-test-2026-09-02.md:

  1. PROD strategy 3 stores params_json['stop_loss_pct'] = 50 while its column
     and ['stop_loss_percentage'] say 15. signal_generator.py:549 reads the
     '_pct' key FIRST, so prod would run a 50% stop nobody chose. DEV runs 15.

  2. Position sizing uses min(user.max_trade_percentage, params['risk_per_trade_pct'])
     (risk_manager.py:80). At 2%/1.5% of a $1,060 account that is $15.90 of
     buying capacity — it cannot afford ANY qualifying 0DTE contract, so every
     entry silently sizes to zero contracts.

  3. A single 15% stop on a ~$470 position loses ~$70. PROD's daily cap of 10%
     is $106, so ~1 losing trade ends the day. 15% ($159) allows 2-3.

  4. PROD has no put strategy. Only puts have qualifying open interest for the
     2026-09-02 expiry (best in-band CALL OI is 510 against a 3000 floor), so
     without it the session trades nothing at all.

Nothing here touches the engine. These are data changes to the prod DB only.
"""
import argparse
import os
import sys
from copy import deepcopy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Both halves of the min(); see note 2. 50% of a $1,060 account is $530 of
# BUYING CAPACITY, not $530 at risk — the stop bounds the loss to ~15% of the
# position. The engine picks the contract closest to the delta midpoint
# (stream_driven_worker.py:1243), which on the 09-01 close was the $391 strike,
# not the $467 one — so this is ~36% headroom over the expected pick.
RISK_PCT = 50.0
MAX_TRADE_PCT = 50.0
DAILY_LOSS_PCT = 15.0
STOP_LOSS_PCT = 15.0


def show(label, before, after):
    mark = "   " if before == after else "-> "
    print(f"  {mark}{label:<34} {str(before):<22} {str(after)}")
    return before != after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='write the changes')
    a = ap.parse_args()

    from models import Strategy, User

    dev_url = os.environ['DATABASE_DEV_URL']
    prod_url = os.environ['DATABASE_PROD_URL']

    # Template the put strategy off DEV's strategy 4 so prod matches what was
    # actually shaken down, rather than a hand-written guess.
    with sessionmaker(bind=create_engine(dev_url))() as dev:
        tmpl = dev.query(Strategy).filter(Strategy.id == 4).first()
        if tmpl is None:
            sys.exit("DEV strategy 4 not found — nothing to mirror")
        tmpl_name = tmpl.name
        tmpl_type = tmpl.strategy_type
        tmpl_params = deepcopy(tmpl.params_json or {})
        tmpl_instruments = deepcopy(tmpl.instruments or [])
        tmpl_timeframe = tmpl.timeframe
        tmpl_max_positions = tmpl.max_positions
        tmpl_sl = tmpl.stop_loss_percentage
        tmpl_tp = tmpl.take_profit_percentage

    engine = create_engine(prod_url)
    changed = False

    with sessionmaker(bind=engine)() as db:
        print("=== PROD user 1 ===")
        user = db.query(User).filter(User.id == 1).first()
        if user is None:
            sys.exit("PROD user 1 not found")
        changed |= show("max_trade_percentage", user.max_trade_percentage, MAX_TRADE_PCT)
        changed |= show("daily_loss_limit_pct", user.daily_loss_limit_pct, DAILY_LOSS_PCT)
        show("selected_trading_mode", user.selected_trading_mode, user.selected_trading_mode)
        show("account_size_usd  (auto-syncs)", user.account_size_usd, user.account_size_usd)

        print("\n=== PROD strategy 3 (calls) ===")
        s3 = db.query(Strategy).filter(Strategy.id == 3).first()
        if s3 is None:
            sys.exit("PROD strategy 3 not found")
        p3 = deepcopy(s3.params_json or {})
        changed |= show("params.stop_loss_pct", p3.get('stop_loss_pct'), STOP_LOSS_PCT)
        changed |= show("params.stop_loss_percentage", p3.get('stop_loss_percentage'), STOP_LOSS_PCT)
        changed |= show("params.risk_per_trade_pct", p3.get('risk_per_trade_pct'), RISK_PCT)
        show("is_active  (leave OFF — no qualifying calls)", s3.is_active, s3.is_active)

        print("\n=== PROD strategy 4 (puts) ===")
        # params_json is a plain JSON column (not JSONB), so filter in Python
        # rather than with a ->> comparison the dialect cannot build.
        s4 = next(
            (s for s in db.query(Strategy).filter(Strategy.user_id == 1)
             if str((s.params_json or {}).get('direction', '')).lower() == 'put'),
            None,
        )
        if s4 is None:
            print(f"  -> CREATE  mirrored from DEV s4: {tmpl_name!r}")
            print(f"     direction=put  instruments={tmpl_instruments}  "
                  f"risk_per_trade_pct={RISK_PCT}  is_active=False")
            changed = True
        else:
            print(f"     exists (id={s4.id}) — updating risk only")
            p4 = deepcopy(s4.params_json or {})
            changed |= show("params.risk_per_trade_pct", p4.get('risk_per_trade_pct'), RISK_PCT)

        if not changed:
            print("\nAlready configured — nothing to do.")
            return

        if not a.apply:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            return

        # ---------------- writes ----------------
        user.max_trade_percentage = MAX_TRADE_PCT
        user.daily_loss_limit_pct = DAILY_LOSS_PCT

        p3['stop_loss_pct'] = STOP_LOSS_PCT
        p3['stop_loss_percentage'] = STOP_LOSS_PCT
        p3['risk_per_trade_pct'] = RISK_PCT
        s3.params_json = p3

        if s4 is None:
            params = deepcopy(tmpl_params)
            params['risk_per_trade_pct'] = RISK_PCT
            params['stop_loss_pct'] = STOP_LOSS_PCT
            params['stop_loss_percentage'] = STOP_LOSS_PCT
            s4 = Strategy(
                user_id=1,
                name=tmpl_name,
                strategy_type=tmpl_type,
                params_json=params,
                instruments=tmpl_instruments,
                timeframe=tmpl_timeframe,
                max_positions=tmpl_max_positions,
                stop_loss_percentage=tmpl_sl,
                take_profit_percentage=tmpl_tp,
                is_active=False,        # you activate it in the portal, deliberately
                is_paper_trading=False,
            )
            db.add(s4)
        else:
            p4 = deepcopy(s4.params_json or {})
            p4['risk_per_trade_pct'] = RISK_PCT
            s4.params_json = p4

        db.commit()
        print("\nWritten. Strategy 4 is INACTIVE — activate it in the portal.")

    # ---------------- verification ----------------
    with sessionmaker(bind=engine)() as db:
        print("\n=== verify: sizing math with the new values ===")
        user = db.query(User).filter(User.id == 1).first()
        acct = float(user.account_size_usd or 0)
        for s in db.query(Strategy).filter(Strategy.user_id == 1).order_by(Strategy.id):
            risk = float((s.params_json or {}).get('risk_per_trade_pct', 1.0))
            eff = min(float(user.max_trade_percentage or 2.0), risk)
            cap = acct * eff / 100.0
            print(f"  s{s.id} {(s.params_json or {}).get('direction','?'):<5} "
                  f"effective={eff:>5.1f}%  capital=${cap:>7.2f}  "
                  f"-> affords a contract up to ${cap:.0f}")


if __name__ == '__main__':
    main()

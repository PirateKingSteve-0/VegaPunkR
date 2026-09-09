#!/usr/bin/env python3
"""One-off: set `max_position_size_usd` -> None on every strategy, DEV and PROD.

    ./venv/bin/python scripts/null_position_size_cap.py

Context. The key shipped in all eight strategy templates and was read by NO code
until 2026-09-08, when enforcement was added to
`risk_manager.calculate_position_size`. Every existing strategy therefore carries
a value that has never bound anything. Turning enforcement on while those values
sit in the rows would silently start blocking real trades: the $500 template
value rejects any single contract priced above $5.00, which on 2026-09-08 would
have killed the session's best entry (SPY 773P at $5.72, +$55).

None means NO CAP. This restores the exact sizing behaviour of every live session
run so far, while leaving the control in place to switch on deliberately once the
account is large enough for a dollar ceiling to bind on purpose.

Refuses to touch a database that has an open position, so sizing can never change
underneath something the engine is currently managing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import flag_modified

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
from models import Strategy, Position  # noqa: E402


def main():
    for env in ("DEV", "PROD"):
        url = os.environ.get(f"DATABASE_{env}_URL")
        if not url:
            print(f"\n=== {env} === no DATABASE_{env}_URL, skipping")
            continue

        db = sessionmaker(bind=create_engine(url))()
        try:
            open_rows = db.query(Position).filter(Position.qty > 0).count()
            print(f"\n=== {env} ===  (open positions with qty>0: {open_rows})")
            if open_rows:
                print("  REFUSING: a position is open. Re-run when flat.")
                continue

            changed = 0
            for s in db.query(Strategy).order_by(Strategy.id).all():
                params = s.params_json or {}
                before = params.get("max_position_size_usd", "<absent>")
                if before is None:
                    print(f"  s{s.id} {s.name:<34} already None")
                    continue
                params["max_position_size_usd"] = None
                s.params_json = params
                # params_json is a JSON column: mutating the dict in place does
                # not mark the attribute dirty, so the UPDATE is never emitted.
                flag_modified(s, "params_json")
                print(f"  s{s.id} {s.name:<34} {before!r} -> None")
                changed += 1

            db.commit()

            for s in db.query(Strategy).order_by(Strategy.id).all():
                val = (s.params_json or {}).get("max_position_size_usd", "<absent>")
                print(f"  verify s{s.id}: max_position_size_usd={val!r}")
            print(f"  {changed} row(s) updated")
        finally:
            db.close()


if __name__ == "__main__":
    main()

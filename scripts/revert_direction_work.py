#!/usr/bin/env python3
"""Undo the 2026-08-26 put-support work's DATABASE changes on DEV.

Code is reverted separately with git (see --help output). This only touches the
two DEV rows the work created or modified:

  * strategy id=3  — restores params_json from the pre-change backup
  * strategy id=4  — the PUTS twin, deleted (and any rows referencing it)

Safe to run more than once. Prints what it will do and asks before writing
unless --yes is passed.

    ./venv/bin/python scripts/revert_direction_work.py [--yes]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BACKUP = os.path.join(os.path.dirname(__file__), 'backups',
                      'strategies_pre_direction_2026-08-26.json')

# 72a52a6 is the last commit before any put-support work.
BASE = "72a52a6"

GIT_HINT = f"""
Code revert (run separately, from the repo root). {BASE} is the last commit
before any of the put-support work:

    git revert --no-commit {BASE}..HEAD
    git commit -m "REVERT - put support"
    git push origin dev

Or, to inspect first:

    git log --oneline {BASE}..HEAD
    git diff {BASE}..HEAD -- api/engine/
"""


def main():
    ap = argparse.ArgumentParser(epilog=GIT_HINT,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--yes', action='store_true', help='skip the confirmation prompt')
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
    url = os.environ.get('DATABASE_DEV_URL')
    if not url:
        sys.exit("DATABASE_DEV_URL not set")

    with open(BACKUP) as f:
        backup = json.load(f)
    original = backup['strategy_3']['params_json']

    eng = create_engine(url)
    with eng.connect() as c:
        cur = c.execute(text("SELECT params_json->>'direction' FROM strategies "
                             "WHERE id=3")).scalar()
        has4 = c.execute(text("SELECT count(*) FROM strategies WHERE id=4")).scalar()
        n_pos = c.execute(text("SELECT count(*) FROM positions WHERE strategy_id=4")).scalar()
        n_trd = c.execute(text("SELECT count(*) FROM trades WHERE strategy_id=4")).scalar()

    print(f"  strategy 3 direction is currently {cur!r} -> will be removed")
    print(f"  strategy 4 exists: {bool(has4)}  (positions={n_pos}, trades={n_trd})")
    if n_trd:
        print("  NOTE: strategy 4 has trades. They will be deleted with it.")
    if not args.yes and input("proceed? [y/N] ").strip().lower() != 'y':
        sys.exit("aborted")

    with eng.begin() as c:
        c.execute(text("UPDATE strategies SET params_json=CAST(:p AS JSONB) WHERE id=3"),
                  {"p": json.dumps(original)})
        c.execute(text("DELETE FROM trades WHERE strategy_id=4"))
        c.execute(text("DELETE FROM positions WHERE strategy_id=4"))
        c.execute(text("DELETE FROM strategies WHERE id=4"))
    print("DEV rows restored.")
    print(GIT_HINT)


if __name__ == '__main__':
    main()

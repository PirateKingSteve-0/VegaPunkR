#!/usr/bin/env python3
"""
Fix negative-expectancy-by-construction on the active strategies.

THE PROBLEM
Both strategies had a stop LOSS wider than their take PROFIT. The win rate needed just
to break even is  SL / (SL + TP)  — so:

    TSLA   SL 20 / TP 15   ->  needs 57.1% win rate   (actual: 31%)
    SPY    SL 50 / TP 25   ->  needs 66.7% win rate

Every trade was therefore negative in expectation, and trading MORE only lost faster.
On 2026-07-13 TSLA took 124 round trips and lost $1,851. That was not a bug — the
engine did exactly what it was told.

THE HIDDEN PART
`params_json` carried BOTH key spellings with DIFFERENT values, and
signal_generator.py:342/355 reads `_pct` FIRST:

    stop_loss_pct = params.get('stop_loss_pct') or params.get('stop_loss_percentage')

SPY had stop_loss_pct=50 and stop_loss_percentage=15. The UI edits the `_percentage`
column, so the UI showed a 15% stop while the engine enforced 50%. The number on screen
was not the number being traded.

THE FIX
Set 1:2 risk/reward (SL 15% / TP 30%) — break-even win rate drops to 33.3% — and write
ALL FOUR keys plus the columns to the same value so nothing can silently disagree again.

    We deliberately do NOT delete the `_pct` keys: trading_safeguards.py:54 rejects any
    strategy whose `stop_loss_pct` is absent or < 10. That validator is currently dead
    code (nothing calls it), but if it is ever wired up, deleting the key would fail the
    strategy outright. Making the keys AGREE is safer than removing them.

WHAT THIS DOES NOT FIX
Nothing here makes the strategy profitable. At the observed 31% win rate, even 1:2 is
still  0.31 x 30 - 0.69 x 15 = -1.05%  per trade. This removes the STRUCTURAL flaw; the
signal itself still has to earn its keep. See docs/negative-expectancy.md.

Idempotent. Run with --apply to commit; default is a dry run.
"""
import argparse
import sys

sys.path.insert(0, "/Users/pirateking/Github/VegaPunkR/api")

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402
from database import SessionLocals, Environment  # noqa: E402
from models import Strategy  # noqa: E402

NEW_SL = 15.0   # percent
NEW_TP = 30.0   # percent  -> 1:2 risk/reward, break-even win rate = 15/(15+30) = 33.3%


def breakeven(sl: float, tp: float) -> float:
    return sl / (sl + tp) * 100


def main(apply: bool) -> int:
    db = SessionLocals[Environment.DEV]()
    strategies = db.query(Strategy).filter(Strategy.id.in_([2, 3])).all()

    print(f"target: SL {NEW_SL:.0f}% / TP {NEW_TP:.0f}%  "
          f"-> break-even win rate {breakeven(NEW_SL, NEW_TP):.1f}%\n")

    changed = 0
    for s in strategies:
        p = dict(s.params_json or {})
        old_sl = p.get('stop_loss_pct') or p.get('stop_loss_percentage')
        old_tp = p.get('take_profit_pct') or p.get('take_profit_percentage')

        print(f"{s.name}")
        print(f"   engine enforced : SL {old_sl} / TP {old_tp}  "
              f"(break-even {breakeven(old_sl, old_tp):.1f}%)")
        print(f"   UI displayed    : SL {s.stop_loss_percentage:.0f} / TP {s.take_profit_percentage:.0f}"
              + ("   <-- DID NOT MATCH THE ENGINE" if float(old_sl) != float(s.stop_loss_percentage) else ""))

        # All four keys + both columns, set to the same values so no reader can disagree.
        p['stop_loss_pct'] = NEW_SL
        p['take_profit_pct'] = NEW_TP
        p['stop_loss_percentage'] = NEW_SL
        p['take_profit_percentage'] = NEW_TP
        s.params_json = p
        flag_modified(s, "params_json")          # JSON column: mutate-in-place isn't tracked
        s.stop_loss_percentage = NEW_SL
        s.take_profit_percentage = NEW_TP

        print(f"   -> now          : SL {NEW_SL:.0f} / TP {NEW_TP:.0f}  "
              f"(break-even {breakeven(NEW_SL, NEW_TP):.1f}%)  [all 4 keys + columns]\n")
        changed += 1

    if not apply:
        db.rollback()
        print(f"DRY RUN — {changed} strategy(ies) NOT written. Re-run with --apply.")
        return 0

    db.commit()
    print("Committed. Verifying what the engine will now read:\n")
    for s in db.query(Strategy).filter(Strategy.id.in_([2, 3])).all():
        p = s.params_json
        sl = p.get('stop_loss_pct') or p.get('stop_loss_percentage')
        tp = p.get('take_profit_pct') or p.get('take_profit_percentage')
        agree = (float(sl) == float(s.stop_loss_percentage) == NEW_SL
                 and float(tp) == float(s.take_profit_percentage) == NEW_TP)
        print(f"   {s.name:<30} engine SL/TP {sl}/{tp}   UI {s.stop_loss_percentage:.0f}/"
              f"{s.take_profit_percentage:.0f}   consistent: {'YES' if agree else 'NO'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit the changes (default: dry run)")
    sys.exit(main(ap.parse_args().apply))

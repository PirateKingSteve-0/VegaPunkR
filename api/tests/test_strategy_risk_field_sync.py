"""A stop loss the API accepts must be the stop loss the engine applies.

The same two settings live in three places on a strategy:

    strategies.stop_loss_percentage        <- a real column
    params_json['stop_loss_pct']           <- what signal_generator.py:581 reads
    params_json['stop_loss_percentage']    <- its fallback

Only params_json is ever read by the engine, so `PATCH {"stop_loss_percentage":
30}` used to return 200, set the column, and change nothing about trading. On
prod the two genuinely diverged once (column 15, params 50).

`_reconcile_risk_fields` closes that. The properties, in order:

  1. Column-only edits TAKE EFFECT — pushed into params_json, both spellings,
     because the engine prefers `_pct` and a stale `_pct` would otherwise stay
     in charge.
  2. Contradictory writes are REFUSED (422) rather than silently resolved.
  3. Otherwise the column MIRRORS params_json, so the display cannot drift from
     what trades.
  4. Untouched fields are never rewritten from stale values.

Exercises the real router helper against real Strategy ORM objects. No network,
no DB session — the helper only reads/writes attributes.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))

from fastapi import HTTPException

from models import Strategy
from routers.strategies import _reconcile_risk_fields

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def strat(column_sl=15.0, column_tp=25.0, **params):
    s = Strategy()
    s.id = 4
    s.name = "SPY 0DTE Momentum (Puts)"
    s.stop_loss_percentage = column_sl
    s.take_profit_percentage = column_tp
    s.params_json = {"stop_loss_pct": 15, "stop_loss_percentage": 15,
                     "take_profit_pct": 25, "take_profit_percentage": 25,
                     **params}
    return s


print("1. a column-only edit actually takes effect:")
s = strat(column_sl=30.0)
_reconcile_risk_fields(s, {"stop_loss_percentage"})
check("params_json['stop_loss_pct'] follows the column", s.params_json["stop_loss_pct"], 30.0)
check("the fallback spelling is written too", s.params_json["stop_loss_percentage"], 30.0)
check("column keeps the requested value", s.stop_loss_percentage, 30.0)
check("take profit untouched (rule 4)", s.params_json["take_profit_pct"], 25)

print("\n2. a contradictory write is refused, not silently resolved:")
s = strat(column_sl=30.0, stop_loss_pct=15)
try:
    _reconcile_risk_fields(s, {"stop_loss_percentage", "params_json"})
    check("raises HTTPException", False, True)
except HTTPException as e:
    check("status is 422", e.status_code, 422)
    check("detail names both sides", "params_json['stop_loss_pct']" in str(e.detail), True)

print("\n3. agreeing values sent together are fine:")
s = strat(column_sl=15.0, stop_loss_pct=15)
try:
    _reconcile_risk_fields(s, {"stop_loss_percentage", "params_json"})
    check("no exception when they agree", True, True)
except HTTPException as e:
    check("no exception when they agree", f"raised {e.status_code}", True)

print("\n4. the column mirrors params_json on a params-only edit:")
s = strat(column_sl=15.0, stop_loss_pct=40, take_profit_pct=60)
_reconcile_risk_fields(s, {"params_json"})
check("column pulled up to the engine's value", s.stop_loss_percentage, 40.0)
check("take profit column too", s.take_profit_percentage, 60.0)

print("\n5. the prod divergence heals instead of persisting:")
# The real 2026-09 state: column said 15, params said 50, engine applied 50.
s = strat(column_sl=15.0, stop_loss_pct=50)
_reconcile_risk_fields(s, {"name"})          # an unrelated edit
check("column corrected to what the engine uses", s.stop_loss_percentage, 50.0)
check("params_json left alone", s.params_json["stop_loss_pct"], 50)

print("\n6. resolution order matches the engine exactly:")
# signal_generator.py:581 -> params['stop_loss_pct'] or params['stop_loss_percentage']
s = strat(column_sl=1.0)
s.params_json = {"stop_loss_percentage": 22}          # only the fallback present
_reconcile_risk_fields(s, {"name"})
check("falls back to _percentage when _pct absent", s.stop_loss_percentage, 22.0)

print("\n7. nothing to mirror leaves the column alone:")
s = strat(column_sl=15.0)
s.params_json = {}
_reconcile_risk_fields(s, {"name"})
check("column untouched when params carry nothing", s.stop_loss_percentage, 15.0)

print("\n8. a create with no risk fields sent does not invent values:")
s = strat(column_sl=None, column_tp=None)
s.params_json = {}
_reconcile_risk_fields(s, set())
check("stop loss column stays None", s.stop_loss_percentage, None)
check("take profit column stays None", s.take_profit_percentage, None)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

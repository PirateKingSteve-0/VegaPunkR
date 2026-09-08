"""The drawdown gate must measure where the strategy IS, not the worst it ever was.

The bug this pins down: `_check_max_drawdown` took the running MAXIMUM drawdown
over the strategy's entire trade history and compared that to the limit. A
running maximum only rises. Nothing reset it, and the query had no date filter,
so one bad stretch retired the strategy permanently — it kept showing as Active,
kept evaluating, kept generating signals, and silently refused every entry, even
after recovering to new all-time highs.

Measured on prod 2026-09-05: strategy 3 carried $119.00 of worst-ever drawdown
against a $121.43 limit. One $3 losing trade from being retired for good, with no
alert and nothing on screen to explain it.

The load-bearing assertion is RECOVERY: a strategy that dug a hole deeper than
the limit and then climbed out of it to a new high must be allowed to trade.

Scratch SQLite, no broker, no network.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Trade
from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<64} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


eng = create_engine("sqlite:///:memory:")
Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()

# $10,000 account, default max_drawdown_pct 10% -> a $1,000 limit.
u = User(email="dd@t.com", hashed_password="x", name="D", role="user",
         account_size_usd=10000.0)
db.add(u); db.flush()

# Old timestamps on purpose: these trades must be invisible to the DAILY loss
# gate, so anything that blocks here is unambiguously the drawdown gate.
BASE = datetime(2026, 1, 5, 15, 0, 0)

rm = RiskManager(db)


def strategy_with(pnls, name, params=None, timestamps=None):
    """One strategy carrying `pnls` as its closed-trade history."""
    st = Strategy(user_id=u.id, name=name, strategy_type="momentum",
                  params_json=params if params is not None else {}, max_positions=1)
    db.add(st); db.flush()
    for i, pnl in enumerate(pnls):
        ts = timestamps[i] if timestamps else BASE + timedelta(hours=i)
        db.add(Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side="sell",
                     qty=1, price=1.0, pnl=float(pnl), status="executed", timestamp=ts))
    db.commit()
    return st


print("\nthe gate itself:")

st = strategy_with([], "no history")
check("no trade history is not a drawdown", rm._check_max_drawdown(u, st).approved, True)

st = strategy_with([400, -300], "shallow")
# peak 400, final 100 -> current drawdown 300, under the $1,000 limit
check("a drawdown under the limit passes", rm._check_max_drawdown(u, st).approved, True)

st = strategy_with([400, -1500], "underwater")
# peak 400, final -1100 -> current drawdown 1500, over the limit
r = rm._check_max_drawdown(u, st)
check("a drawdown over the limit blocks", r.approved, False)
check("...and carries the machine-readable code", r.code, "max_drawdown")
check("...and says entries, not exits, are paused",
      "open positions are unaffected" in r.reason.lower(), True)

print("\nRECOVERY — the whole point of the fix:")

# +400, -300, -900, +2000: worst-ever drawdown was 1200 (over the $1,000 limit),
# but the strategy finished at +1200, its best level ever. Before the fix this
# was blocked forever.
st = strategy_with([400, -300, -900, 2000], "recovered to a new high")
check("a strategy that dug past the limit and recovered CAN TRADE",
      rm._check_max_drawdown(u, st).approved, True)

# Same history, minus the recovery leg. Still in the hole -> still blocked.
st = strategy_with([400, -300, -900], "still in the hole")
check("...but while still in the hole it stays blocked",
      rm._check_max_drawdown(u, st).approved, False)

# Recovered exactly back to the previous peak: drawdown is zero, not "the worst
# it ever was".
st = strategy_with([400, -300, -900, 1200], "recovered to flat at peak")
check("recovering exactly to the old peak clears the block",
      rm._check_max_drawdown(u, st).approved, True)

print("\nordering — a running total is meaningless unsorted:")

# True sequence is +1000, -1500, +200 (peak 1000, final -300, drawdown 1300 ->
# BLOCKED). Rows are INSERTED in a different order, so a query without an
# ORDER BY computes peak=0 and a drawdown of 300 -> wrongly approved.
st = strategy_with(
    [-1500, 1000, 200], "inserted out of order",
    timestamps=[BASE + timedelta(hours=2), BASE, BASE + timedelta(hours=1)],
)
check("drawdown is computed in timestamp order, not insertion order",
      rm._check_max_drawdown(u, st).approved, False)

print("\nthe read-only status used by the UI badge agrees with the gate:")

st = strategy_with([400, -1500], "blocked, for the badge")
st.is_active = True
db.commit()
status = rm.get_entry_block_status(u, st)
check("blocked strategy reports blocked", status["blocked"], True)
check("...with the same code the gate used", status["code"], "max_drawdown")

st = strategy_with([400, -300, -900, 2000], "recovered, for the badge")
st.is_active = True
db.commit()
check("recovered strategy reports clear", rm.get_entry_block_status(u, st)["blocked"], False)

st = strategy_with([400, -1500], "inactive, for the badge")
st.is_active = False
db.commit()
check("an INACTIVE strategy is not reported as blocked (it is just off)",
      rm.get_entry_block_status(u, st)["blocked"], False)

print("\nthe limit tracks account size:")

# $119 of drawdown against a 10% limit: blocked on a $1,000 account, fine on
# $10,000. This is the prod situation that prompted the fix.
st = strategy_with([200, -119], "the strategy-3 shape")
u.account_size_usd = 1000.0
db.commit()
check("$119 drawdown blocks a $1,000 account (limit $100)",
      rm._check_max_drawdown(u, st).approved, False)
u.account_size_usd = 10000.0
db.commit()
check("...and passes a $10,000 account (limit $1,000)",
      rm._check_max_drawdown(u, st).approved, True)

print("\nnotification hooks must never break the gate:")

st = strategy_with([400, -1500], "no discord prefs")
u.notification_preferences = None
db.commit()
rm._note_entry_block(u, st, rm._check_max_drawdown(u, st))
check("a user with no notification prefs does not raise", True, True)
rm._note_entry_clear(u, st)
check("clearing a block for an unnotified user does not raise", True, True)

print("\nthe off switch — max_drawdown_pct <= 0:")

# Deep underwater: a $1,500 drawdown against a $1,000 limit would normally block.
DEEP = [400, -1500]

st = strategy_with(DEEP, "disabled with 0", params={"max_drawdown_pct": 0})
check("0 disables the gate even when far underwater",
      rm._check_max_drawdown(u, st).approved, True)

st = strategy_with(DEEP, "disabled with a negative", params={"max_drawdown_pct": -5})
check("a negative threshold is off too", rm._check_max_drawdown(u, st).approved, True)

st = strategy_with(DEEP, "unset params")
check("an ABSENT setting still defaults to 10% (no silent disarm)",
      rm._check_max_drawdown(u, st).approved, False)

st = strategy_with(DEEP, "disabled, for the badge", params={"max_drawdown_pct": 0})
st.is_active = True
db.commit()
check("a disabled gate reports no block on the badge",
      rm.get_entry_block_status(u, st)["blocked"], False)

print("\nalert-only mode — max_drawdown_block=False:")

RiskManager._drawdown_bleed_state.clear()
st = strategy_with(DEEP, "bleeding but trading",
                   params={"max_drawdown_pct": 10, "max_drawdown_block": False})
check("past the threshold but NOT blocked", rm._check_max_drawdown(u, st).approved, True)
check("...and the bleed was recorded once",
      len(RiskManager._drawdown_bleed_state), 1)

# Re-evaluating must not raise a second alert; the entry path runs this
# hundreds of times a day.
before = dict(RiskManager._drawdown_bleed_state[(u.id, st.id)])
for _ in range(50):
    rm._check_max_drawdown(u, st)
check("...and 50 more evaluations do not re-alert",
      RiskManager._drawdown_bleed_state[(u.id, st.id)], before)

st_blocks = strategy_with(DEEP, "same numbers, blocking on",
                          params={"max_drawdown_pct": 10, "max_drawdown_block": True})
check("the same drawdown DOES block when the toggle is on",
      rm._check_max_drawdown(u, st_blocks).approved, False)

print("\nhysteresis — a strategy on the line must not flap:")

RiskManager._drawdown_bleed_state.clear()
P = {"max_drawdown_pct": 10, "max_drawdown_block": False}   # threshold $1,000

# peak 2000, final 850 -> drawdown 1150, over the threshold: alert.
st = strategy_with([2000, -1150], "over the line", params=P)
rm._check_max_drawdown(u, st)
check("over the threshold raises the bleed", len(RiskManager._drawdown_bleed_state), 1)

# peak 2000, final 1100 -> drawdown 900. Under the threshold but ABOVE 80% of
# it ($800), so the alert deliberately stays open.
st2 = strategy_with([2000, -900], "in the hysteresis band", params=P)
RiskManager._drawdown_bleed_state[(u.id, st2.id)] = {"since": None, "drawdown": 1150.0}
rm._check_max_drawdown(u, st2)
check("just under the threshold does NOT clear it yet",
      (u.id, st2.id) in RiskManager._drawdown_bleed_state, True)

# peak 2000, final 1300 -> drawdown 700, under 80% of the threshold: cleared.
st3 = strategy_with([2000, -700], "clear of the band", params=P)
RiskManager._drawdown_bleed_state[(u.id, st3.id)] = {"since": None, "drawdown": 1150.0}
rm._check_max_drawdown(u, st3)
check("dropping under 80% of the threshold clears it",
      (u.id, st3.id) in RiskManager._drawdown_bleed_state, False)

print()
if fails:
    print(f"FAILED ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all max-drawdown checks passed")

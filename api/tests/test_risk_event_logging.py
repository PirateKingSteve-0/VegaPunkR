"""A blocked trade must be REJECTED, never raise.

`RiskEvent` has no `message` column — it carries `details` JSON — but
`_log_risk_event` passed `message=` and had no try/except. Every gate routed
through it therefore raised

    TypeError: 'message' is an invalid keyword argument for RiskEvent

instead of returning a clean rejection. `strategy_executor` counts that as a
tick error, and at 20 consecutive errors it sets `strategy.is_active = False`
(`strategy_executor.py:238`). So hitting a daily loss cap did not pause the
strategy for the day — it switched the strategy OFF, and it stayed off.
Reachable on any ordinary session: the per-strategy cap defaults to 5% of
account, about two losing trades.

Why the existing tests missed it: they call the private `_check_*` helpers
directly. The crash lives in the LOGGING that `validate_pre_trade` does around
them, so it is only reachable through the public entry point. Every case here
goes through `validate_pre_trade`.

Scratch SQLite, no broker, no network.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Trade, Position, RiskEvent
from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


eng = create_engine("sqlite:///:memory:")
Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()

# daily_loss_limit_pct=0 switches the ACCOUNT-level cap off, so each case below
# reaches the specific per-strategy gate it is testing.
u = User(email="r@t.com", hashed_password="x", name="R", role="user",
         account_size_usd=1214.25, daily_loss_limit_pct=0, max_trade_percentage=50.0)
db.add(u); db.flush()

OLD = datetime(2026, 1, 5, 15, 0, 0)     # not "today" — invisible to daily gates
rm = RiskManager(db)


def make(name, params, trades=(), old_trades=(), open_qty=0, max_positions=5):
    st = Strategy(user_id=u.id, name=name, strategy_type="0dte", is_active=True,
                  is_paper_trading=False, max_positions=max_positions, params_json=params)
    db.add(st); db.flush()
    for i, pnl in enumerate(old_trades):
        db.add(Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side="sell", qty=1,
                     price=1.0, pnl=float(pnl), status="executed",
                     timestamp=OLD + timedelta(hours=i)))
    for pnl in trades:
        db.add(Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side="sell", qty=1,
                     price=1.0, pnl=float(pnl), status="executed",
                     timestamp=datetime.utcnow()))
    if open_qty:
        db.add(Position(user_id=u.id, strategy_id=st.id, symbol="SPY", qty=open_qty,
                        avg_entry_price=3.0))
    db.commit()
    return st


def attempt(st):
    """Run the real entry gate. Returns 'RAISED: ...' instead of blowing up, so a
    regression reads as a failed assertion rather than a stack trace."""
    try:
        r = rm.validate_pre_trade(user=u, strategy=st, symbol="SPY", qty=1,
                                  estimated_price=3.0, side="buy")
        return ("approved" if r.approved else "rejected"), r
    except Exception as e:
        return f"RAISED: {type(e).__name__}: {e}", None


def events_for(st):
    return db.query(RiskEvent).filter(RiskEvent.strategy_id == st.id).all()


print("\nthe three gates that log through _log_risk_event:")

# 1. per-strategy daily loss cap — 5% of $1,214.25 = $60.71, two typical losers
st = make("daily loss tripped", {"daily_loss_limit_pct": 5.0, "max_drawdown_pct": 0},
          trades=[-100.0])
outcome, res = attempt(st)
check("strategy daily loss: REJECTS, does not raise", outcome, "rejected")
check("...and persisted one risk event", len(events_for(st)), 1)
check("...with the reason in details, not a phantom column",
      "Daily loss limit" in (events_for(st)[0].details or {}).get("reason", ""), True)

# 2. max drawdown — old trades only, so the daily gates see nothing
st = make("drawdown tripped", {"daily_loss_limit_pct": 0, "max_drawdown_pct": 10},
          old_trades=[400, -1500])
outcome, res = attempt(st)
check("max drawdown: REJECTS, does not raise", outcome, "rejected")
check("...and persisted one risk event", len(events_for(st)), 1)

# 3. position cap
st = make("position cap tripped", {"daily_loss_limit_pct": 0, "max_drawdown_pct": 0},
          open_qty=1, max_positions=1)
outcome, res = attempt(st)
check("position limit: REJECTS, does not raise", outcome, "rejected")
check("...and persisted one risk event", len(events_for(st)), 1)

print("\nthe account-level cap still logs through its own writer:")

u.daily_loss_limit_pct = 5.0
db.commit()
st = make("account cap tripped", {"daily_loss_limit_pct": 0, "max_drawdown_pct": 0},
          trades=[-200.0])
outcome, res = attempt(st)
check("account daily loss: REJECTS, does not raise", outcome, "rejected")
check("...and carries its machine-readable code", res.code, "account_daily_loss")
u.daily_loss_limit_pct = 0
db.commit()

print("\na healthy strategy is still approved:")

# risk_per_trade_pct matches prod (50). Without it sizing defaults to 1% of
# account = $12, which cannot afford a single $300 contract, and the approval
# case would fail on position size before it ever proves the point.
st = make("all clear", {"daily_loss_limit_pct": 0, "max_drawdown_pct": 0,
                        "risk_per_trade_pct": 50})
outcome, res = attempt(st)
check("nothing tripped: approved", outcome, "approved")
check("...and wrote no risk event", len(events_for(st)), 0)

print("\nlogging must never decide whether a trade happens:")

# A write failure has to be swallowed. Poison the session's commit and confirm
# the gate still returns its verdict rather than propagating.
st = make("logging blows up", {"daily_loss_limit_pct": 5.0, "max_drawdown_pct": 0},
          trades=[-100.0])
real_commit = db.commit
db.commit = lambda: (_ for _ in ()).throw(RuntimeError("db is on fire"))
outcome, res = attempt(st)
db.commit = real_commit
check("a failed risk-event write still returns a clean rejection", outcome, "rejected")

print("\nexits are sacred — every risk gate must let a SELL through:")

# Each of these blocks a buy. None of them may block a sell: a breached cap
# must never strand an open position. Unreachable today (exits go through
# close_position, which skips validate_pre_trade) — pinned so it stays that way.
cases = [
    ("strategy daily loss", {"daily_loss_limit_pct": 5.0, "max_drawdown_pct": 0,
                             "risk_per_trade_pct": 50}, [-100.0], (), 0, 5),
    ("max drawdown",        {"daily_loss_limit_pct": 0, "max_drawdown_pct": 10,
                             "risk_per_trade_pct": 50}, (), [400, -1500], 0, 5),
    ("position cap",        {"daily_loss_limit_pct": 0, "max_drawdown_pct": 0,
                             "risk_per_trade_pct": 50}, (), (), 1, 1),
]
for label, params, today, old_t, open_qty, maxpos in cases:
    st = make(f"sell through {label}", params, trades=today, old_trades=old_t,
              open_qty=open_qty, max_positions=maxpos)
    buy, _ = attempt(st)
    check(f"{label}: buy is blocked", buy, "rejected")
    try:
        r = rm.validate_pre_trade(user=u, strategy=st, symbol="SPY", qty=1,
                                  estimated_price=3.0, side="sell")
        sell = "approved" if r.approved else f"REJECTED ({r.reason})"
    except Exception as e:
        sell = f"RAISED: {type(e).__name__}"
    check(f"{label}: SELL IS ALLOWED", sell, "approved")

# The account-wide cap and the manual halt were already side-aware; confirm the
# whole gate still lets a sell through when they are the ones tripped.
u.daily_loss_limit_pct = 5.0
db.commit()
st = make("sell through account cap", {"daily_loss_limit_pct": 0, "max_drawdown_pct": 0,
                                       "risk_per_trade_pct": 50}, trades=[-200.0])
buy, _ = attempt(st)
check("account daily loss: buy is blocked", buy, "rejected")
r = rm.validate_pre_trade(user=u, strategy=st, symbol="SPY", qty=1,
                          estimated_price=3.0, side="sell")
check("account daily loss: SELL IS ALLOWED", r.approved, True)
u.daily_loss_limit_pct = 0
db.commit()

print()
if fails:
    print(f"FAILED ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all risk-event logging checks passed")

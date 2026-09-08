"""MFE/MAE must survive position-row reuse — scratch SQLite, no broker, no network.

`positions.peak_price` / `trough_price` track excursion live, but
`_update_position_entry` RESETS both when it reuses a closed row for a new entry.
Position rows are reused for every re-entry into the same contract, so the figure
is destroyed by the next trade unless it is copied onto the sell leg at close.

Cost real data twice in the first live week: on 2026-09-02 and 09-03 the earlier
trade's peak was overwritten hours later by a re-entry into the same contract.
See TODO.md E5.

The load-bearing assertion is the LAST one: after a reopen wipes the position's
peak, the already-written Trade row must still hold the closed round trip's value.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Position, Trade
from engine.order_manager import OrderManager
from datetime import datetime

eng = create_engine("sqlite:///:memory:")
Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()

u = User(email="m@t.com", hashed_password="x", name="M", role="user", account_size_usd=100000)
db.add(u); db.flush()
st = Strategy(user_id=u.id, name="S", strategy_type="momentum",
              params_json={"exit_before_close_minutes": 15}, max_positions=1)
db.add(st); db.flush(); db.commit()

om = OrderManager(db)
C = "SPY260904P00774000"

failures = []
def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        failures.append((label, got, want))


def mk_trade(side, qty, price):
    t = Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side=side, qty=qty,
              filled_qty=qty, price=price, status="executed", timestamp=datetime.utcnow())
    db.add(t); db.flush(); return t


print("\n1) Open at 2.97, let it run to 4.93 and dip to 2.80")
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=1, price=2.97,
                          trade=mk_trade("buy", 1, 2.97), option_symbol=C)
pos = db.query(Position).filter(Position.option_symbol == C).one()
check("entry seeds peak and trough at the fill", (pos.peak_price, pos.trough_price), (2.97, 2.97))

# Excursion as the live loop would record it.
pos.peak_price = 4.93
pos.trough_price = 2.80
db.commit()

print("\n2) Close it — the sell leg must snapshot the excursion")
sell = Trade(user_id=u.id, strategy_id=st.id, position_id=pos.id, symbol="SPY",
             side="sell", qty=1, filled_qty=1,
             price=pos.avg_entry_price, exit_price=4.44,
             exit_timestamp=datetime.utcnow(), pnl=147.0, status="executed",
             timestamp=datetime.utcnow(),
             mfe_price=pos.peak_price, mae_price=pos.trough_price)
db.add(sell); db.commit()
sell_id = sell.id
check("sell leg captured MFE", sell.mfe_price, 4.93)
check("sell leg captured MAE", sell.mae_price, 2.80)

# Flatten the row the way a real close does — the reopen branch in
# _update_position_entry only fires for a row already at qty=0. With qty>0 it
# averages into the open position instead and legitimately keeps the peak.
pos.qty = 0
db.commit()

print("\n3) Re-enter the SAME contract — this is what used to destroy the data")
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=1, price=4.57,
                          trade=mk_trade("buy", 1, 4.57), option_symbol=C)
db.commit()
pos = db.query(Position).filter(Position.option_symbol == C).one()
check("reopen RESET the position's peak to the new fill", pos.peak_price, 4.57)
check("reopen RESET the position's trough to the new fill", pos.trough_price, 4.57)
check("...and it is the same row, not a second one",
      db.query(Position).filter(Position.option_symbol == C).count(), 1)

print("\n4) THE POINT: the closed trade's excursion survived that reset")
db.expire_all()
kept = db.query(Trade).filter(Trade.id == sell_id).one()
check("closed leg still reports its own MFE", kept.mfe_price, 4.93)
check("closed leg still reports its own MAE", kept.mae_price, 2.80)

print("\n5) Buy legs carry no excursion — a round trip is measured at its close")
buy = db.query(Trade).filter(Trade.side == "buy").order_by(Trade.id).first()
check("buy leg leaves MFE null", buy.mfe_price, None)
check("buy leg leaves MAE null", buy.mae_price, None)

print("\n6) Derived reads the report will make")
entry = kept.price
check("MFE as % of entry", round((kept.mfe_price - entry) / entry * 100, 1), 66.0)
check("MAE as % of entry", round((kept.mae_price - entry) / entry * 100, 1), -5.7)
realised = (kept.exit_price - entry) / entry * 100
check("MFE capture ratio (realised / MFE)",
      round(realised / ((kept.mfe_price - entry) / entry * 100), 2), 0.75)

print()
if failures:
    print(f"{len(failures)} FAILED")
    for l, g, w in failures:
        print(f"   {l}\n     got  {g!r}\n     want {w!r}")
    sys.exit(1)
print("ALL PASSED")

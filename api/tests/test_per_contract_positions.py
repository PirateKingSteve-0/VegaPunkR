"""Per-contract Position rows — behavioural test against a scratch SQLite DB.

Exercises _update_position_entry / _update_position_exit directly. No broker,
no network, no touching the real database.
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

u = User(email="t@t.com", hashed_password="x", name="T", role="user", account_size_usd=100000)
db.add(u); db.flush()
st = Strategy(user_id=u.id, name="S", strategy_type="momentum",
              params_json={"exit_before_close_minutes": 15}, max_positions=1)
db.add(st); db.flush(); db.commit()

om = OrderManager(db)
C1 = "SPY260825C00745000"
C2 = "SPY260826C00750000"

def mk_trade(side, qty, price):
    t = Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side=side, qty=qty,
              filled_qty=qty, price=price, status="executed", timestamp=datetime.utcnow())
    db.add(t); db.flush(); return t

def rows():
    return db.query(Position).order_by(Position.id).all()

print("1) Buy contract C1 (3 @ 2.00)")
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=3, price=2.00,
                          trade=mk_trade("buy", 3, 2.00), option_symbol=C1)
for p in rows(): print(f"   row {p.id}: {p.option_symbol}  qty={p.qty}  entry={p.avg_entry_price}")
assert len(rows()) == 1

print("\n2) Sell C1 (3 @ 2.50)")
om._update_position_exit(user=u, strategy=st, symbol="SPY", qty=3, price=2.50,
                         trade=mk_trade("sell", 3, 2.50), option_symbol=C1)
for p in rows(): print(f"   row {p.id}: {p.option_symbol}  qty={p.qty}")
assert rows()[0].qty == 0

print("\n3) Buy a DIFFERENT contract C2 (2 @ 3.00) — must NOT reuse C1's row")
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=2, price=3.00,
                          trade=mk_trade("buy", 2, 3.00), option_symbol=C2)
for p in rows(): print(f"   row {p.id}: {p.option_symbol}  qty={p.qty}  entry={p.avg_entry_price}")
assert len(rows()) == 2, "C2 should get its OWN row"
assert rows()[0].option_symbol == C1, "C1's row must still name C1"
assert rows()[0].qty == 0 and rows()[1].qty == 2

print("\n4) THE REGRESSION: C1's row still names C1 after C2 was bought")
print(f"   row 1 option_symbol = {rows()[0].option_symbol}   (old behaviour: would now read {C2})")
assert rows()[0].option_symbol == C1

print("\n5) Sell C2, then re-buy C1 — must REUSE C1's original row, not make a third")
om._update_position_exit(user=u, strategy=st, symbol="SPY", qty=2, price=3.20,
                         trade=mk_trade("sell", 2, 3.20), option_symbol=C2)
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=1, price=1.50,
                          trade=mk_trade("buy", 1, 1.50), option_symbol=C1)
for p in rows(): print(f"   row {p.id}: {p.option_symbol}  qty={p.qty}  entry={p.avg_entry_price}")
assert len(rows()) == 2, "re-entering C1 must reuse its row, not create a third"
assert rows()[0].qty == 1 and rows()[0].avg_entry_price == 1.50

print("\n6) Trade->contract attribution now resolvable via position_id")
for t in db.query(Trade).order_by(Trade.id).all():
    pos = db.query(Position).filter(Position.id == t.position_id).first()
    print(f"   trade {t.id} {t.side:<4} -> position {t.position_id} = {pos.option_symbol if pos else '?'}")
    assert pos is not None

print("\nALL ASSERTIONS PASSED")

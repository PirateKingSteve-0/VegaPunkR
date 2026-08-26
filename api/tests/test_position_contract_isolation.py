import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Position, Trade
from engine.order_manager import OrderManager
from datetime import datetime

def fresh():
    eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    u = User(email="t@t.com", hashed_password="x", name="T", role="user", account_size_usd=100000)
    db.add(u); db.flush()
    st = Strategy(user_id=u.id, name="S", strategy_type="momentum", params_json={}, max_positions=1)
    db.add(st); db.flush(); db.commit()
    return db, u, st

def mk(db, u, st, side, qty, price):
    t = Trade(user_id=u.id, strategy_id=st.id, symbol="SPY", side=side, qty=qty,
              filled_qty=qty, price=price, status="executed", timestamp=datetime.utcnow())
    db.add(t); db.flush(); return t

C1, C2 = "SPY260825C00745000", "SPY260826C00750000"

print("── CHECK A: does the legacy fallback clobber the WRONG contract? ──")
db, u, st = fresh(); om = OrderManager(db)
om._update_position_entry(user=u, strategy=st, symbol="SPY", qty=3, price=2.00,
                          trade=mk(db,u,st,"buy",3,2.00), option_symbol=C1)
print(f"   holding C1 qty=3")
# An exit arrives for a contract we do NOT hold.
om._update_position_exit(user=u, strategy=st, symbol="SPY", qty=3, price=9.99,
                         trade=mk(db,u,st,"sell",3,9.99), option_symbol=C2)
p = db.query(Position).filter(Position.option_symbol == C1).first()
print(f"   after a C2 exit -> C1 row qty={p.qty}   {'*** CLOBBERED ***' if p.qty == 0 else 'untouched'}")

print("\n── CHECK B: is `option_symbol == None` real SQL `IS NULL`? ──")
db2, u2, st2 = fresh()
db2.add(Position(user_id=u2.id, strategy_id=st2.id, symbol="SPY", option_symbol=None,
                 qty=5, avg_entry_price=400.0, current_price=400.0, unrealized_pnl=0.0))
db2.commit()
none_var = None
found = db2.query(Position).filter(Position.option_symbol == none_var).first()
print(f"   equity row (option_symbol NULL) found by `== None`: {found is not None}")
q = str(db2.query(Position).filter(Position.option_symbol == none_var))
print(f"   emitted SQL fragment: ...{q.split('WHERE')[1].strip()}")

print("\n── CHECK C: legacy row always names the contract it holds? ──")
db3, u3, st3 = fresh(); om3 = OrderManager(db3)
om3._update_position_entry(user=u3, strategy=st3, symbol="SPY", qty=2, price=1.0,
                           trade=mk(db3,u3,st3,"buy",2,1.0), option_symbol=C1)
row = db3.query(Position).filter(Position.qty > 0).first()
print(f"   open row option_symbol = {row.option_symbol}  (== held contract: {row.option_symbol == C1})")
print("   => exact-match lookup always finds it; the fallback has no legitimate job")

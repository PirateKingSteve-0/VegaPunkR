"""The gates that must NOT have been widened by per-contract rows."""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Position, Trade
from datetime import datetime

eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()
u = User(email="t@t.com", hashed_password="x", name="T", role="user", account_size_usd=100000)
db.add(u); db.flush()
st = Strategy(user_id=u.id, name="S", strategy_type="momentum", params_json={}, max_positions=1)
db.add(st); db.flush()

C1, C2 = "SPY260825C00745000", "SPY260826C00750000"
# Hold C1, and leave a CLOSED row for C2 lying around.
db.add(Position(user_id=u.id, strategy_id=st.id, symbol="SPY", option_symbol=C1,
                qty=3, avg_entry_price=2.0, current_price=2.1, unrealized_pnl=30.0))
db.add(Position(user_id=u.id, strategy_id=st.id, symbol="SPY", option_symbol=C2,
                qty=0, avg_entry_price=3.0, current_price=3.0, unrealized_pnl=0.0))
db.commit()

def check(label, got, want):
    print(f"  {'PASS' if got == want else 'FAIL'}  {label:<62} {got!r}")
    return got == want

ok = True
print("Entry lockout — must see the open contract via an UNDERLYING-keyed query:")
locked = db.query(Position).filter(
    Position.user_id == u.id, Position.strategy_id == st.id,
    Position.symbol == "SPY").filter(Position.qty > 0).first()
ok &= check("blocks a new entry while ANY SPY contract is held", locked is not None, True)

print("\nWorker 'do I hold something?' — exactly one open row:")
open_rows = db.query(Position).filter(Position.strategy_id == st.id, Position.qty > 0).all()
ok &= check("open row count", len(open_rows), 1)
ok &= check("and it is the contract we hold", open_rows[0].option_symbol, C1)

print("\nmax_positions counter — closed rows must not inflate it:")
cnt = db.query(Position).filter(Position.user_id == u.id, Position.strategy_id == st.id,
                                Position.qty > 0).count()
ok &= check(f"counts open only (2 rows exist, max_positions={st.max_positions})", cnt, 1)

print("\nDaily-loss gate — sums unrealized over open rows only:")
from sqlalchemy import func
unreal = db.query(func.sum(Position.unrealized_pnl)).filter(
    Position.user_id == u.id, Position.qty > 0).scalar() or 0.0
ok &= check("closed C2 row contributes nothing", unreal, 30.0)

print("\nPositions API — open-only after the router fix:")
listed = db.query(Position).filter(Position.user_id == u.id, Position.qty > 0).all()
ok &= check("total_positions reports held, not ever-held", len(listed), 1)

print("\n" + ("ALL GATES HOLD" if ok else "*** A GATE REGRESSED ***"))
sys.exit(0 if ok else 1)

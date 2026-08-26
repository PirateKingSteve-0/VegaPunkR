"""Direction selection (Phase 1), the opposite-side entry gate (Phase 2), and
the engine-guard findings C1-C4.

In-memory SQLite, no broker, no network. The gate assertions rely on the gate
returning BEFORE any broker call, so a blocked entry never needs a client.
"""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy, Position
from engine.order_manager import OrderManager
from engine.stream_driven_worker import StreamDrivenWorker
from engine.signal_generator import Signal, SignalGenerator, resolve_direction
import engine.signal_generator as sg
from datetime import datetime

# Freeze the clock mid-session. The entry-time gate (lower bound market open,
# upper bound the forced-exit time) runs before anything this file tests, so
# without this every signal assertion silently returns None outside market hours.
_FROZEN_ET = datetime(2026, 8, 25, 11, 0, 0)      # a Tuesday, 11:00 ET
sg._market_hours.get_current_et_time = lambda: _FROZEN_ET

_preview_calls = []


async def _stub_preview(self, *a, **kw):
    """Stand in for the Tradier preview so 'not blocked' cases prove they got
    past the gate without touching the network.

    Returns an aborting tuple rather than raising: execute_signal swallows every
    exception (a raise there is invisible), while close_position does not (a
    raise there kills the test). Returning ok=False aborts both cleanly, and the
    recorded call is the actual assertion.
    """
    _preview_calls.append(kw.get('option_symbol', a[5] if len(a) > 5 else None))
    return (False, None, "stubbed preview", None)


OrderManager._preview_or_abort = _stub_preview

# Far-future expiry ON PURPOSE. With a past-dated contract the drift
# check disarms on expiry before it reaches the side check, and the C3
# assertion below passes without testing anything.
CALL, PUT = "SPY271231C00745000", "SPY271231P00745000"
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def fresh():
    eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    u = User(email="t@t.com", hashed_password="x", name="T", role="user",
             account_size_usd=100000)
    db.add(u); db.flush()
    return db, u


# ------------------------------------------------------------ Phase 1
print("resolve_direction — single source of truth for which side we buy:")
for label, params, want in [
    ("no params defaults to call", {}, 'call'),
    ("explicit put", {'direction': 'put'}, 'put'),
    ("case/whitespace normalised", {'direction': ' PUT '}, 'put'),
    ("shipped template infers call", {'entry_signal': 'price_above_9ema_and_vwap'}, 'call'),
    ("'below' infers put", {'entry_signal': 'price_below_9ema_and_vwap'}, 'put'),
    ("explicit beats inferred", {'direction': 'call',
                                 'entry_signal': 'price_below_9ema_and_vwap'}, 'call'),
    ("garbage falls back to call", {'direction': 'xyz'}, 'call'),
]:
    check(label, resolve_direction(params), want)


def entry_signal_for(direction, price, entry_signal='price_above_9ema_and_vwap'):
    """Run check_entry_signal against a rising history with EMA+VWAP gating."""
    db, u = fresh()
    st = Strategy(user_id=u.id, name="s", strategy_type="momentum", max_positions=1,
                  params_json={'direction': direction, 'entry_signal': entry_signal,
                               'ema_period': 9, 'use_vwap': True})
    db.add(st); db.flush(); db.commit()
    gen = SignalGenerator()
    for i in range(30):                      # rising history -> EMA/VWAP below spot
        gen._update_history("SPY", 700.0 + i, 1_000_000)
    return gen.check_entry_signal(strategy=st, symbol="SPY", current_price=price,
                                  current_volume=1_000_000, user=u)


print("\nTHE BUG: a bearish strategy must not emit a sell as an ENTRY")
sig = entry_signal_for('put', 600.0, 'price_below_9ema_and_vwap')
check("bearish entry action is 'buy', not 'sell'", sig.action if sig else None, 'buy')
check("direction carried on the signal",
      (sig.indicators or {}).get('direction') if sig else None, 'put')

print("\nC1: direction drives the comparison, not the entry_signal wording")
# entry_signal says 'above' for BOTH; only `direction` differs. Price is far
# below the rising EMA/VWAP, i.e. a bearish setup.
check("call strategy does NOT fire on a bearish break",
      entry_signal_for('call', 600.0) is None, True)
check("put strategy DOES fire on the same bearish break",
      entry_signal_for('put', 600.0) is not None, True)
# ...and the mirror: price far above.
check("call strategy fires on a bullish break",
      entry_signal_for('call', 900.0) is not None, True)
check("put strategy does NOT fire on a bullish break",
      entry_signal_for('put', 900.0) is None, True)

# ------------------------------------------------------------ Phase 2
print("\nOpposite-side gate — never hold both sides of one underlying:")


def gate_msg(held_contract, my_direction, buying=CALL, signal_type='entry'):
    db, u = fresh()
    other = Strategy(user_id=u.id, name="other", strategy_type="momentum",
                     max_positions=1, params_json={})
    mine = Strategy(user_id=u.id, name="mine", strategy_type="momentum",
                    max_positions=1, params_json={'direction': my_direction})
    db.add_all([other, mine]); db.flush()
    db.add(Position(user_id=u.id, strategy_id=other.id, symbol="SPY",
                    option_symbol=held_contract, qty=3, avg_entry_price=2.0,
                    current_price=2.0, unrealized_pnl=0.0))
    db.commit()
    sig = Signal(signal_type=signal_type,
                 action='buy' if signal_type == 'entry' else 'sell',
                 symbol="SPY", confidence=1.0, reason="test", price=2.0)
    OrderManager._last_order_at.clear()   # class-level; would leak between cases
    r = asyncio.run(OrderManager(db).execute_signal(
        user=u, strategy=mine, signal=sig, qty=1, option_symbol=buying,
        estimated_price=2.0))
    return r.message or ""


BLOCK = "Refusing to hold both sides"
check("call entry blocked while another strategy holds a put",
      BLOCK in gate_msg(PUT, 'call', buying=CALL), True)
check("put entry blocked while another strategy holds a call",
      BLOCK in gate_msg(CALL, 'put', buying=PUT), True)
check("same-side pair NOT blocked (pre-existing behaviour preserved)",
      BLOCK in gate_msg(CALL, 'call', buying=CALL), False)

print("\nC2: the gate reads the CONTRACT being bought, not params")
# params say 'call' (so the old code would compare calls-vs-calls and pass),
# but the armed contract is a PUT and another strategy holds a CALL.
check("stale params can't sneak the opposite side past the gate",
      BLOCK in gate_msg(CALL, 'call', buying=PUT), True)
# Mirror: params say 'put' but we're actually buying a call, other holds a call.
check("...and it doesn't false-positive on a same-side buy",
      BLOCK in gate_msg(CALL, 'put', buying=CALL), False)

print("\nExits are never blocked (via close_position, the real exit path):")
db, u = fresh()
mine = Strategy(user_id=u.id, name="mine", strategy_type="momentum",
                max_positions=1, params_json={'direction': 'call'})
other = Strategy(user_id=u.id, name="other", strategy_type="momentum",
                 max_positions=1, params_json={'direction': 'put'})
db.add_all([mine, other]); db.flush()
db.add(Position(user_id=u.id, strategy_id=other.id, symbol="SPY", option_symbol=PUT,
                qty=3, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0))
held = Position(user_id=u.id, strategy_id=mine.id, symbol="SPY", option_symbol=CALL,
                qty=2, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0)
db.add(held); db.commit()
OrderManager._last_order_at.clear(); _preview_calls.clear()
asyncio.run(OrderManager(db).close_position(user=u, strategy=mine, position=held,
                                            reason="test exit", option_symbol=CALL))
check("close_position reaches the broker despite the opposite side being held",
      _preview_calls == [CALL], True)

# ------------------------------------------------------------ C3 / C4
print("\nC3: an armed contract on the wrong side must be disarmed")
disarmed = []


class _FakeState:
    option_symbol = CALL
    drift_checked_at = None
    delta = None
    open_interest = None


async def _c3():
    w = StreamDrivenWorker.__new__(StreamDrivenWorker)
    w._disarm_contract = lambda *a, **k: disarmed.append(True) or asyncio.sleep(0)
    st = Strategy(id=1, name="s", strategy_type="momentum",
                  params_json={'direction': 'put'})       # armed CALL, wants PUT
    await StreamDrivenWorker._check_contract_drift(w, st, 1, _FakeState(), None, None)

asyncio.run(_c3())
check("side mismatch disarms before any quote call", disarmed == [True], True)

print("\nC4/N1/N2: adoption is an EXIT-enabling path — filter ownership, not side")
db, u = fresh()
u2 = User(email="other@t.com", hashed_password="x", name="O", role="user",
          account_size_usd=100000)
db.add(u2); db.flush()
a = Strategy(user_id=u.id, name="calls", strategy_type="momentum",
             params_json={'direction': 'call'}, is_active=True)
b = Strategy(user_id=u.id, name="puts", strategy_type="momentum",
             params_json={'direction': 'put'}, is_active=True)
db.add_all([a, b]); db.flush()
db.add(Position(user_id=u.id, strategy_id=b.id, symbol="SPY", option_symbol=PUT,
                qty=3, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0))
db.commit()
broker = [{"symbol": PUT, "quantity": 3}, {"symbol": CALL, "quantity": 1},
          {"symbol": "SPY", "quantity": 100}, {"symbol": "SPYG271231C00050000", "quantity": 9}]

got, declined = StreamDrivenWorker._adoptable_broker_options(db, u.id, a.id, "SPY", broker)
check("skips the stock leg and the SPYG contract (root match, not prefix)",
      [p["symbol"] for p in got], [CALL])
check("...and reports the put as DECLINED, not absent", declined, 1)

# N2: a call strategy MUST still be able to adopt a live put it owns, otherwise
# flipping Direction orphans the open position at the broker with no exit path.
db2, u3 = fresh()
solo = Strategy(user_id=u3.id, name="flipped", strategy_type="momentum",
                params_json={'direction': 'put'}, is_active=True)
db2.add(solo); db2.commit()
got, declined = StreamDrivenWorker._adoptable_broker_options(
    db2, u3.id, solo.id, "SPY", [{"symbol": CALL, "quantity": 2}])
check("a put-direction strategy still adopts a live CALL it must exit",
      [p["symbol"] for p in got], [CALL])
check("nothing declined, so the caller will not zero the row", declined, 0)

# N1: OCC symbols are global. Another USER's row must not block our adoption.
db3, u4 = fresh()
u5 = User(email="b@t.com", hashed_password="x", name="B", role="user",
          account_size_usd=100000)
db3.add(u5); db3.flush()
mine3 = Strategy(user_id=u4.id, name="mine", strategy_type="momentum",
                 params_json={}, is_active=True)
theirs = Strategy(user_id=u5.id, name="theirs", strategy_type="momentum",
                  params_json={}, is_active=True)
db3.add_all([mine3, theirs]); db3.flush()
db3.add(Position(user_id=u5.id, strategy_id=theirs.id, symbol="SPY",
                 option_symbol=CALL, qty=3, avg_entry_price=2.0,
                 current_price=2.0, unrealized_pnl=0.0))
db3.commit()
got, declined = StreamDrivenWorker._adoptable_broker_options(
    db3, u4.id, mine3.id, "SPY", [{"symbol": CALL, "quantity": 3}])
check("another USER's row does not block adoption of our own position",
      [p["symbol"] for p in got], [CALL])

print("\nF2: staleness is the CONTRACT's expiry, never the owner's is_active flag")
EXPIRED_PUT = "SPY200101P00745000"          # Jan 2020 — cannot still be held


def gate_with(held_contract, owner_active):
    db, u = fresh()
    other = Strategy(user_id=u.id, name="other", strategy_type="momentum",
                     max_positions=1, params_json={}, is_active=owner_active)
    mine = Strategy(user_id=u.id, name="mine", strategy_type="momentum",
                    max_positions=1, params_json={'direction': 'call'}, is_active=True)
    db.add_all([other, mine]); db.flush()
    db.add(Position(user_id=u.id, strategy_id=other.id, symbol="SPY",
                    option_symbol=held_contract, qty=3, avg_entry_price=2.0,
                    current_price=2.0, unrealized_pnl=0.0))
    db.commit()
    sig = Signal(signal_type='entry', action='buy', symbol="SPY", confidence=1.0,
                 reason="t", price=2.0)
    OrderManager._last_order_at.clear()
    return (asyncio.run(OrderManager(db).execute_signal(
        user=u, strategy=mine, signal=sig, qty=1, option_symbol=CALL,
        estimated_price=2.0)).message or "")


check("a live opposite-side row blocks (owner active)",
      BLOCK in gate_with(PUT, True), True)
# strategy_executor auto-stops a strategy after 20 consecutive errors, which is
# exactly when a LIVE position has just lost its worker. It must still block.
check("...and STILL blocks when the owner was auto-deactivated",
      BLOCK in gate_with(PUT, False), True)
check("an EXPIRED contract cannot be held, so it does not block",
      BLOCK in gate_with(EXPIRED_PUT, True), False)

print("\nF3: adoption must NOT defer to a dead strategy's claim")
db4, u6 = fresh()
live = Strategy(user_id=u6.id, name="live", strategy_type="momentum",
                params_json={}, is_active=True)
dead = Strategy(user_id=u6.id, name="dead", strategy_type="momentum",
                params_json={}, is_active=False)
mine4 = Strategy(user_id=u6.id, name="mine", strategy_type="momentum",
                 params_json={}, is_active=True)
db4.add_all([live, dead, mine4]); db4.flush()
db4.add(Position(user_id=u6.id, strategy_id=live.id, symbol="SPY", option_symbol=CALL,
                 qty=1, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0))
db4.add(Position(user_id=u6.id, strategy_id=dead.id, symbol="SPY", option_symbol=PUT,
                 qty=1, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0))
db4.commit()
got, declined = StreamDrivenWorker._adoptable_broker_options(
    db4, u6.id, mine4.id, "SPY", [{"symbol": CALL, "quantity": 1},
                                  {"symbol": PUT, "quantity": 1}])
check("declines the ACTIVE strategy's contract",
      CALL not in [p["symbol"] for p in got], True)
check("but ADOPTS the dead strategy's, so it can still be exited",
      PUT in [p["symbol"] for p in got], True)
check("declined counts only the live claim", declined, 1)

print("\nF7: instruments are stored verbatim — casing must not orphan a position")
got, declined = StreamDrivenWorker._adoptable_broker_options(
    db4, u6.id, mine4.id, "spy", [{"symbol": PUT, "quantity": 1}])
check("lowercase underlying still matches the contract",
      [p["symbol"] for p in got], [PUT])

print("\nF5: an unparseable contract must fail CLOSED, not open")
msg = gate_msg(PUT, 'call', buying="NOT-AN-OCC-SYMBOL")
check("a non-empty unparseable option_symbol blocks the entry",
      "not a parseable OCC contract" in msg, True)

print("\nN4: an entry_signal with no direction word imposes no bound")
# 'ema_crossover' names the indicator but no bound. Before direction existed
# this imposed no price-vs-EMA constraint; it must still impose none.
check("bullish price passes", entry_signal_for('call', 900.0, 'ema_crossover') is not None, True)
check("bearish price ALSO passes (no bound, as before)",
      entry_signal_for('call', 600.0, 'ema_crossover') is not None, True)

print("\nG1/G2: a live contract must never be zeroed by adoption")


class _FakeClient:
    def __init__(self, positions): self._p = positions
    def get_positions(self): return self._p


class _State:
    option_symbol = None
    underlying_symbol = "SPY"


def run_startup_sync(broker_positions, rows, strategies):
    """rows: list of (strategy_key, occ, qty). strategies: {key: is_active}."""
    db, u = fresh()
    objs = {}
    for key, active in strategies.items():
        st = Strategy(user_id=u.id, name=key, strategy_type="momentum",
                      params_json={}, max_positions=1, is_active=active,
                      instruments=["SPY"])
        db.add(st); objs[key] = st
    db.flush()
    for key, occ, qty in rows:
        db.add(Position(user_id=u.id, strategy_id=objs[key].id, symbol="SPY",
                        option_symbol=occ, qty=qty, avg_entry_price=2.0,
                        current_price=2.0, unrealized_pnl=0.0))
    db.commit()
    w = StreamDrivenWorker.__new__(StreamDrivenWorker)
    w._tradier_client_for = lambda sid, d: _FakeClient(broker_positions)
    asyncio.run(StreamDrivenWorker._startup_sync(
        w, objs["mine"].id, "SPY", _State(), db))
    out = {}
    for key, st in objs.items():
        out[key] = sorted(
            (r.option_symbol, r.qty)
            for r in db.query(Position).filter(Position.strategy_id == st.id).all())
    return out


# G1: our own live CALL must survive, even though Tradier lists the PUT first
# and a dead strategy's claim now makes that PUT adoptable.
res = run_startup_sync(
    broker_positions=[{"symbol": PUT, "quantity": 1, "cost_basis": 200.0},
                      {"symbol": CALL, "quantity": 1, "cost_basis": 200.0}],
    rows=[("mine", CALL, 1), ("dead", PUT, 1)],
    strategies={"mine": True, "dead": False})
check("our live CALL row is NOT zeroed by broker response ordering",
      (CALL, 1) in res["mine"], True)

# G1b: a second contract the broker really holds is not silently zeroed.
res = run_startup_sync(
    broker_positions=[{"symbol": CALL, "quantity": 1, "cost_basis": 200.0},
                      {"symbol": PUT, "quantity": 1, "cost_basis": 200.0}],
    rows=[("mine", CALL, 1), ("mine", PUT, 1)],
    strategies={"mine": True})
check("both broker-held rows stay open (no silent orphan)",
      sorted(res["mine"]), sorted([(CALL, 1), (PUT, 1)]))

# G1c: a row the broker does NOT hold is still zeroed — the original purpose.
res = run_startup_sync(
    broker_positions=[{"symbol": CALL, "quantity": 1, "cost_basis": 200.0}],
    rows=[("mine", CALL, 1), ("mine", PUT, 1)],
    strategies={"mine": True})
check("a row the broker does not hold is still cleared", (PUT, 0) in res["mine"], True)

# G2: adopting from a dead claimant must clear that claimant's row, or the
# account-wide daily-loss gate counts one broker holding twice.
res = run_startup_sync(
    broker_positions=[{"symbol": PUT, "quantity": 1, "cost_basis": 200.0}],
    rows=[("dead", PUT, 1)],
    strategies={"mine": True, "dead": False})
check("we adopt the dead strategy's contract", (PUT, 1) in res["mine"], True)
check("...and its stale row is cleared, so P&L is not double-counted",
      res["dead"], [(PUT, 0)])

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S):\n  " + "\n  ".join(fails)))
sys.exit(1 if fails else 0)

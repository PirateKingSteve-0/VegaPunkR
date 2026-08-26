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

print("\nC4: adoption must not steal the other strategy's contract")
db, u = fresh()
a = Strategy(user_id=u.id, name="calls", strategy_type="momentum",
             params_json={'direction': 'call'})
b = Strategy(user_id=u.id, name="puts", strategy_type="momentum",
             params_json={'direction': 'put'})
db.add_all([a, b]); db.flush()
db.add(Position(user_id=u.id, strategy_id=b.id, symbol="SPY", option_symbol=PUT,
                qty=3, avg_entry_price=2.0, current_price=2.0, unrealized_pnl=0.0))
db.commit()
broker = [{"symbol": PUT, "quantity": 3}, {"symbol": CALL, "quantity": 1},
          {"symbol": "SPY", "quantity": 100}]
got = StreamDrivenWorker._adoptable_broker_options(db, a.id, "SPY", broker, 'call')
check("call strategy ignores the put and the stock",
      [p["symbol"] for p in got], [CALL])
got = StreamDrivenWorker._adoptable_broker_options(db, a.id, "SPY", broker, 'put')
check("and refuses a put already owned by another strategy",
      [p["symbol"] for p in got], [])

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S):\n  " + "\n  ".join(fails)))
sys.exit(1 if fails else 0)

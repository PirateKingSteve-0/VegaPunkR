"""Sizing mode B: start-of-day value for the percentage, cash left as the ceiling.

docs/sizing-basis-design-2026-09-29.md (owner-approved 2026-09-29). Before this,
sizing and every loss / drawdown cap read `user.account_size_usd`, which only the
dashboard updates. On 2026-09-28 it read $1,757.84 (saved while a put was open),
and on 2026-09-25 two strategy workers computed the "account-wide" cap from
different copies of it ($73.76 vs $77.53 in the same second).

Pinned here:
  1. Monday 2026-09-28 replay: 1 / 1 / 2 contracts; with only $300 left, trade 3 -> 1.
  2. EXITS ARE SACRED: a sell never reaches the cash-left cap.
  3. Buys in flight (reservations) come off cash left.
  4. Cash left can't fund one contract -> no preview, no order, ONE log event.
  5. Careful update: lower broker figure adopted only with no buy in flight; a big
     drop only when a second read confirms it; a higher figure never raises ours.
  6. New ET day -> refresh; a restart mid-day recomputes the same start-of-day value.
  7. Every worker sees ONE cap (the 09-25 case); unknown -> the old source.
  8. Call budget: 150 signals -> 1 balance call; a broker outage isn't retried per signal.
  9. Paper and live are separate accounts: a mode switch never carries sandbox
     figures into live (engine-guard H1).
 10. Implausible start-of-day equity (stale Position rows) is rejected.
 11. Fee allowance: cash sized to the last dollar buys one fewer, not zero.
 12. A REAL entry through execute_signal (in-memory SQLite): the preview and the
     order get the capped qty, and the fill comes off cash left.
 13. Late fill (backfill): subtracted only if cash was read before the order.
No network: the broker client and event logger are stubbed.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')  # noqa: E702

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import engine.account_state as acct
import engine.order_manager as om
from engine.order_manager import OrderManager
from engine.risk_manager import RiskManager
from engine.signal_generator import Signal
from models import Base, User, Strategy, Position

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<66} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


# --- stubs -----------------------------------------------------------------
DAY = {"key": "2026-09-28T04:00:00"}
acct._day_key = lambda now_utc=None: DAY["key"]
PNL = {"today": 0.0}
_real_today_pnl = acct._today_pnl
acct._today_pnl = lambda db, user_id: PNL["today"]
EVENTS = []
om.log_event = lambda **kw: EVENTS.append(kw)
LIVE = "live"


class FakeUser:
    def __init__(self, uid=1, stored=1757.84, mode=LIVE):
        self.id = uid
        self.account_size_usd = stored
        self.max_trade_percentage = 50.0
        self.selected_environment = "prod"
        self.selected_trading_mode = mode
        self.role = "admin"


class FakeStrategy:
    id = 4
    name = "SPY 0DTE Momentum (Puts)"
    trades_options = True
    params_json = {"risk_per_trade_pct": 50.0, "max_contracts": 3, "max_position_size_usd": None}


class FakeClient:
    def __init__(self, cash, equity=None, raises=False):
        self.cash, self.equity, self.raises = cash, (equity if equity is not None else cash), raises
        self.balance_calls = 0
        self.reads = None          # optional list of cash figures to return in turn

    def get_balances(self):
        self.balance_calls += 1
        if getattr(self, "on_read", None):
            self.on_read()                     # something happening while the read is in flight
        if self.raises:
            raise RuntimeError("broker down")
        cash = self.reads.pop(0) if self.reads else self.cash
        return {"total_equity": self.equity, "total_cash": cash, "cash": {"cash_available": cash}}


class FakeTradingClient:
    def __init__(self, clients):
        self.clients = clients if isinstance(clients, dict) else {LIVE: clients, "paper": clients}
        self.preview_calls, self.placed = 0, []

    def get_client(self, user):
        return self.clients[user.selected_trading_mode]

    async def preview_order(self, **kw):
        self.preview_calls += 1
        return None

    async def place_order(self, **kw):
        return None


def reset_classes():
    acct._reset_for_tests()
    for d in (OrderManager._pending_buy_reservations, OrderManager._settled_cash_cache,
              OrderManager._cash_block_state, OrderManager._last_order_at,
              OrderManager._unconfirmed_orders):
        d.clear()
    EVENTS.clear()


def fresh(cash, equity=None, raises=False):
    reset_classes()
    mgr = OrderManager.__new__(OrderManager)
    mgr.db = None
    client = FakeClient(cash, equity, raises)
    mgr.trading_client = FakeTradingClient(client)
    return mgr, client


def refresh(mgr, user):
    return asyncio.run(acct.ensure_fresh(user.id, acct.mode_of(user),
                                         lambda: mgr.trading_client.get_client(user), None))


def cap(mgr, user, qty, price):
    return asyncio.run(mgr._cap_qty_to_cash_left(user, "SPY", qty, "SPY260928P00770000", price))[0]


def sized(user, price):
    rm = RiskManager.__new__(RiskManager)
    return rm.calculate_position_size(user=user, strategy=FakeStrategy(), current_price=price)


print("1. Monday 2026-09-28 replay (mode B):")
user = FakeUser()
mgr, client = fresh(cash=1468.43)
refresh(mgr, user)
check("start-of-day base replaces the dashboard's $1,757.84", RiskManager._account_base(user), 1468.43)
q1 = cap(mgr, user, sized(user, 2.87), 2.87)
acct.record_buy_fill(user.id, LIVE, 287.0)
q2 = cap(mgr, user, sized(user, 6.30), 6.30)
acct.record_buy_fill(user.id, LIVE, 630.0)
q3 = cap(mgr, user, sized(user, 1.79), 1.79)
check("contracts 10:19 / 10:56 / 11:18 ET", (q1, q2, q3), (1, 1, 2))
check("cash left after two buys", round(acct.cash_left(user.id, LIVE), 2), 551.43)
mgr, _ = fresh(cash=300.0, equity=1468.43)
refresh(mgr, user)
check("only $300 left at trade 3 -> capped 2 -> 1", cap(mgr, user, 2, 1.79), 1)

print("\n2. EXITS ARE SACRED - a sell never reaches the cap:")
mgr, _ = fresh(cash=0.0, equity=1468.43)
refresh(mgr, user)
seen = []
real_cap = mgr._cap_qty_to_cash_left


async def spy_cap(*a, **k):
    seen.append(a)
    return await real_cap(*a, **k)
mgr._cap_qty_to_cash_left = spy_cap
asyncio.run(mgr.execute_signal(user, FakeStrategy(), Signal("exit", "sell", "SPY", 1.0, "t", price=1.50), 1,
                               option_symbol="SPY260928P00770000", estimated_price=1.50))
check("cap never consulted on a sell", seen, [])
check("sell with $0 cash left still reached the preview", mgr.trading_client.preview_calls, 1)

print("\n3. buys in flight come off cash left:")
mgr, _ = fresh(cash=551.43)
refresh(mgr, user)
OrderManager._acquire_buy_reservation(user.id, 300.0)
check("$551 - $300 reserved = $251 -> 1 contract at $1.79", cap(mgr, user, 2, 1.79), 1)

print("\n4. cash left can't fund one contract:")
mgr, _ = fresh(cash=150.0, equity=1468.43)
refresh(mgr, user).first_read_confirmed = True     # a vouched-for figure (see 14 for an unconfirmed one)
buy = Signal("manual", "buy", "SPY", 1.0, "t", price=751.0)   # 'manual' skips the DB lock-out query
for _ in range(20):
    r = asyncio.run(mgr.execute_signal(user, FakeStrategy(), buy, 2,
                                       option_symbol="SPY260928P00770000", estimated_price=1.79))
check("order refused", r.success, False)
check("message names cash left", "Insufficient cash left" in r.message, True)
check("no preview call", mgr.trading_client.preview_calls, 0)
check("one ENTRY_SKIPPED_NO_CASH event for 20 refusals", [e["event_type"] for e in EVENTS], ["ENTRY_SKIPPED_NO_CASH"])
check("rate limiter never stamped", OrderManager._last_order_at, {})
mgr, _ = fresh(cash=5000.0)
refresh(mgr, user)
check("no option mid -> underlying price NOT used, qty untouched", cap(mgr, user, 2, None), 2)

print("\n5. careful update of cash left:")
acct.POST_FILL_CHECK_SECONDS = 0.0
acct.CONFIRM_SECONDS = 0.0
in_flight = {"v": False}


def run_check(client):
    asyncio.run(acct._careful_check(user.id, LIVE, client, lambda: in_flight["v"], 0.0))


mgr, client = fresh(cash=551.43)
refresh(mgr, user)
client.reads = [548.10]
run_check(client)
check("small drop (fees) adopted on one read", acct.cash_left(user.id, LIVE), 548.10)
client.reads = [900.0]
run_check(client)
check("higher broker figure (lag) never raises ours", acct.cash_left(user.id, LIVE), 548.10)
client.reads = [100.0, 548.10]
run_check(client)
check("big drop NOT repeated on 2nd read -> ignored", acct.cash_left(user.id, LIVE), 548.10)
client.reads = [100.0, 102.0]
run_check(client)
check("big drop confirmed on 2nd read -> adopted", acct.cash_left(user.id, LIVE), 102.0)
mgr, client = fresh(cash=551.43)
refresh(mgr, user)
in_flight["v"] = True
client.reads = [300.0]
run_check(client)
check("another buy in flight -> broker figure not adopted", acct.cash_left(user.id, LIVE), 551.43)
in_flight["v"] = False
acct.record_buy_fill(user.id, LIVE, 10_000.0)
check("never below zero", acct.cash_left(user.id, LIVE), 0.0)

print("\n6. new ET day and restarts:")
mgr, client = fresh(cash=1468.43)
refresh(mgr, user)
DAY["key"] = "2026-09-29T04:00:00"
check("yesterday's entry is not today's", acct.get(user.id, LIVE), None)
refresh(mgr, user)
check("new day -> one more refresh", client.balance_calls, 2)
DAY["key"] = "2026-09-28T04:00:00"
mgr, _ = fresh(cash=551.07, equity=1613.07)      # restart 11:30 ET Monday, +$145 so far
PNL["today"] = 145.0
st = refresh(mgr, user)
PNL["today"] = 0.0
check("restart: cash left = broker's reduced figure", st.cash_left, 551.07)
check("restart: start-of-day recomputed (1613.07 - 145)", round(st.day_start_equity, 2), 1468.07)

print("\n7. one cap for every worker; unknown -> old source:")
mgr, _ = fresh(cash=1468.43)
refresh(mgr, FakeUser())
a, b = FakeUser(stored=1475.20), FakeUser(stored=1550.60)      # the 09-25 values
check("two stale copies, one base", (RiskManager._account_base(a), RiskManager._account_base(b)), (1468.43, 1468.43))
acct._reset_for_tests()
check("no entry today -> stored value, as before", RiskManager._account_base(b), 1550.60)

print("\n8. call budget:")
mgr, client = fresh(cash=1468.43)
for _ in range(150):
    refresh(mgr, user)
check("150 signals -> 1 balance call", client.balance_calls, 1)
mgr, client = fresh(cash=0.0, raises=True)
for _ in range(150):
    refresh(mgr, user)
check("broker down -> 1 attempt, not 150", client.balance_calls, 1)
check("broker down -> old source", RiskManager._account_base(user), 1757.84)
check("broker down -> cap leaves qty alone (post-preview gate still guards)", cap(mgr, user, 2, 1.79), 2)

print("\n9. paper and live are separate accounts (engine-guard H1):")
reset_classes()
mgr = OrderManager.__new__(OrderManager)
mgr.db = None
sandbox, live = FakeClient(100_000.0), FakeClient(1468.43)
mgr.trading_client = FakeTradingClient({"paper": sandbox, LIVE: live})
u = FakeUser(mode="paper")
refresh(mgr, u)
check("morning in paper: sandbox base", RiskManager._account_base(u), 100_000.0)
u.selected_trading_mode = LIVE                                   # switched at 11:00 ET
check("after switch to live: sandbox figure NOT used", acct.get(u.id, LIVE), None)
refresh(mgr, u)
check("live refresh reads the LIVE account", (RiskManager._account_base(u), live.balance_calls), (1468.43, 1))
check("live cap sized on live cash", cap(mgr, u, 3, 6.30), 2)

print("\n10. implausible start-of-day equity is rejected:")
mgr, _ = fresh(cash=1468.43, equity=1468.43)
PNL["today"] = -900.0                                            # stale rows: start looks $2,368
st = refresh(mgr, user)
check("> 50% from total equity -> unknown", st.day_start_equity, None)
check("-> sizing falls back to the stored value", RiskManager._account_base(user), 1757.84)
mgr, _ = fresh(cash=1468.43, equity=1468.43)
PNL["today"] = 1000.0                                            # start would be $468 < cash
check("below the settled cash just read -> unknown", refresh(mgr, user).day_start_equity, None)
PNL["today"] = 0.0

print("\n11. fee allowance:")
mgr, _ = fresh(cash=358.50)
refresh(mgr, user)
check("$358.50 at $1.79: 1 contract, not 2 then refused", cap(mgr, user, 2, 1.79), 1)

print("\n12. a real entry through execute_signal:")
reset_classes()
eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()
ru = User(email="t@t.com", hashed_password="x", name="T", role="admin", account_size_usd=1757.84,
          selected_trading_mode=LIVE, selected_environment="prod", max_trade_percentage=50.0)
db.add(ru); db.flush()
rs = Strategy(user_id=ru.id, name="s", strategy_type="momentum", max_positions=1,
              params_json={"direction": "put", "risk_per_trade_pct": 50.0, "max_contracts": 3})
db.add(rs); db.commit()
PREVIEWS, ORDERS = [], []


async def stub_preview(self, **kw):
    PREVIEWS.append(kw["qty"])
    return True, {"cost": kw["qty"] * 179.0}, "ok", None
OrderManager._preview_or_abort = stub_preview
real = OrderManager(db)
real.trading_client = FakeTradingClient(FakeClient(551.43, equity=1468.43))


async def place(**kw):
    ORDERS.append(kw["qty"])
    return {"order": {"id": 777}}
real.trading_client.place_order = place


async def filled(order_id, user):
    return {"status": "filled", "avg_fill_price": 1.79, "exec_quantity": ORDERS[-1]}
real._await_terminal_order = filled
asyncio.run(acct.ensure_fresh(ru.id, LIVE, lambda: real.trading_client.get_client(ru), db))
acct.record_buy_fill(ru.id, LIVE, 300.0)                         # cash left now $251.43
res = asyncio.run(real.execute_signal(ru, rs, Signal("entry", "buy", "SPY", 1.0, "t", price=751.0), 2,
                                      option_symbol="SPY260928P00766000", estimated_price=1.79))
check("preview received the capped qty (2 -> 1)", PREVIEWS, [1])
check("order placed with the capped qty", ORDERS, [1])
check("entry succeeded", res.success, True)
check("fill came off cash left ($251.43 - $179)", round(acct.cash_left(ru.id, LIVE), 2), 72.43)
check("real P&L query runs on the DB", _real_today_pnl(db, ru.id), 0.0)

print("\n13. late fill (backfill):")
reset_classes()
mgr, _ = fresh(cash=551.43)
refresh(mgr, user)
st = acct.get(user.id, LIVE)
check("order placed AFTER the cash read -> counts",
      acct.refreshed_before(user.id, LIVE, st.refreshed_at + timedelta(seconds=5)), True)
check("order placed BEFORE the cash read -> may be in it already",
      acct.refreshed_before(user.id, LIVE, st.refreshed_at - timedelta(seconds=5)), False)

print("\n14. a low FIRST read of the day is double-checked (owner, N1):")
mgr, client = fresh(cash=0.0, equity=1468.43)          # glitch: first read says $0
refresh(mgr, user)


async def low_first_read(second):
    client.reads = [second]
    q = await mgr._cap_qty_to_cash_left(user, "SPY", 2, "SPY260928P00770000", 1.79)
    await asyncio.sleep(0.05)                           # let the 0 s confirmation run
    return q[0]
acct.CONFIRM_SECONDS = 0.0
check("unconfirmed $0 first read -> qty left to the broker gate", asyncio.run(low_first_read(1468.43)), 2)
check("second read replaces the glitch", acct.cash_left(user.id, LIVE), 1468.43)
mgr, client = fresh(cash=0.0, equity=1468.43)
refresh(mgr, user)
asyncio.run(low_first_read(0.0))
check("second read agrees -> now trusted, cap blocks", cap(mgr, user, 2, 1.79), 0)
mgr, _ = fresh(cash=551.43, equity=1468.43)
refresh(mgr, user)
acct.record_buy_fill(user.id, LIVE, 500.0)
check("low only after our own fills -> trusted at once", cap(mgr, user, 2, 1.79), 0)

print("\n15. normal fill whose cash figure was read AFTER placement (N2):")
reset_classes()
db.query(Position).delete(); db.commit()               # section 12's position would lock out the entry
real.trading_client = FakeTradingClient(FakeClient(551.43, equity=1468.43))
real.trading_client.place_order = place
PREVIEWS.clear(); ORDERS.clear()
# The reviewer's scenario: the broker couldn't be read at order time (refresh in its
# 60 s cool-down, so the cap leaves qty alone) and comes back during the fill wait.
acct._FAILED_AT[(ru.id, LIVE)] = datetime.utcnow()


async def filled_after_refresh(order_id, user):
    # the day's first cash read lands while this order is still working
    acct._FAILED_AT.clear()
    await acct.ensure_fresh(ru.id, LIVE, lambda: real.trading_client.get_client(ru), db)
    return {"status": "filled", "avg_fill_price": 1.79, "exec_quantity": ORDERS[-1]}
real._await_terminal_order = filled_after_refresh
OrderManager._last_order_at.clear()
asyncio.run(real.execute_signal(ru, rs, Signal("entry", "buy", "SPY", 1.0, "t", price=751.0), 1,
                                option_symbol="SPY260928P00766000", estimated_price=1.79))
check("cost NOT subtracted a second time", acct.cash_left(ru.id, LIVE), 551.43)

print("\n16. paper/live switch during the fill wait (N3):")
reset_classes()
db.query(Position).delete(); db.commit()
live_c, paper_c = FakeClient(1468.43), FakeClient(100_000.0)
real.trading_client = FakeTradingClient({LIVE: live_c, "paper": paper_c})
real.trading_client.place_order = place
ru.selected_trading_mode = LIVE
asyncio.run(acct.ensure_fresh(ru.id, LIVE, lambda: live_c, db))
asyncio.run(acct.ensure_fresh(ru.id, "paper", lambda: paper_c, db))


async def filled_after_switch(order_id, user):
    user.selected_trading_mode = "paper"                  # switched while the order works
    return {"status": "filled", "avg_fill_price": 1.79, "exec_quantity": ORDERS[-1]}
real._await_terminal_order = filled_after_switch
OrderManager._last_order_at.clear()
asyncio.run(real.execute_signal(ru, rs, Signal("entry", "buy", "SPY", 1.0, "t", price=751.0), 1,
                                option_symbol="SPY260928P00766000", estimated_price=1.79))
check("cost came off the LIVE account it was placed on", round(acct.cash_left(ru.id, LIVE), 2), 1289.43)
check("paper account untouched", acct.cash_left(ru.id, "paper"), 100_000.0)
ru.selected_trading_mode = LIVE

print("\n17. glitchy first read, and the broker's gate lets a buy through meanwhile (review F1):")
acct.FILL_SETTLE_SECONDS = 0.0
mgr, client = fresh(cash=0.0, equity=2000.0)                     # first read glitches to $0
refresh(mgr, user)


async def f1():
    client.reads = [1600.0]                                        # the real figure after a $400 buy
    await mgr._cap_qty_to_cash_left(user, "SPY", 1, "SPY260928P00770000", 4.00)   # suspect -> re-check
    acct.record_buy_fill(user.id, LIVE, 400.0)                     # broker gate let A through
    q_b = (await mgr._cap_qty_to_cash_left(user, "SPY", 1, "SPY260928P00770000", 4.00))[0]
    await asyncio.sleep(0.05)
    return q_b
check("B during the re-check: still left to the broker gate", asyncio.run(f1()), 1)
check("clean second read replaces the pinned $0", acct.cash_left(user.id, LIVE), 1600.0)
check("and entries are sized normally again", cap(mgr, user, 3, 4.00), 3)

print("\n18. a fill lands WHILE the re-check read is in flight (review F2):")
mgr, client = fresh(cash=0.0, equity=2000.0)
refresh(mgr, user)
state = {"n": 0}


def fill_during_first_read():
    state["n"] += 1
    if state["n"] == 1:
        acct.record_buy_fill(user.id, LIVE, 300.0)


async def f2():
    client.reads = [1700.0, 1700.0]
    client.on_read = fill_during_first_read
    await mgr._cap_qty_to_cash_left(user, "SPY", 1, "SPY260928P00770000", 4.00)
    await asyncio.sleep(0.1)
check_state = asyncio.run(f2())
check("dirty read rejected, next attempt applied", (acct.cash_left(user.id, LIVE), client.balance_calls), (1700.0, 3))
check("confirmed after the clean read", acct.get(user.id, LIVE).first_read_confirmed, True)

if fails:
    print("\nFAIL test_sizing_cash_left")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("\nPASS test_sizing_cash_left")

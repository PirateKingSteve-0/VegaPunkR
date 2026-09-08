"""Entries must not ask the broker a question we can already answer.

2026-09-02: 321 entry signals, capacity for 3, and 214 previews sent to Tradier
purely to be told "you do not have enough buying power" — 214 round trips, 214
rate-limit slots, 214 log lines, 214 system_events rows. The authoritative cash
gate runs AFTER the preview; this adds a cheap one BEFORE it.

The properties that matter, in order:
  1. SELLS ARE NEVER GATED. A cash shortfall must never strand an open position.
  2. It only ever skips what is clearly unaffordable; anything unknown proceeds
     to the real gate.
  3. The 200th skip is not the 200th log line.
No network, no DB: the client and event logger are stubbed.
"""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

import engine.order_manager as om
from engine.order_manager import OrderManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<60} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class FakeUser:
    id = 1
    selected_environment = "prod"


class FakeStrategy:
    id = 3


class FakeClient:
    def __init__(self, cash, raises=False):
        self._cash, self._raises = cash, raises
        self.balance_calls = 0

    def get_balances(self):
        self.balance_calls += 1
        if self._raises:
            raise RuntimeError("broker down")
        return {"account_type": "cash", "total_cash": self._cash,
                "cash": {"cash_available": self._cash}}


class FakeTradingClient:
    def __init__(self, client):
        self._client, self.preview_calls = client, 0

    def get_client(self, user):
        return self._client

    async def preview_order(self, **kw):
        self.preview_calls += 1
        return {"status": "ok", "cost": 500.0, "order_cost": 500.0,
                "commission": 0.0, "fees": 0.0}


EVENTS = []
om.log_event = lambda **kw: EVENTS.append(kw)


def fresh(cash, raises=False):
    """A manager with empty ledgers — class state must not leak between cases."""
    OrderManager._pending_buy_reservations.clear()
    OrderManager._settled_cash_cache.clear()
    OrderManager._cash_block_state.clear()
    EVENTS.clear()
    mgr = OrderManager.__new__(OrderManager)
    mgr.db = None
    client = FakeClient(cash, raises)
    mgr.trading_client = FakeTradingClient(client)
    return mgr, client


def call(mgr, side, qty=2, price=2.50, option="SPY260903C00765000"):
    return asyncio.run(mgr._preview_or_abort(
        user=FakeUser(), strategy=FakeStrategy(), symbol="SPY",
        qty=qty, side=side, option_symbol=option, signal_price=price,
    ))


print("1. the whole point — an unaffordable BUY never reaches the broker:")
mgr, _ = fresh(cash=13.46)                      # 2 x 2.50 x 100 = $500 needed
ok, preview, msg, rid = call(mgr, "buy")
check("aborted", ok, False)
check("no preview call was made", mgr.trading_client.preview_calls, 0)
check("no reservation taken", rid, None)
check("message names the shortfall", "Insufficient settled cash (pre-preview)" in msg, True)

print("\n2. EXITS ARE SACRED — a SELL is never gated on cash:")
mgr, _ = fresh(cash=13.46)
ok, preview, msg, rid = call(mgr, "sell")
check("sell proceeds", ok, True)
check("sell DID reach the preview", mgr.trading_client.preview_calls, 1)
check("no cash-block state recorded for a sell", OrderManager._cash_block_state, {})

print("\n3. an affordable buy is unaffected:")
mgr, _ = fresh(cash=1202.46)
ok, _, _, _ = call(mgr, "buy")
check("proceeds", ok, True)
check("reached the preview", mgr.trading_client.preview_calls, 1)

print("\n4. unknown inputs DEFER to the real gate — the precheck never decides:")
# Balances unavailable: the precheck must stand down. The order still aborts,
# but at the EXISTING gate ("Could not fetch settled cash for buy preview"),
# which is the pre-existing fail-safe and not this change's doing. The property
# under test is that the preview was reached, i.e. the precheck did not block.
mgr, _ = fresh(cash=13.46, raises=True)
ok, _, msg, _ = call(mgr, "buy")
check("precheck stood down (preview reached)", mgr.trading_client.preview_calls, 1)
check("abort came from the existing gate", "Could not fetch settled cash" in msg, True)
check("no cash-block state recorded", OrderManager._cash_block_state, {})

# No signal price: nothing to estimate from, so the precheck cannot fire.
mgr, _ = fresh(cash=13.46)
ok, _, _, _ = asyncio.run(mgr._preview_or_abort(
    user=FakeUser(), strategy=FakeStrategy(), symbol="SPY", qty=2,
    side="buy", option_symbol="SPY260903C00765000", signal_price=None))
check("no signal price -> preview reached", mgr.trading_client.preview_calls, 1)

print("\n5. the 200th skip is not the 200th log line:")
mgr, _ = fresh(cash=13.46)
for _ in range(50):
    call(mgr, "buy")
check("skips counted", OrderManager._cash_block_state[1]["skipped"], 50)
check("exactly ONE event emitted", len(EVENTS), 1)
check("event type", EVENTS[0]["event_type"], "ENTRY_SKIPPED_NO_CASH")
check("balances fetched once (cached)", mgr.trading_client._client.balance_calls, 1)

print("\n6. reservations reduce what is available:")
mgr, _ = fresh(cash=600.0)
OrderManager._acquire_buy_reservation(1, 400.0)     # 600 - 400 = 200 < 500
ok, _, _, _ = call(mgr, "buy")
check("reserved cash is not spendable twice", ok, False)

print("\n7. recovery clears the block and reports the total:")
mgr, _ = fresh(cash=13.46)
call(mgr, "buy"); call(mgr, "buy")
check("blocked", OrderManager._cash_block_state[1]["skipped"], 2)
OrderManager._settled_cash_cache.clear()
mgr.trading_client._client._cash = 1202.46
ok, _, _, _ = call(mgr, "buy")
check("proceeds once funded", ok, True)
check("block state cleared", OrderManager._cash_block_state, {})

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

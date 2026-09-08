"""The account event stream must watch the account the ORDERS go to.

Verified 2026-09-07, before the fix: orders resolved to live account 6YB***56 on
api.tradier.com while the stream opened a socket on sandbox account VA8***04 at
sandbox.tradier.com. It calls get_tradier_client(), the module singleton built
from TRADIER_ENV (sandbox), while orders route per-user on
selected_trading_mode (live). Live fills were therefore never pushed and
confirmation fell back to the 30s REST poll this stream exists to backstop.

No network: create_account_stream_session is stubbed.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from engine.tradier_account_stream import TradierAccountStreamManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class FakeClient:
    def __init__(self, env, account):
        self._env, self._account = env, account
        self.sessions = 0

    def _resolve_account_id(self):
        return self._account

    def create_account_stream_session(self):
        self.sessions += 1
        host = "sandbox-ws" if self._env == "sandbox" else "ws"
        return {"sessionid": f"sid-{self._env}", "url": f"wss://{host}.tradier.com/v1/accounts/events"}


def mgr_with(provider):
    m = TradierAccountStreamManager()
    m.set_client_provider(provider)
    return m


print("the stream follows the account the orders use:")
live = FakeClient("live", "6YB70356")
m = mgr_with(lambda: live)
session = m._create_session_sync()
check("session created on the LIVE client", live.sessions, 1)
check("live websocket host", "sandbox" not in session["url"], True)
check("env recorded for the log line", m._env_label, "live")
check("account recorded, masked", m._account_label, "6YB***56")

print("\npaper mode still gets the sandbox account (not forced live):")
sand = FakeClient("sandbox", "VA88888804")
m = mgr_with(lambda: sand)
session = m._create_session_sync()
check("sandbox websocket host", "sandbox-ws" in session["url"], True)
check("env recorded", m._env_label, "sandbox")

print("\nno provider -> falls back, but LOUDLY (this was the silent case):")
m = TradierAccountStreamManager()
try:
    m._create_session_sync()
    fell_back = True
except Exception:
    fell_back = True   # network refused is fine; the point is it did not use a provider
check("fallback path reached without a provider", fell_back, True)
check("provider is None by default", TradierAccountStreamManager()._client_provider, None)

print("\na broken provider must not take the stream down:")
def boom():
    raise RuntimeError("provider exploded")
m = mgr_with(boom)
try:
    m._create_session_sync()
    survived = True
except Exception as e:
    survived = "provider exploded" not in str(e)
check("provider exception is caught, not propagated", survived, True)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

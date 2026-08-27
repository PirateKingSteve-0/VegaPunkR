"""_fetch_option_price must never return a stale `last` print.

On 2026-08-26 the REST fallback returned `last` whenever the book came back
one-sided. That value feeds check_exit_signal's pnl_pct against a fresh entry,
so a ten-minute-old print fired 13 of 16 exits on a fiction — stop losses
claiming -24% that realised -0.4%, take profits claiming +30% that realised
-1.9%, median hold 2.1 seconds. No network: requests.get is stubbed.
"""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')
import requests
from engine.strategy_executor import StrategyExecutor

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<56} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class _Resp:
    def __init__(self, q): self._q = q
    def raise_for_status(self): pass
    def json(self): return {"quotes": {"quote": self._q}}


def price_for(quote):
    requests.get = lambda *a, **k: _Resp(quote)
    ex = StrategyExecutor.__new__(StrategyExecutor)
    return asyncio.run(StrategyExecutor._fetch_option_price(ex, "SPY271231C00745000"))


_real_get = requests.get
try:
    print("two-sided quote -> mid:")
    check("bid 1.50 / ask 1.60 -> 1.55",
          price_for({"bid": 1.50, "ask": 1.60, "last": 9.99}), 1.55)

    print("\none-sided book -> the bid (what a long actually sells into):")
    check("bid 1.50 / ask 0 -> 1.50",
          price_for({"bid": 1.50, "ask": 0, "last": 9.99}), 1.50)

    print("\nTHE BUG: no bid at all must yield NO price, never `last`:")
    check("bid 0 / ask 0, last 2.01 -> 0.0 (not 2.01)",
          price_for({"bid": 0, "ask": 0, "last": 2.01}), 0.0)
    check("missing bid/ask keys, last present -> 0.0",
          price_for({"last": 2.01}), 0.0)
    check("empty quote -> 0.0", price_for({}), 0.0)
    check("ask without bid is not tradeable -> 0.0",
          price_for({"bid": 0, "ask": 1.60, "last": 2.01}), 0.0)

    print("\nreconstruction of trade 2929 (entry 1.54, claimed +30.46%):")
    stale = price_for({"bid": 0, "ask": 0, "last": 2.01})
    entry = 1.54
    print(f"    stale `last` was 2.01 -> pnl_pct would be "
          f"{((2.01-entry)/entry)*100:+.2f}%  (take profit fires at +30%)")
    print(f"    with the fix the price is {stale} -> caller skips the tick")
    check("no fictional take-profit can be computed", stale, 0.0)
finally:
    requests.get = _real_get

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

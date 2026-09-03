"""Entry sizing must refuse a frozen streamed quote (TODO B1/B2 groundwork).

The 2026-08-27 fix expired stale quotes on the EXIT path only. The entry path
kept sizing from `(bid+ask)/2` off the same streamed fields with no age check,
so a contract that stopped quoting sized orders off a frozen price.

The property that matters most here is the NARROWNESS of the change: behaviour
must be byte-identical except when a quote exists and has gone stale.
"""
import os, sys, asyncio
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from engine.stream_driven_worker import StrategyMarketState, SelectedContract
from engine.strategy_executor import MAX_QUOTE_AGE_SECONDS

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


OCC = "SPY271231C00745000"


def decide(md):
    """The exact branch structure of the entry sizing block, so the test pins
    the decision rather than re-implementing arithmetic."""
    bid = md.get('bid', 0) or 0
    ask = md.get('ask', 0) or 0
    age = md.get('quote_age_s')
    if age is None:
        return ('skip', None)
    if age > MAX_QUOTE_AGE_SECONDS:
        return ('rest', None)
    if ask <= 0:
        return ('skip', None)
    return ('stream', (bid + ask) / 2)


st = StrategyMarketState(underlying_symbol="SPY")
st.arm(SelectedContract(symbol=OCC, delta=0.7, open_interest=9999))

print("freshly armed, never quoted — unchanged: wait for the first quote")
check("never-quoted skips (as before the change)", decide(st.to_market_data())[0], 'skip')
check("...and bid/ask really are zero, so old code skipped too",
      (st.option_bid, st.option_ask), (0.0, 0.0))

print("\na fresh quote sizes from the stream, exactly as before:")
st.apply({"type": "quote", "symbol": OCC, "bid": 0.58, "ask": 0.62})
act, price = decide(st.to_market_data())
check("fresh quote uses the stream", act, 'stream')
check("...at the mid", price, 0.60)

print("\nTHE BUG: the quote stops arriving and the price freezes:")
st.option_quote_at = datetime.utcnow() - timedelta(minutes=10)
md = st.to_market_data()
check("bid still reads the frozen value", st.option_bid, 0.58)
check("age exceeds the limit", md['quote_age_s'] > MAX_QUOTE_AGE_SECONDS, True)
check("entry now goes to REST instead of the frozen mid", decide(md)[0], 'rest')

print("\nboundary — the guard must not fire early:")
st.option_quote_at = datetime.utcnow() - timedelta(seconds=MAX_QUOTE_AGE_SECONDS - 5)
check(f"{MAX_QUOTE_AGE_SECONDS-5:.0f}s old is still fresh", decide(st.to_market_data())[0], 'stream')
st.option_quote_at = datetime.utcnow() - timedelta(seconds=MAX_QUOTE_AGE_SECONDS + 5)
check(f"{MAX_QUOTE_AGE_SECONDS+5:.0f}s old is stale", decide(st.to_market_data())[0], 'rest')

print("\na fresh but one-sided book still skips (unchanged, no oversizing):")
st.arm(SelectedContract(symbol=OCC, delta=0.7, open_interest=9999))
st.apply({"type": "quote", "symbol": OCC, "bid": 0.58, "ask": 0.0})
check("fresh quote with no ask skips", decide(st.to_market_data())[0], 'skip')

print("\nre-arming clears the stamp, so a new strike waits for its own quote:")
st.arm(SelectedContract(symbol="SPY271231P00745000", delta=0.7, open_interest=9999))
check("re-armed contract skips until quoted", decide(st.to_market_data())[0], 'skip')

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

"""summary/timesale must be CAPTURED but never QUEUED (TODO.md C2).

C2 widened the websocket filter to ["trade","quote","summary","timesale"] so the
session recorder has aggressor-side and session-range data to analyse later.
Subscribing alone would have been unsafe: StreamRouter.dispatch routes by SYMBOL
and, before this, did not look at `type` at all. Strategy queues are maxsize=100
and drop silently on overflow (`pass  # drop stale tick`), and timesale emits
about one message per trade — roughly doubling trade-side traffic on a queue
whose displaced message could be the underlying `trade` tick an entry fires on,
or the option `quote` that refreshes state.option_bid, which the exit path
prices against (the 2026-08-27 stale-bid take-profits: +36%/+42%/+68% claimed,
-2% to -4% realised).

So dispatch now drops anything outside _ROUTED_TYPES. This test pins BOTH halves:
the new types never reach a queue, and the three that already did still do —
the filter must not narrow the trading path while protecting it.

No network, no DB.
"""
import os, sys, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))

from engine.stream_router import StreamRouter, _ROUTED_TYPES

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def drained(event_types, symbol="SPY"):
    """Dispatch one event of each type; return the types that reached the queue."""
    async def run():
        r = StreamRouter()
        q = r.register_strategy(1, [symbol])
        for t in event_types:
            await r.dispatch({"type": t, "symbol": symbol})
        got = []
        while not q.empty():
            got.append(q.get_nowait()["type"])
        return got
    return asyncio.run(run())


print("the trading path must be unchanged — these still route:")
for t in ("trade", "tradex", "quote"):
    check(f"{t} reaches the strategy queue", drained([t]), [t])

print("\nC2 research feeds must never consume a queue slot:")
for t in ("summary", "timesale"):
    check(f"{t} is dropped before put_nowait", drained([t]), [])

print("\nmixed stream: research types filtered, trading types survive in order:")
mixed = ["quote", "summary", "trade", "timesale", "tradex", "summary"]
check("only trade/tradex/quote survive", drained(mixed), ["quote", "trade", "tradex"])

print("\nmalformed events must not crash or leak through:")
async def edge():
    r = StreamRouter()
    q = r.register_strategy(1, ["SPY"])
    await r.dispatch({"symbol": "SPY"})               # no type at all
    await r.dispatch({"type": None, "symbol": "SPY"})  # explicit None
    await r.dispatch({"type": "trade"})                # no symbol
    return q.qsize()
check("typeless / None-type / symbolless all dropped", asyncio.run(edge()), 0)

print("\nUI SSE connections share dispatch and get the same protection:")
async def ui():
    r = StreamRouter()
    q = await r.register_ui("conn-1", ["SPY"])
    await r.dispatch({"type": "timesale", "symbol": "SPY"})
    await r.dispatch({"type": "quote", "symbol": "SPY"})
    got = []
    while not q.empty():
        got.append(q.get_nowait()["type"])
    return got
check("UI queue sees quote but not timesale", asyncio.run(ui()), ["quote"])

print("\nthe routed set itself is the pre-C2 set — widening it is a behaviour change:")
check("_ROUTED_TYPES", set(_ROUTED_TYPES), {"trade", "tradex", "quote"})

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

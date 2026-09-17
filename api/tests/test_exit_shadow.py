"""Exit shadow mode must OBSERVE exits and never influence them.

engine/exit_shadow.py watches five alternative exit rules on live positions and
records when each would have sold (docs/dynamic-exits-math.md §7). Two kinds of
guarantee are pinned here:

  A. SAFETY — it cannot touch the exit path: it places nothing, writes nothing,
     never raises into the caller, and the executor reports a real exit to it
     only after the close has succeeded.
  B. CORRECTNESS — each rule fires at the price and for the reason its
     definition says, using the same definitions as
     scripts/dynamic_exits_review.py so live and offline results compare.

No network, no DB: positions are plain objects, the clock is injected.
"""
import math
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')  # noqa: E702

import engine.exit_shadow as xs

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<70} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class Pos:
    def __init__(self, pid=1, entry=2.00, qty=1, opened=None, sym="SPY260917P00750000"):
        self.id, self.avg_entry_price, self.qty = pid, entry, qty
        self.option_symbol = sym
        self.opened_at = opened or T0


T0 = datetime(2026, 9, 17, 14, 0, 0)
PARAMS = dict(stop_loss_pct=15, trailing_stop_activation=15, trailing_stop_distance=10)
# 30 one-minute changes alternating +0.10 / -0.10: stdev exactly 0.10, so
# sigma30 = 0.10 * sqrt(30) = 0.5477 and sigma10 = 0.10 * sqrt(10) = 0.3162.
CLOSES = [700.0 + (0.1 if i % 2 else 0.0) for i in range(31)]


def feed(pos, prices, delta=0.5, closes=CLOSES, start=T0 + timedelta(seconds=1)):
    for i, px in enumerate(prices):
        xs.observe(pos, px, closes, PARAMS, delta=delta, now=start + timedelta(seconds=i))


def state(pid=1):
    return xs._STATE.get(pid)


# ---------------------------------------------------------------------------
print("\nA1. the module contains nothing that can act:")
src = open("api/engine/exit_shadow.py").read()
code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
code = re.sub(r'"""[\s\S]*?"""', "", code)   # docstrings describe what it must NOT do
for forbidden in ("place_order", "close_position", "execute_signal", "preview",
                  ".commit(", ".query(", "db.", "session", "requests", "httpx"):
    check(f"no `{forbidden}` in exit_shadow code", forbidden in code, False)

print("\nA2. observe() and on_exit() never raise, whatever they are handed:")
xs._reset_for_tests()
for label, args in [
    ("position None", (None, 2.0, CLOSES, PARAMS)),
    ("price None", (Pos(), None, CLOSES, PARAMS)),
    ("price 0", (Pos(), 0.0, CLOSES, PARAMS)),
    ("closes None", (Pos(pid=9), 2.0, None, PARAMS)),
    ("params None", (Pos(pid=8), 2.0, CLOSES, None)),
    ("entry 0", (Pos(pid=7, entry=0.0), 2.0, CLOSES, PARAMS)),
]:
    try:
        xs.observe(*args, delta=None)
        ok = True
    except Exception:
        ok = False
    check(f"observe with {label} does not raise", ok, True)

real = xs._observe
xs._observe = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    xs.observe(Pos(pid=5), 2.0, CLOSES, PARAMS)
    swallowed = True
except Exception:
    swallowed = False
xs._observe = real
check("an internal crash is swallowed, not propagated", swallowed, True)
check("on_exit for a position shadow never saw returns None", xs.on_exit(Pos(pid=404), 2.1, "x"), None)

print("\nA3. the executor wiring — observe before the decision, on_exit only after success:")
ex = open("api/engine/strategy_executor.py").read()
i_obs = ex.find("exit_shadow.observe(")
i_dec = ex.find("exit_signal = self.signal_generator.check_exit_signal(")
check("observe is called", i_obs > 0, True)
check("observe comes BEFORE the real exit decision", 0 < i_obs < i_dec, True)
obs_call = ex[i_obs:ex.find(")", ex.find("else None)", i_obs)) + 1]
check("observe is not handed the exit decision", "exit_signal" in obs_call, False)
lines = ex.splitlines()
on_exits = [i for i, l in enumerate(lines) if "exit_shadow.on_exit(" in l]
check("on_exit is called from exactly two places", len(on_exits), 2)


def enclosing_block(i):
    """The nearest less-indented line above line i — the block that owns it."""
    ind = len(lines[i]) - len(lines[i].lstrip())
    for j in range(i - 1, -1, -1):
        t = lines[j]
        if t.strip() and not t.strip().startswith("#") and len(t) - len(t.lstrip()) < ind:
            return t.strip()
    return ""


for n, i in enumerate(on_exits, 1):
    owner = enclosing_block(i)
    check(f"on_exit #{n} (line {i + 1}) is owned by a success branch",
          owner in ("if order_result.success:", "if close_result.success:"), True)
check("shadow's return value is never used", bool(re.search(r"=\s*exit_shadow\.", ex)), False)

# ---------------------------------------------------------------------------
print("\nB1. snapshot at entry:")
xs._reset_for_tests()
p = Pos()
feed(p, [2.00])
st = state()
check("sigma30 from 1-minute closes", round(st["sigma30"], 4), round(0.1 * math.sqrt(30), 4))
check("dynamic target = entry + 2 * delta * sigma30", round(st["target"], 4),
      round(2.00 + 2 * 0.5 * 0.1 * math.sqrt(30), 4))
check("delta recorded as known", st["delta_known"], True)
check("a snapshot 1s after opening is not late", st["late"], False)
check("stop / arm / trail read from the strategy's params", (st["stop_pct"], st["arm_pct"], st["trail_pct"]),
      (15.0, 15.0, 10.0))

xs._reset_for_tests()
feed(Pos(opened=T0 - timedelta(minutes=20)), [2.00])
check("a snapshot 20 minutes after opening IS late (restart mid-trade)", state()["late"], True)

xs._reset_for_tests()
feed(Pos(), [2.00], delta=None)
check("no delta -> default used and flagged unknown", (state()["delta"], state()["delta_known"]),
      (xs.DEFAULT_DELTA, False))

print("\nB2. nothing fires before the trail arms, on dips above the stop:")
xs._reset_for_tests()
feed(Pos(), [2.00, 1.80, 2.20, 1.75, 2.10])      # never reaches +15% (2.30), never -15% (1.70)
check("no rule has sold", state()["exits"], {})
check("trail not armed", state()["armed"], False)

print("\nB3. the stop loss closes every rule still open, at the same price:")
xs._reset_for_tests()
feed(Pos(), [2.00, 1.90, 1.69])
st = state()
check("all five rules recorded", sorted(st["exits"]), sorted(xs.RULES))
check("all by stop", {e["reason"] for e in st["exits"].values()}, {"stop"})
check("all at 1.69", {e["price"] for e in st["exits"].values()}, {1.69})

print("\nB4. keep-a-share-of-the-gain trails:")
xs._reset_for_tests()
# arms at 2.40 (+20%): keep70 level 2.00 + 0.7*0.40 = 2.28, keep50 level 2.20
feed(Pos(), [2.00, 2.20, 2.40, 2.30, 2.27, 2.21, 2.19])
st = state()
check("keep70 sells at the first price <= 2.28", st["exits"]["keep70"]["price"], 2.27)
check("keep50 sells at the first price <= 2.20", st["exits"]["keep50"]["price"], 2.19)
check("keep70 P&L is +$27 on one contract", st["exits"]["keep70"]["pnl_usd"], 27.0)

print("\nB5. the volatility trail uses delta and sigma10:")
xs._reset_for_tests()
# peak 2.40, level = 2.40 - 0.5 * 0.5 * 0.3162 = 2.3209
feed(Pos(), [2.00, 2.40, 2.33, 2.32])
check("vol_trail sells at the first price <= 2.3209", state()["exits"]["vol_trail"]["price"], 2.32)

print("\nB6. dynamic take profit, alone and with the trail underneath it:")
xs._reset_for_tests()
tgt = 2.00 + 2 * 0.5 * 0.1 * math.sqrt(30)          # 2.5477
feed(Pos(), [2.00, 2.30, 2.55])
st = state()
check("dyn_tp sells at the target", (st["exits"]["dyn_tp"]["price"], st["exits"]["dyn_tp"]["reason"]),
      (2.55, "target"))
check("dyn_tp_trail also takes the target when it comes first",
      st["exits"]["dyn_tp_trail"]["reason"], "target")

xs._reset_for_tests()
# arms at 2.40 but never reaches 2.5477; trail at 10% of peak = 2.16
feed(Pos(), [2.00, 2.40, 2.20, 2.15])
st = state()
check("dyn_tp alone keeps holding (no trail)", "dyn_tp" in st["exits"], False)
check("dyn_tp_trail sells on the trail at 2.15", (st["exits"]["dyn_tp_trail"]["price"],
      st["exits"]["dyn_tp_trail"]["reason"]), (2.15, "trail"))

xs._reset_for_tests()
feed(Pos(), [2.00, 2.40, 2.20], closes=[700.0] * 5)  # too few bars for a sigma
st = state()
check("no sigma -> no dynamic target", st["target"], None)
check("no sigma -> dyn_tp and vol_trail cannot fire", ("dyn_tp" in st["exits"], "vol_trail" in st["exits"]),
      (False, False))

print("\nB7. a rule records once — its FIRST sell, not a later one:")
xs._reset_for_tests()
feed(Pos(), [2.00, 2.40, 2.27, 2.10, 2.35, 2.05])
check("keep70 keeps its first price", state()["exits"]["keep70"]["price"], 2.27)

print("\nB8. on_exit summarises, marks still-holding rules open, and forgets:")
xs._reset_for_tests()
p = Pos(qty=2)
feed(p, [2.00, 2.40, 2.27])                      # keep70 sold; dyn_tp still open
rec = xs.on_exit(p, 2.31, "Trailing stop hit", now=T0 + timedelta(minutes=5))
check("real P&L at the real quantity", rec["real"]["pnl_usd"], 62.0)
check("keep70 reported sold", rec["rules"]["keep70"]["status"], "sold")
check("dyn_tp reported OPEN, not flat", rec["rules"]["dyn_tp"]["status"], "open")
check("open rules carry last price and peak", (rec["rules"]["dyn_tp"]["last"], rec["rules"]["dyn_tp"]["peak"]),
      (2.27, 2.40))
check("state cleared after the real exit", state(), None)
check("a second on_exit for the same position is a no-op", xs.on_exit(p, 2.31, "again"), None)

xs._reset_for_tests()
feed(Pos(pid=77), [2.00], start=T0 - timedelta(days=2))
feed(Pos(pid=78), [2.00])
xs.on_exit(Pos(pid=78), 2.0, "x", now=T0 + timedelta(minutes=1))
check("positions never closed through shadow are pruned after a day", 77 in xs._STATE, False)

print("\nC1. note_underlying builds 1-minute OHLC bars, prunes, and never raises:")
xs._reset_for_tests()
m0 = datetime(2026, 9, 17, 14, 0, 0)
for sec, px in [(1, 700.0), (20, 700.4), (40, 699.8), (59, 700.1)]:
    xs.note_underlying("SPY", px, now=m0 + timedelta(seconds=sec))
check("one bar: open/high/low/close", xs._BARS["SPY"][m0], [700.0, 700.4, 699.8, 700.1])
for i in range(xs.MAX_BARS + 10):
    xs.note_underlying("QQQ", 500.0, now=m0 + timedelta(minutes=i))
check("bars pruned to MAX_BARS", len(xs._BARS["QQQ"]), xs.MAX_BARS)
check("pruning keeps the newest bar", max(xs._BARS["QQQ"]) == m0 + timedelta(minutes=xs.MAX_BARS + 9), True)
for label, args in [("symbol None", (None, 700.0)), ("price None", ("SPY", None)),
                    ("price text", ("SPY", "abc")), ("price 0", ("SPY", 0))]:
    try:
        xs.note_underlying(*args, now=m0)
        ok = True
    except Exception:
        ok = False
    check(f"note_underlying with {label} does not raise", ok, True)

BUF = 0.25 * 0.1 * math.sqrt(10)        # 0.25 x sigma10 with CLOSES -> 0.0791


def bars(symbol, start, prices):
    """One flat bar per minute (open = high = low = close)."""
    for i, px in enumerate(prices):
        xs.note_underlying(symbol, px, now=start + timedelta(minutes=i, seconds=30))


def tick(pos, minute, price, sym="SPY"):
    xs.observe(pos, price, CLOSES, PARAMS, delta=0.5, underlying=sym,
               now=m0 + timedelta(minutes=minute, seconds=10))


print("\nC2. PUT: a swing HIGH sets the stop above it; a bar CLOSING above the stop fires:")
xs._reset_for_tests()
put = Pos(pid=31, sym="SPY260917P00700000", opened=m0)
bars("SPY", m0, [700.0, 700.2, 700.5, 700.3, 700.1, 700.4, 700.7])
#                 14:00  14:01  14:02   14:03  14:04  14:05  14:06
tick(put, 5, 1.95)            # 14:00-14:04 complete -> swing high 14:02 confirmed
st = state(31)
check("stop = swing high 700.50 + buffer", round(st["struct_stop"], 4), round(700.5 + BUF, 4))
tick(put, 6, 1.95)            # 14:05 closes 700.40, below the stop -> nothing
check("a close below the stop does not fire", "structure" in st["exits"], False)
tick(put, 7, 1.90)            # 14:06 closes 700.70, above 700.579 -> fire at this tick
check("fires on the next tick after the close", (st["exits"]["structure"]["price"],
      st["exits"]["structure"]["reason"]), (1.90, "structure"))
check("no other rule fired", sorted(st["exits"]), ["structure"])

print("\nC3. CALL: the mirror image, a swing LOW and a close BELOW:")
xs._reset_for_tests()
call = Pos(pid=32, sym="SPY260917C00700000", opened=m0)
bars("SPY", m0, [700.0, 699.8, 699.5, 699.7, 699.9, 699.6, 699.3])
tick(call, 5, 1.95)
st = state(32)
check("stop = swing low 699.50 - buffer", round(st["struct_stop"], 4), round(699.5 - BUF, 4))
tick(call, 6, 1.95)           # 699.60 close, above the stop
check("a close above a call's stop does not fire", "structure" in st["exits"], False)
tick(call, 7, 1.92)           # 699.30 close, below 699.42
check("a close below it fires", st["exits"]["structure"]["price"], 1.92)

print("\nC4. the stop only moves in the trade's favour:")
xs._reset_for_tests()
put = Pos(pid=33, sym="SPY260917P00700000", opened=m0)
#                 00     01     02     03     04     05     06     07     08     09     10
bars("SPY", m0, [700.0, 700.2, 700.5, 700.3, 700.1, 700.0, 699.9, 700.25, 699.8, 699.7, 699.6])
tick(put, 5, 1.95)
first = state(33)["struct_stop"]
tick(put, 11, 1.95)           # 14:07 is a LOWER swing high (700.25): stop moves DOWN
st = state(33)
check("a lower swing high moves a put's stop down", round(st["struct_stop"], 4), round(700.25 + BUF, 4))
check("it is lower than the first stop", st["struct_stop"] < first, True)
xs._reset_for_tests()
put = Pos(pid=35, sym="SPY260917P00700000", opened=m0)
bars("SPY", m0, [700.0, 700.2, 700.3, 700.2, 700.1, 700.0, 700.1])   # 14:02 swing 700.30
tick(put, 5, 1.95)
low_stop = state(35)["struct_stop"]                                   # 700.379
# 14:07: a HIGHER swing high (spike to 700.45) whose bar CLOSES back below the stop, so it
# can form a swing without firing. Neighbours 14:05-14:09 all stay below 700.379.
t7 = m0 + timedelta(minutes=7)
for sec, px in [(5, 700.20), (30, 700.45), (55, 700.20)]:
    xs.note_underlying("SPY", px, now=t7 + timedelta(seconds=sec))
bars("SPY", m0 + timedelta(minutes=8), [700.1, 700.0])
tick(put, 10, 1.95)                                                   # 14:07-14:09 complete
st = state(35)
check("the higher swing did not fire the rule (closed below the stop)", "structure" in st["exits"], False)
check("a higher swing never loosens a put's stop", st["struct_stop"], low_stop)

print("\nC5. swings from BEFORE the entry minute are ignored:")
xs._reset_for_tests()
late_put = Pos(pid=36, sym="SPY260917P00700000", opened=m0 + timedelta(minutes=3))
bars("SPY", m0, [700.0, 700.2, 700.5, 700.3, 700.1, 700.0])
tick(late_put, 6, 1.95)
check("the 14:02 swing does not set a stop for a 14:03 entry", state(36)["struct_stop"], None)

print("\nC6. no underlying -> the structure stop stays silent, the floor still works:")
xs._reset_for_tests()
put = Pos(pid=37, sym="SPY260917P00700000", opened=m0)
bars("SPY", m0, [700.0, 700.2, 700.5, 700.3, 700.1, 700.4, 700.7])
for minute in (5, 6, 7):
    xs.observe(put, 1.95, CLOSES, PARAMS, delta=0.5, now=m0 + timedelta(minutes=minute, seconds=10))
check("no stop without an underlying", state(37)["struct_stop"], None)
xs.observe(put, 1.60, CLOSES, PARAMS, delta=0.5, now=m0 + timedelta(minutes=8))
check("the 15% floor still records it", state(37)["exits"]["structure"]["reason"], "stop")

print("\nC7. the live trail still runs alongside the structure stop:")
xs._reset_for_tests()
put = Pos(pid=38, sym="SPY260917P00700000", opened=m0)
bars("SPY", m0, [700.0, 700.0, 700.0])
tick(put, 1, 2.40)            # +20%, armed
tick(put, 2, 2.15)            # below 10% of peak (2.16)
check("structure records the trail exit", (state(38)["exits"]["structure"]["price"],
      state(38)["exits"]["structure"]["reason"]), (2.15, "trail"))

print("\nC8. executor wiring for the structure stop:")
check("note_underlying is fed on every tick, beside _update_history",
      "exit_shadow.note_underlying(symbol, current_price)" in ex
      and ex.find("exit_shadow.note_underlying(") > ex.find("self.signal_generator._update_history("), True)
check("observe is told the underlying", "underlying=symbol," in ex[i_obs:i_dec], True)
check("structure is a watched rule", "structure" in xs.RULES, True)

print("\nB9. ENABLED = False turns everything off:")
xs._reset_for_tests()
xs.ENABLED = False
feed(Pos(), [2.00, 1.60])
check("no state recorded while disabled", xs._STATE, {})
check("on_exit returns None while disabled", xs.on_exit(Pos(), 1.6, "x"), None)
xs.ENABLED = True

print()
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")

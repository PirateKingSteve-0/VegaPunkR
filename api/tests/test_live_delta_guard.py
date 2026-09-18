"""The long-shot guard must judge contracts by their REAL delta (TODO.md G5).

The broker's delta refreshes about hourly and is last night's at the open.
2026-09-17 it said 0.727 for a put whose real delta was 0.13-0.27, and the
engine bought three. engine/live_greeks.py computes delta from live prices;
SignalGenerator.check_entry_signal step 4b uses it to catch contracts that are
really below the delta floor ("long shots").

Pinned here:
  1. the maths — prices, parity, implied delta, and the three 2026-09-17 cases
     recomputed from recorded prices
  2. the verdict — below the floor is a long shot, deep in the money never is,
     and with no computable delta it falls back to moneyness
  3. the guard's modes — shadow never blocks, enforce blocks only long shots,
     off does nothing, an unreadable mode behaves as shadow
  4. it can only narrow — only the floor is guarded, only where a floor is set
  5. recording the real delta cannot loosen `confirmation_required`
     (negative control, as in test_vwap_stretch)
  6. no exit path reads it

No network, no DB.
"""
import io
import logging
import math
import os
import sys
from datetime import datetime, timedelta, time as dtime

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')  # noqa: E702

import engine.signal_generator as sg
from engine import live_greeks as lg
from engine.signal_generator import SignalGenerator

# Mid-session on the contract's own expiry day: 270 minutes to the 16:00 close.
NOW = datetime(2026, 9, 10, 11, 30)
sg._market_hours.get_current_et_time = lambda: NOW
sg._market_hours.get_market_close_time_et = lambda: dtime(16, 0)
MINS = 270.0
T0 = datetime(2026, 9, 10, 14, 0, 0)
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<72} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def near(x, y, tol):
    return x is not None and abs(x - y) <= tol


# ------------------------------------------------------------------ 1. the maths
print("1. the maths:")
check("OCC symbol parses", lg.parse_occ("SPY260917P00758000"),
      (datetime(2026, 9, 17).date(), "P", 758.0))
check("a malformed symbol returns None", lg.parse_occ("SPY"), None)

c, dc = lg.bs_price_delta(700, 698, MINS, 0.20, "C")
p, dp = lg.bs_price_delta(700, 698, MINS, 0.20, "P")
check("put-call parity at r=0: C - P = S - K", round(c - p, 6), 2.0)
check("call delta minus put delta is exactly 1", round(dc - dp, 9), 1.0)

d, iv, src = lg.implied_abs_delta(700, 698, MINS, c, "C")
check("implied vol is recovered from the price it produced", round(iv, 4), 0.20)
check("...and so is the delta", round(d, 4), round(dc, 4))
check("price at intrinsic -> no time value (deep ITM)",
      lg.implied_abs_delta(700, 690, MINS, 10.0, "C")[2], "no_time_value")
check("no time to expiry -> unavailable", lg.implied_abs_delta(700, 698, 0, 3.0, "C")[2], "unavailable")

# The three 2026-09-17 cases, from recorded prices (docs: TODO.md G5 table).
def d917(hms, spot, strike, mid, kind):
    now = datetime.fromisoformat("2026-09-17T" + hms)
    sym = "SPY260917%s%08d" % (kind, int(strike * 1000))
    return lg.live_delta(sym, spot, mid, mid, now).delta

check("09-17 09:30:42 put 758 — real delta ~0.128 (broker said 0.727)",
      near(d917("09:30:42", 762.68, 758, 0.265, "P"), 0.128, 0.005), True)
check("09-17 10:04:30 put 758 — real delta ~0.233 at the buy",
      near(d917("10:04:30", 760.63, 758, 0.495, "P"), 0.233, 0.005), True)
check("09-17 09:30:43 call 751 — real delta ~0.945 (broker said 0.656)",
      near(d917("09:30:43", 762.73, 751, 11.905, "C"), 0.945, 0.005), True)

ld = lg.live_delta("SPY260910C00698000", 700.0, None, None, NOW)
check("no quote -> unavailable, but moneyness is still known",
      (ld.source, round(ld.itm_dollars, 2)), ("unavailable", 2.0))
check("a tz-aware 'now' is read as ET wall time",
      lg.live_delta("SPY260910C00698000", 700.0, c - 0.01, c + 0.01,
                    NOW.replace(tzinfo=__import__("datetime").timezone.utc)).source, "computed")

# ------------------------------------------------------------------ 2. verdict
print("\n2. the long-shot verdict:")
LD = lg.LiveDelta
check("computed 0.23 < 0.60 is a long shot", lg.is_long_shot(LD(0.23, .2, "computed", -2.6, .5), 0.6)[0], True)
check("computed 0.72 is not", lg.is_long_shot(LD(0.72, .2, "computed", 2.0, 3.0), 0.6)[0], False)
check("computed 0.95 (deep) is not — the deep side is NOT guarded",
      lg.is_long_shot(LD(0.95, .3, "computed", 9.0, 11.0), 0.6)[0], False)
check("no time value (deep ITM) is never a long shot",
      lg.is_long_shot(LD(None, None, "no_time_value", 10.0, 10.0), 0.6)[0], False)
check("unavailable + out of the money -> long shot",
      lg.is_long_shot(LD(None, None, "unavailable", -1.5, None), 0.6)[0], True)
check("unavailable + at the money (0) -> long shot",
      lg.is_long_shot(LD(None, None, "unavailable", 0.0, None), 0.6)[0], True)
check("unavailable + in the money -> not",
      lg.is_long_shot(LD(None, None, "unavailable", 1.5, None), 0.6)[0], False)
check("nothing known at all -> long shot (most restrictive)",
      lg.is_long_shot(LD(None, None, "unavailable", None, None), 0.6)[0], True)

# ------------------------------------------------------------------ 3. the guard
print("\n3. the guard inside check_entry_signal:")


class FakeStrategy:
    """A call strategy that clears every earlier gate on the tape below."""
    def __init__(self, **over):
        p = {"ema_period": 9, "use_vwap": True, "entry_signal": "price_above_9ema_and_vwap",
             "volume_spike_required": False, "confirmation_required": False,
             "direction": "call", "entry_after_open_minutes": 0,
             "exit_before_close_minutes": 15, "delta_min": 0.60, "delta_max": 0.85}
        p.update(over)
        self.params_json = p
        self.id = 7
        self.name = "test"


def build():
    """45 minutes alternating 699/701 closing low: VWAP 700, EMA ~699 (see test_vwap_stretch)."""
    g = SignalGenerator()
    cv = 1_000_000
    for i in range(60 * 45):
        px = 699.0 if i % 2 else 701.0
        cv += 100
        g._update_history("SPY", px, 100, cum_volume=cv, ts=T0 + timedelta(seconds=i))
    g._update_history("SPY", 700.0, 0, cum_volume=cv, ts=T0 + timedelta(seconds=60 * 45))
    return g


SPOT = 700.4


def quote(strike, iv=0.20, kind="C"):
    px = lg.bs_price_delta(SPOT, strike, MINS, iv, kind)[0]
    return round(px - 0.01, 2), round(px + 0.01, 2)


def data(strike, bid_ask=None, broker=0.727):
    b, a = bid_ask if bid_ask else quote(strike)
    return {"option_symbol": "SPY260910C%08d" % int(strike * 1000), "bid": b, "ask": a,
            "delta": broker, "open_interest": 5000}


buf = io.StringIO()
h = logging.StreamHandler(buf)
sg.logger.addHandler(h)
sg.logger.setLevel(logging.INFO)


def run(mode=None, strike=698.0, bid_ask=None, **over):
    if mode is not None:
        over["live_delta_guard"] = mode
    buf.truncate(0); buf.seek(0)
    sig = build().check_entry_signal(strategy=FakeStrategy(**over), symbol="SPY",
                                     current_price=SPOT, current_volume=1_000,
                                     additional_data=data(strike, bid_ask))
    return sig, buf.getvalue()


LONG = 702.5      # out-of-the-money call: real delta ~0.2 though the broker says 0.727
DEEP = 690.0      # deep in the money

sig, log = run("enforce", 698.0)
check("enforce + a genuinely in-band contract still fires", sig is not None, True)
check("...and the real delta is recorded", "delta_live" in sig.indicators, True)

sig, log = run("enforce", LONG)
check("enforce + a long shot the broker calls 0.727 is BLOCKED", sig, None)
check("...and says so in the log", "Long shot BLOCKED" in log, True)

sig, log = run("shadow", LONG)
check("shadow + the same long shot is NOT blocked", sig is not None, True)
check("...but logs what it would have blocked", "WOULD BLOCK long shot (shadow)" in log, True)
check("...and records the real delta below the floor", sig.indicators["delta_live"] < 0.60, True)

sig, log = run(None, LONG)
check("no setting at all means shadow (records, never blocks)",
      (sig is not None, "WOULD BLOCK" in log), (True, True))

sig, log = run("enforce", DEEP, bid_ask=(10.39, 10.41))
check("enforce + deep in the money (no time value) fires", sig is not None, True)
check("...recorded as no_time_value", sig.indicators["delta_live_source"], "no_time_value")

sig, log = run("off", LONG)
check("off: a long shot fires and nothing is computed",
      (sig is not None, "delta_live_source" in sig.indicators), (True, False))

sig, log = run("yes", LONG)
check("an unreadable mode behaves as shadow — does not block",
      (sig is not None, "WOULD BLOCK" in log), (True, True))
check("...and says the setting is unreadable", "is not off/shadow/enforce" in log, True)

sig, log = run("enforce", LONG, bid_ask=(0, 0))
check("enforce + no quote + out of the money -> blocked on moneyness", sig, None)
sig, log = run("enforce", 698.0, bid_ask=(0, 0))
check("enforce + no quote + in the money -> fires on moneyness", sig is not None, True)

print("\n3b. a stale option quote is not used to solve delta:")
fresh = lg.live_delta("SPY260910C00698000", 700.0, c - 0.01, c + 0.01, NOW, quote_age_s=5)
stale = lg.live_delta("SPY260910C00698000", 700.0, c - 0.01, c + 0.01, NOW, quote_age_s=45)
check("a 5-second-old quote is used", fresh.source, "computed")
check("a 45-second-old quote is not — stale_quote", stale.source, "stale_quote")
check("...but moneyness is still known from the live underlying", round(stale.itm_dollars, 2), 2.0)
check("unknown age (None) is not treated as stale",
      lg.live_delta("SPY260910C00698000", 700.0, c - 0.01, c + 0.01, NOW, quote_age_s=None).source, "computed")


def run_aged(mode, strike, age):
    buf.truncate(0); buf.seek(0)
    d = data(strike); d["quote_age_s"] = age
    return build().check_entry_signal(strategy=FakeStrategy(live_delta_guard=mode), symbol="SPY",
                                      current_price=SPOT, current_volume=1_000, additional_data=d), buf.getvalue()


sig, log = run_aged("enforce", LONG, 45)
check("enforce + stale quote + out of the money -> blocked on moneyness", sig, None)
sig, log = run_aged("enforce", 698.0, 45)
check("enforce + stale quote + in the money -> fires", sig is not None, True)
check("...recorded as stale_quote", sig.indicators["delta_live_source"], "stale_quote")
sig, log = run_aged("shadow", LONG, 45)
check("shadow + stale quote + out of the money -> logs, does not block",
      (sig is not None, "WOULD BLOCK" in log), (True, True))

# ------------------------------------------------------- 4. it can only narrow
print("\n4. it can only narrow the entry path:")
sig, log = run("enforce", LONG, delta_min=0.0)
check("no floor configured -> the guard does not apply at all",
      (sig is not None, "delta_live_source" in (sig.indicators if sig else {})), (True, False))
sig, log = run("enforce", 698.0, delta_max=0.10)
check("the broker-delta band still rejects first — 4b adds, never replaces", sig, None)

# ------------------------------------------- 5. confirmation is not loosened
print("\n5. recording the real delta cannot loosen confirmation_required:")
# Built so the ONLY real indicator is 'delta': EMA off, VWAP not a gate, no quote
# (so no bid_ask_spread), no OI floor. The observation 'delta_live_source' is
# then the only other key. In the money, so shadow has nothing to flag.
CONFIRM = dict(confirmation_required=True, ema_period=0, use_vwap=False, entry_signal="")


def confirm_case():
    d = data(698.0, bid_ask=(0, 0))
    d.pop("open_interest")
    return build().check_entry_signal(strategy=FakeStrategy(live_delta_guard="shadow", **CONFIRM),
                                      symbol="SPY", current_price=SPOT, current_volume=1_000,
                                      additional_data=d)


check("one real indicator + the recorded observation does NOT clear confirmation", confirm_case(), None)
_saved = sg._OBSERVED_NOT_GATED
sg._OBSERVED_NOT_GATED = frozenset({"vwap_stretch"})
try:
    unguarded = confirm_case()
finally:
    sg._OBSERVED_NOT_GATED = _saved
check("...and WOULD fire if the new keys were missing from _OBSERVED_NOT_GATED",
      unguarded is not None, True)
check("both new keys are declared observation-only",
      {"delta_live", "delta_live_source"} <= sg._OBSERVED_NOT_GATED, True)
sig, _ = run("shadow", 698.0)
check("they never appear in the trade's reason string",
      "delta_live" in sig.reason, False)

# ------------------------------------------------------ 6. exits never read it
print("\n6. no exit path reads it:")
import inspect
exit_src = inspect.getsource(SignalGenerator.check_exit_signal)
check("check_exit_signal source is non-trivial (guard the guard)", len(exit_src) > 500, True)
for needle in ("live_greeks", "delta_live", "live_delta_guard", "is_long_shot"):
    check(f"check_exit_signal does not mention {needle}", needle in exit_src, False)

print("\n7. the greeks-refresh log line (observation only):")
lg._greeks_seen.clear()
check("first sighting logs",
      "first seen" in (lg.note_greeks_refresh("SPY260917P00758000", "2026-09-16 20:00:06", -0.727) or ""), True)
check("the same timestamp again logs nothing",
      lg.note_greeks_refresh("SPY260917P00758000", "2026-09-16 20:00:06", -0.727), None)
line = lg.note_greeks_refresh("SPY260917P00758000", "2026-09-17 10:15:02", -0.208)
check("a changed timestamp logs the refresh, old -> new",
      ("REFRESHED" in line, "20:00:06 -> 2026-09-17 10:15:02" in line), (True, True))
check("no timestamp -> nothing", lg.note_greeks_refresh("SPY260917P00758000", None, 0.5), None)
src_drift = open("api/engine/stream_driven_worker.py").read()
i_hook = src_drift.find("note_greeks_refresh(sym")
i_decide = src_drift.find("if not (delta_min <= delta <= delta_max) or oi < min_oi:")
check("the drift check calls it BEFORE its own decision, inside try/except",
      0 < i_hook < i_decide and "except Exception:" in src_drift[i_hook:i_decide], True)

print()
if fails:
    print("FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL PASSED")

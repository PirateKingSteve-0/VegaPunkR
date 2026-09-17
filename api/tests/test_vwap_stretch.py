"""The "don't chase" gate: block entries made far from VWAP (TODO.md G4b).

The existing VWAP gate is binary -- a penny above the line and a dollar above it
pass identically. Measured on 20 sessions of SPY 1-minute bars, price sitting 1+
"wiggles" from VWAP drifts ~3.0 bp BACK toward it over the next 30 minutes
(shuffle p = 0.001), and the 27 replayed entries made 1-2 wiggles out lost $534 --
more than the whole strategy's $425.

A wiggle is the volume-weighted standard deviation of price around today's VWAP,
so the threshold self-scales through the day (~$0.41 at 10:00 ET, ~$1.05 at
15:00 ET) instead of meaning something different every hour.

Pinned here:
  1. the wiggle is the volume-weighted SD, and it is volume-weighted, not a
     plain SD over sampled prices
  2. stretch is measured in wiggles and blocks at >= vwap_max_stretch, on BOTH
     sides of VWAP (a put chasing downward is chasing too)
  3. an unavailable wiggle BLOCKS, like every other indicator in this file
  4. the param being unset changes nothing -- it ships off
  5. recording `vwap_stretch` does NOT weaken `confirmation_required`, which is
     live on both prod strategies, and does not appear in the reason string
  6. exits are untouched

No network, no DB: SignalGenerator is driven directly with an injected clock.
"""
import os
import sys
from datetime import datetime, timedelta, time as dtime

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')  # noqa: E702

import engine.signal_generator as sg
from engine.signal_generator import SignalGenerator

# Mid-session so the entry-time gates never participate.
sg._market_hours.get_current_et_time = lambda: datetime(2026, 9, 10, 11, 30)
sg._market_hours.get_market_close_time_et = lambda: dtime(16, 0)

T0 = datetime(2026, 9, 10, 14, 0, 0)
fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<68} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class FakeStrategy:
    """Mirrors the live prod params (strategies 3 and 4) unless overridden."""
    def __init__(self, **over):
        p = {
            "ema_period": 9,
            "use_vwap": True,
            "entry_signal": "price_above_9ema_and_vwap",
            "volume_spike_required": False,
            "confirmation_required": False,
            "direction": "call",
            "entry_after_open_minutes": 0,
            "exit_before_close_minutes": 15,
        }
        p.update(over)
        self.params_json = p
        self.id = 1
        self.name = "test"


def build(prices_and_volumes, symbol="SPY"):
    """Feed (price, volume) pairs one second apart and return the generator."""
    g = SignalGenerator()
    cv = 1_000_000
    for i, (px, vol) in enumerate(prices_and_volumes):
        cv += vol
        g._update_history(symbol, px, vol, cum_volume=cv,
                          ts=T0 + timedelta(seconds=i))
    return g


def tape(close_low=True, minutes=45):
    """A tape with VWAP exactly 700.0 and a wiggle of exactly 1.0.

    Prices alternate 699/701 every second, so the volume-weighted SD around
    VWAP is 1.0 by construction and one wiggle is one dollar -- which makes
    every stretch in this file readable as cents.

    `close_low` picks which of the two the MINUTE closes on, and so which side
    of the tape the 9-minute EMA settles on (699 or 701). The side check needs
    price above the EMA for calls and below it for puts, so the two cases need
    opposite tapes; without this the EMA gate blocks first and the stretch gate
    is never reached -- which is exactly how the first draft of this test fooled
    itself into passing.

    The final flush tick carries volume 0 so it moves the bar without skewing
    VWAP off 700.0 by one odd tick.

    `minutes` defaults to 45 so the accumulator clears the 30-minute warm-up.
    At the old default of 30 the tape was 29.98 minutes old and EVERY stretch
    case blocked on warm-up instead of on the thing it meant to test -- which
    is a useful reminder that a passing stretch test needs a warm tape.
    """
    lo, hi = 699.0, 701.0
    out = []
    for i in range(60 * minutes):
        odd = i % 2 == 1
        out.append(((lo if odd else hi) if close_low else (hi if odd else lo), 100))
    out.append((700.0, 0))          # flushes the last bar, contributes no volume
    return out


# ---------------------------------------------------------------- 1. the maths
print("1. the wiggle is the VOLUME-weighted standard deviation around VWAP:")

g = build([(100.0, 10), (100.0, 10), (100.0, 10)])
check("a single repeated price has no dispersion -> None",
      g._calculate_vwap_wiggle("SPY"), None)

g = build([(90.0, 10), (110.0, 10)])
check("+/-10 around a VWAP of 100 gives a wiggle of 10.0",
      round(g._calculate_vwap_wiggle("SPY"), 9), 10.0)

# Volume weighting: same two prices, but 90 carries 9x the volume.
# VWAP = (90*90 + 110*10)/100 = 92.0; var = .9*(−2)^2 + .1*(18)^2 = 36 -> sd 6.0
g = build([(90.0, 90), (110.0, 10)])
check("VWAP is pulled to the heavy side (92.0, not 100)",
      round(g._calculate_vwap("SPY"), 9), 92.0)
check("and the wiggle is volume-weighted too (6.0, not a plain SD of 10)",
      round(g._calculate_vwap_wiggle("SPY"), 9), 6.0)

g = SignalGenerator()
check("no ticks at all -> None", g._calculate_vwap_wiggle("SPY"), None)

# The float-cancellation claim is pinned in SECTION 2, not here. _calculate_vwap_wiggle
# uses E[p^2] - E[p]^2, which subtracts two large nearly-equal numbers; the cases above
# run at 90-110 where that is harmless, so they do NOT exercise it. The section-2 tape
# asserts VWAP 700.0 and a wiggle of 1.0 to six decimals -- a variance of 1 against an
# E[p^2] near 490,001, i.e. a 490,000:1 cancellation at SPY-scale prices, which is the
# regime the engine actually runs in. Noted here because this is where someone auditing
# the numerics would look first.

g = build([(100.0, 10)])
g._vwap_accumulators["SPY"].pop("sum_p2v")          # accumulator from a hot reload
check("an accumulator predating the field -> None, never a wrong wiggle",
      g._calculate_vwap_wiggle("SPY"), None)

# -------------------------------------------------------------- 2. the gate
print("\n2. the gate blocks at >= vwap_max_stretch wiggles, and only then:")

g = build(tape())
check("test tape has VWAP 700.0", round(g._calculate_vwap("SPY"), 6), 700.0)
check("test tape has a wiggle of exactly 1.0",
      round(g._calculate_vwap_wiggle("SPY"), 6), 1.0)
check("so one wiggle is one dollar, and the EMA sits clear at 699",
      round(g._calculate_ema("SPY", 9), 6), 699.0)


def fired(price, close_low=True, minutes=45, **params):
    """Did an entry signal survive every gate at this price?"""
    gen = build(tape(close_low=close_low, minutes=minutes))
    sig = gen.check_entry_signal(strategy=FakeStrategy(**params), symbol="SPY",
                                 current_price=price, current_volume=1_000)
    return sig is not None


# 0.4 wiggles above VWAP -- near the line, allowed.
check("0.4 wiggles out is allowed", fired(700.4, vwap_max_stretch=1.0), True)
check("0.99 wiggles out is allowed", fired(700.99, vwap_max_stretch=1.0), True)
check("1.4 wiggles out is BLOCKED", fired(701.4, vwap_max_stretch=1.0), False)
check("exactly 1.0 is blocked (>=, not >)", fired(701.0, vwap_max_stretch=1.0), False)
check("a higher threshold lets 1.4 through", fired(701.4, vwap_max_stretch=2.0), True)

# Puts chase downward. Direction flips the side check, so the put must be BELOW.
check("a put 0.4 wiggles BELOW is allowed",
      fired(699.6, close_low=False, vwap_max_stretch=1.0, direction="put",
            entry_signal="price_below_9ema_and_vwap"), True)
check("a put 1.4 wiggles BELOW is BLOCKED (stretch is absolute)",
      fired(698.6, close_low=False, vwap_max_stretch=1.0, direction="put",
            entry_signal="price_below_9ema_and_vwap"), False)

# ------------------------------------------------- 3. unavailable -> blocked
print("\n3. a wiggle that cannot be computed BLOCKS, like every other indicator:")

gen = build(tape())                      # a monotone ramp still has dispersion
gen._vwap_accumulators["SPY"].pop("sum_p2v")
check("no sum_p2v -> entry blocked, not traded ungated",
      gen.check_entry_signal(strategy=FakeStrategy(vwap_max_stretch=1.0),
                             symbol="SPY", current_price=800.0,
                             current_volume=1_000), None)

gen = build(tape())
gen._vwap_accumulators["SPY"] = {"date": None, "sum_pv": 0.0, "sum_v": 0, "sum_p2v": 0.0}
check("no VWAP at all + stretch set -> blocked even when entry_signal omits vwap",
      gen.check_entry_signal(
          strategy=FakeStrategy(vwap_max_stretch=1.0, entry_signal="price_above_9ema"),
          symbol="SPY", current_price=800.0, current_volume=1_000), None)

# --------------------------------------------------------- 4. off by default
print("\n4. the param ships OFF -- an unset value changes nothing:")

check("3.0 wiggles out still fires when vwap_max_stretch is unset",
      fired(703.0), True)
# ...but the stretch IS still recorded, so a session can be measured without
# first committing to a threshold. BRAINSTORM.md asks for this explicitly: the
# measurement must not be gated behind the decision it exists to inform.
gen = build(tape())
sig = gen.check_entry_signal(strategy=FakeStrategy(), symbol="SPY",
                             current_price=703.0, current_volume=1_000)
check("the stretch is recorded even with the gate off",
      sig is not None and 'vwap_stretch' in sig.indicators, True)
check("and it is the real value (703.0 is 3 wiggles out)",
      sig.indicators['vwap_stretch'], 3.0)
check("...still not reported as a condition met",
      'vwap_stretch' in sig.reason, False)

# The whole point: recording must not change WHICH trades are taken. With the
# gate off, a 3-wiggle entry still fires.
check("recording changes no entry decision", sig.action, 'buy')

# ------------------------------------------- 5. recording must not widen gates
print("\n5. recording vwap_stretch must not weaken confirmation_required:")

gen = build(tape())
sig = gen.check_entry_signal(strategy=FakeStrategy(vwap_max_stretch=1.0),
                             symbol="SPY", current_price=700.4,
                             current_volume=1_000)
check("an allowed entry records the stretch for later measurement",
      sig is not None and 'vwap_stretch' in sig.indicators, True)
check("recorded to 3dp in wiggles", sig.indicators['vwap_stretch'], 0.4)
check("it is NOT listed as a condition that was met",
      'vwap_stretch' in sig.reason, False)
check("real conditions still are", 'vwap' in sig.reason and 'ema' in sig.reason, True)

# confirmation_required needs 2 GATING indicators, and vwap_stretch must not
# be allowed to act as the second one.
#
# This case has to be built so that `indicators` is EXACTLY {vwap, vwap_stretch}.
# An earlier draft used use_vwap=False + entry_signal="price_above_9ema", which
# left indicators == {ema} -- so it blocked on the pre-existing count alone and
# passed identically with _OBSERVED_NOT_GATED emptied. It asserted nothing.
# ema_period=0 drops the EMA entirely, leaving vwap as the only real indicator.
CONFIRM_CASE = dict(vwap_max_stretch=1.0, confirmation_required=True,
                    ema_period=0, entry_signal="price_above_vwap")

gen = build(tape())
sig = gen.check_entry_signal(strategy=FakeStrategy(**CONFIRM_CASE), symbol="SPY",
                             current_price=700.4, current_volume=1_000)
check("one real indicator + a recorded observation does NOT clear confirmation",
      sig, None)

# Prove the line above is load-bearing rather than passing for some other
# reason: with the guard removed the SAME inputs must place an order.
_saved = sg._OBSERVED_NOT_GATED
sg._OBSERVED_NOT_GATED = frozenset()
try:
    gen = build(tape())
    unguarded = gen.check_entry_signal(strategy=FakeStrategy(**CONFIRM_CASE),
                                       symbol="SPY", current_price=700.4,
                                       current_volume=1_000)
finally:
    sg._OBSERVED_NOT_GATED = _saved
check("...and WOULD fire on one indicator if the guard were removed",
      unguarded is not None, True)

gen = build(tape())
sig = gen.check_entry_signal(
    strategy=FakeStrategy(vwap_max_stretch=1.0, confirmation_required=True),
    symbol="SPY", current_price=700.4, current_volume=1_000)
check("two real indicators (ema + vwap) still clear it", sig is not None, True)

# ------------------------------------------- 5b. independent of use_vwap
print("\n5b. a configured gate must never be silently inert:")

# Regression: vwap_max_stretch used to be read INSIDE `if use_vwap:`, so a
# strategy that set the gate but left use_vwap false got no gate at all and no
# log line. Five wiggles out still fired.
check("stretch gate applies even when use_vwap is false",
      fired(705.0, use_vwap=False, entry_signal="price_above_9ema",
            vwap_max_stretch=1.0), False)
check("...and still allows a near-the-line entry",
      fired(700.4, use_vwap=False, entry_signal="price_above_9ema",
            vwap_max_stretch=1.0), True)

# But opting into the DISTANCE check must not hand the strategy a SIDE check
# it never asked for: 699.6 is below VWAP, which a side check would reject.
check("stretch-only does not add a side check (below VWAP still allowed)",
      fired(699.6, use_vwap=False, entry_signal="price_above_9ema",
            vwap_max_stretch=1.0), True)

# ...nor inflate the confirmation count with a 'vwap' key it did not ask for.
gen = build(tape())
sig = gen.check_entry_signal(
    strategy=FakeStrategy(use_vwap=False, entry_signal="price_above_9ema",
                          vwap_max_stretch=1.0),
    symbol="SPY", current_price=700.4, current_volume=1_000)
check("stretch-only does not record a 'vwap' indicator",
      'vwap' in sig.indicators, False)
check("but does record the stretch", 'vwap_stretch' in sig.indicators, True)

print("\n5d. the wiggle is not trusted until it has seen enough of the session:")

# A tally built from a stub of the session understates dispersion, overstates
# the stretch, and makes the gate refuse ordinary entries. Measured on the tape:
# 2026-09-10 gave 0.69 against a full-session 1.24; 2026-09-11 at 15:00 ET gave
# 0.58 against 2.44. Both are sessions where the engine restarted mid-day.
check("a 29-minute tally is too young to act on",
      fired(700.4, minutes=29, vwap_max_stretch=1.0), False)
check("a 31-minute tally is old enough",
      fired(700.4, minutes=31, vwap_max_stretch=1.0), True)
check("and a too-young tally blocks even a near-the-line entry",
      fired(700.01, minutes=10, vwap_max_stretch=1.0), False)

# The guard belongs to the stretch gate alone. A strategy that never opted in
# must be completely unaffected -- this is what keeps the change inert on the
# four live strategies, none of which set vwap_max_stretch.
check("warm-up does NOT apply when the stretch gate is off",
      fired(700.4, minutes=10), True)
check("...not even far from VWAP", fired(705.0, minutes=10), True)

g = build(tape(minutes=29))
check("age is reported from the tick clock, not wall time",
      round(g._vwap_accumulator_age_minutes("SPY")), 29)
check("an empty accumulator has no age",
      SignalGenerator()._vwap_accumulator_age_minutes("SPY"), None)

print("\n5c. an unusable threshold blocks rather than crashing or being ignored:")

# A JSON string that is plainly a number is COERCED, not rejected -- there is no
# UI field for this param yet, so "1.0" is an easy and unambiguous thing to
# write by hand. It used to raise TypeError out of every evaluation.
check("vwap_max_stretch='1.0' is coerced: near the line still fires",
      fired(700.01, vwap_max_stretch="1.0"), True)
check("vwap_max_stretch='1.0' is coerced: stretched still blocks",
      fired(705.0, vwap_max_stretch="1.0"), False)

# Anything we cannot read as a positive threshold blocks. Ignoring it would
# silently widen the entry path back to un-gated, which is the worse failure.
for bad in (True, 0, -1, "abc", float('nan')):
    check(f"vwap_max_stretch={bad!r} blocks every entry",
          fired(700.01, vwap_max_stretch=bad), False)

# ---------------------------------------------------------------- 6. exits
print("\n6. exits are untouched -- the gate is entry-only:")

import inspect  # noqa: E402
exit_src = inspect.getsource(SignalGenerator.check_exit_signal)
# Guard the guard: if the exit method is ever renamed, the two checks below
# would pass vacuously against an empty string.
check("the exit path was actually found and read", len(exit_src) > 500, True)
check("no exit path reads vwap_max_stretch",
      'vwap_max_stretch' in exit_src or 'vwap_stretch' in exit_src, False)
check("no exit path reads the wiggle",
      '_calculate_vwap_wiggle' in exit_src, False)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

"""The entry-time cutoff: stop opening positions after a wall-clock ET time.

`params_json.entry_before_et` ("HH:MM", absolute ET) blocks NEW entries from that
minute onward. It exists because late entries lose money for two reasons that have
nothing to do with the signal: SPY volume troughs over lunch (median 97,052/min at
09:30 against 33,950 at 12:30) and theta over a 30-minute hold runs ~2% at 10:00 ET
against ~28% at 15:30, so a late entry is stopped out by the clock rather than by
being wrong. Measured over 9 recorded trading days / 146 replayed round trips,
entries from 11:30 ET onward lost on 7 of 9 days, -$716 across 117 trades, while
the 29 before 11:30 made +$311. Live on 2026-09-15 a 12:30 ET entry gave back $54
of the $192 the two morning entries had made.

THE POINT OF THE WHOLE GATE is section 3: it stops us BUYING without touching the
EXIT. `User.trading_window_end` conflates those -- it feeds forced_exit_time_et, so
setting it to 11:30 FLATTENS open positions at 11:30. That is the trap this gate is
built to avoid, so section 3 is the section that matters most.

Pinned here:
  1. the wall blocks at/after its minute and allows before it
  2. it composes most-restrictive-wins and never WIDENS an existing bound
  3. it moves NO exit, and no exit path reads it
  4. an absent or unparseable value applies NO wall -- which is exactly why
     schemas.py must reject typos rather than let the engine guess
  5. it is inert on a strategy that has never had the key
  6. check_entry_signal really enforces it end to end, with the clock as the only
     difference between a firing signal and a blocked one

No network, no DB: the module clock is injected.
"""
import os
import sys
from datetime import datetime, timedelta, time as dtime

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')  # noqa: E702

import engine.signal_generator as sg
from engine.signal_generator import (
    SignalGenerator,
    entry_cutoff_reached,
    entry_cutoff_time_et,
    forced_exit_time_et,
)

sg._market_hours.get_market_close_time_et = lambda: dtime(16, 0)

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<70} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def at(h, m):
    """A moment on 2026-09-16, a normal Wednesday session."""
    return datetime(2026, 9, 16, h, m)


def clock(now):
    sg._market_hours.get_current_et_time = lambda: now


class FakeUser:
    def __init__(self, enabled=False, start=None, end=None):
        self.trading_window_enabled = enabled
        self.trading_window_start = start
        self.trading_window_end = end
        self.trading_halted_on = None
        self.trading_halt_mode = None
        self.id = 1


# Mirrors live prod strategies 3 and 4.
PROD = {"entry_after_open_minutes": 30, "exit_before_close_minutes": 15}
WALL = dict(PROD, entry_before_et="11:30")


def cutoff(params, now, user=None):
    t, _ = entry_cutoff_time_et(params, user or FakeUser(), now)
    return t.strftime("%H:%M") if t else None


def blocked(params, now, user=None):
    """Is the entry window closed at `now`? Goes through the same helper the
    executor uses, so this tests the real consumer rather than a reimplementation."""
    clock(now)
    return entry_cutoff_reached(params, user or FakeUser()) is not None


print("1. the wall blocks at/after its minute, and allows before it:")
check("cutoff resolves to the wall, not the forced exit", cutoff(WALL, at(10, 0)), "11:30")
check("10:00 -> open", blocked(WALL, at(10, 0)), False)
check("11:29 -> open", blocked(WALL, at(11, 29)), False)
check("11:30 exactly -> BLOCKED (>=, not >)", blocked(WALL, at(11, 30)), True)
check("12:30 -> BLOCKED (the trade that cost us $54)", blocked(WALL, at(12, 30)), True)
check("15:00 -> BLOCKED", blocked(WALL, at(15, 0)), True)

print("\n2. composition -- most restrictive wins, and it never WIDENS a bound:")
check("no wall -> cutoff is the forced-exit time 15:45", cutoff(PROD, at(10, 0)), "15:45")
check("a wall EARLIER than the forced exit wins", cutoff(WALL, at(10, 0)), "11:30")
# The important direction: a LATER wall must not push the cutoff out past the
# forced exit, or we would open a position we are already obliged to close.
check("a wall LATER than the forced exit cannot widen it",
      cutoff(dict(PROD, entry_before_et="15:55"), at(10, 0)), "15:45")
check("a tighter exit_before_close still wins over a later wall",
      cutoff({"exit_before_close_minutes": 60, "entry_before_et": "15:30"}, at(10, 0)), "15:00")
# The account window is an independent layer and must still be able to tighten.
check("account trading_window_end tightens past the wall",
      cutoff(WALL, at(10, 0), FakeUser(True, "09:45", "11:00")), "11:00")
check("...and the wall still wins when it is the earlier of the two",
      cutoff(WALL, at(10, 0), FakeUser(True, "09:45", "15:45")), "11:30")

print("\n3. EXITS ARE UNTOUCHED -- the reason this is a separate function:")
# If entry_before_et ever reached forced_exit_time_et, a position opened at 10:09
# would be flattened at 11:30 instead of running to its target. That is the
# User.trading_window_end trap, and this is the assertion that catches it.
exit_without, _ = forced_exit_time_et(PROD, FakeUser(), at(10, 0))
exit_with, _ = forced_exit_time_et(WALL, FakeUser(), at(10, 0))
check("forced exit is identical with and without the wall", exit_with, exit_without)
check("...and it is still 15:45, not 11:30", exit_with.strftime("%H:%M"), "15:45")

import inspect  # noqa: E402
exit_src = inspect.getsource(SignalGenerator.check_exit_signal)
check("the exit path was actually found and read", len(exit_src) > 500, True)
check("no exit path reads entry_before_et", 'entry_before_et' in exit_src, False)
check("no exit path calls entry_cutoff_time_et", 'entry_cutoff' in exit_src, False)
fx_src = inspect.getsource(forced_exit_time_et)
check("forced_exit_time_et itself never reads entry_before_et",
      'entry_before_et' in fx_src, False)

print("\n4. an absent or unparseable wall applies NO wall (schemas.py rejects typos):")
for bad in ("11.30", "1130", "25:00", "11:60", "lunch", "", None, 1130):
    check(f"entry_before_et={bad!r} -> falls back to the forced exit",
          cutoff(dict(PROD, entry_before_et=bad), at(12, 30)), "15:45")

print("\n5. inert on a strategy that has never had the key:")
check("12:30 with prod params as they stand today -> still open",
      blocked(PROD, at(12, 30)), False)
check("empty params -> open (and clamped to the 15:45 EOD floor)",
      cutoff({}, at(12, 30)), "15:45")

print("\n6. end to end through check_entry_signal, clock the only variable:")


def firing_generator(symbol="SPY"):
    """History where price sits above both the 9EMA and VWAP, so the indicator
    gates all pass and only the clock can block the entry."""
    g = SignalGenerator()
    cv = 1_000_000
    base = datetime(2026, 9, 16, 9, 31)
    # Rising minute bars: each tick a new minute, so bars complete immediately.
    for i in range(12):
        cv += 10_000
        g._update_history(symbol, 700.0 + i * 0.10, 10_000,
                          cum_volume=cv, ts=base + timedelta(minutes=i))
    return g


class FakeStrategy:
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


def fires(now, **over):
    clock(now)
    g = firing_generator()
    sig = g.check_entry_signal(strategy=FakeStrategy(**over), symbol="SPY",
                              current_price=706.0, current_volume=10_000,
                              additional_data={}, user=FakeUser())
    return sig is not None


# Control: with no wall the signal fires at both times, so any difference below
# is the wall and not the indicators.
check("no wall, 11:00 -> fires", fires(at(11, 0)), True)
check("no wall, 12:30 -> fires (today's leak)", fires(at(12, 30)), True)
check("wall 11:30, 11:00 -> still fires", fires(at(11, 0), entry_before_et="11:30"), True)
check("wall 11:30, 12:30 -> BLOCKED", fires(at(12, 30), entry_before_et="11:30"), False)
check("wall 11:30, 11:29 -> fires", fires(at(11, 29), entry_before_et="11:30"), True)
check("wall 11:30, 11:30 -> BLOCKED", fires(at(11, 30), entry_before_et="11:30"), False)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

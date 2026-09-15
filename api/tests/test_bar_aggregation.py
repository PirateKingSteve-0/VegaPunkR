"""The indicator history must aggregate into 1-MINUTE bars (TODO.md G3).

Until 2026-09-10 `_update_history` appended one entry per CALL, and the caller
(stream_driven_worker) evaluates once a second — so `ema_period: 9` was a
9-SECOND EMA. Measured against the recorded SPY tape it crossed spot ~12 times a
minute where a genuine 9-minute EMA crosses 0.2: it tracked price rather than
trend, and gated nothing.

Three things are pinned here:
  1. a bar is a minute, so 9 periods is 9 minutes
  2. bar volume comes from the exchange's CUMULATIVE counter, not from summing
     the ~1 trade per second we happen to sample
  3. an indicator that cannot be computed BLOCKS the entry rather than being
     silently skipped — which is how `ema_period > max_history_length` used to
     delete the filter with nothing logged

No network, no DB: SignalGenerator is driven directly with an injected clock.
"""
import os
import sys
from collections import deque
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
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<66} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


def feed(gen, ticks, cv_step=1000, symbol="SPY"):
    """Push `ticks` one-second samples with cumulative volume climbing evenly."""
    cv = 1_000_000
    for i in range(ticks):
        gen._update_history(symbol, 700.0 + i * 0.001, 100,
                            cum_volume=cv + i * cv_step,
                            ts=T0 + timedelta(seconds=i))


class FakeStrategy:
    def __init__(self, **over):
        p = {
            "ema_period": 9,
            "use_vwap": True,
            "entry_signal": "price_above_9ema_and_vwap",
            "volume_spike_required": True,
            "min_volume_multiplier": 1.5,
            "direction": "call",
            "entry_after_open_minutes": 0,
            "exit_before_close_minutes": 15,
        }
        p.update(over)
        self.params_json = p
        self.id = 1
        self.name = "test"


print("1. a bar is a MINUTE, not a call:")
g = SignalGenerator(); feed(g, 60)
check("60 one-second ticks leave the bar still open", len(g.price_history["SPY"]), 0)
g = SignalGenerator(); feed(g, 61)
check("crossing the minute boundary flushes one bar", len(g.price_history["SPY"]), 1)
g = SignalGenerator(); feed(g, 60 * 10 + 1)
check("ten minutes of ticks make ten bars", len(g.price_history["SPY"]), 10)

print("\n2. `ema_period: 9` now needs nine MINUTES of history:")
g = SignalGenerator(); feed(g, 9)
check("nine seconds does NOT satisfy a 9-period EMA", g._calculate_ema("SPY", 9), None)
g = SignalGenerator(); feed(g, 60 * 8 + 1)
check("eight minutes is still short", g._calculate_ema("SPY", 9), None)
g = SignalGenerator(); feed(g, 60 * 10 + 1)
check("ten minutes satisfies it", g._calculate_ema("SPY", 9) is not None, True)

print("\n3. the bar's close is the last price of that minute:")
g = SignalGenerator()
for i, px in enumerate((700.0, 705.0, 701.0)):
    g._update_history("SPY", px, 100, cum_volume=1000 + i, ts=T0 + timedelta(seconds=i))
g._update_history("SPY", 800.0, 100, cum_volume=2000, ts=T0 + timedelta(minutes=1))
check("close is the minute's final print", g.price_history["SPY"][-1], 701.0)

print("\n4. bar volume is the CUMULATIVE delta, not a sum of sampled tick sizes:")
g = SignalGenerator(); feed(g, 61, cv_step=1000)
check("59 intervals x 1,000 = 59,000 (not 60 x the 100 tick size)",
      g.volume_history["SPY"][0], 59_000)
g = SignalGenerator()
for i in range(61):
    g._update_history("SPY", 700.0, 100, cum_volume=None, ts=T0 + timedelta(seconds=i))
check("no cumulative reading -> volume is unknown, not zero",
      g.volume_history["SPY"][0], None)
g = SignalGenerator()
g._update_history("SPY", 700.0, 100, cum_volume=9_000_000, ts=T0)
g._update_history("SPY", 700.0, 100, cum_volume=5_000, ts=T0 + timedelta(seconds=30))
g._update_history("SPY", 700.0, 100, cum_volume=6_000, ts=T0 + timedelta(minutes=1))
check("a counter reset yields unknown, never a negative volume",
      g.volume_history["SPY"][0], None)

print("\n5. the 20-bar average steps over unknown bars instead of blacking out:")
g = SignalGenerator()
g.volume_history["SPY"] = deque([100] * 10 + [None] + [100] * 10, maxlen=100)
check("one unknown bar costs one bar, not twenty",
      g._calculate_avg_volume("SPY", period=20), 100)
g = SignalGenerator()
g.volume_history["SPY"] = deque([100] * 19, maxlen=100)
check("fewer than 20 usable bars -> no average yet",
      g._calculate_avg_volume("SPY", period=20), None)

print("\n6. an indicator that cannot be computed BLOCKS the entry:")
g = SignalGenerator(); feed(g, 9)
check("cold EMA blocks rather than trading ungated",
      g.check_entry_signal(strategy=FakeStrategy(), symbol="SPY",
                           current_price=800.0, current_volume=1_000_000), None)
g = SignalGenerator(); feed(g, 60 * 30 + 1)
check("ema_period above the buffer blocks (it used to DELETE the gate)",
      g.check_entry_signal(strategy=FakeStrategy(ema_period=500), symbol="SPY",
                           current_price=1e9, current_volume=1_000_000), None)
g = SignalGenerator(); feed(g, 60 * 30 + 1)
check("no volume baseline -> blocked",
      g.check_entry_signal(strategy=FakeStrategy(min_volume_multiplier=0.0),
                           symbol="SPY", current_price=1e9,
                           current_volume=1_000_000) is None, False)

print("\n7. check_entry_signal must NOT feed the history:")
g = SignalGenerator(); feed(g, 60 * 25 + 1)
before = len(g.price_history["SPY"])
st = FakeStrategy()
for _ in range(50):
    g.check_entry_signal(strategy=st, symbol="SPY",
                         current_price=800.0, current_volume=1_000)
check("50 evaluations append nothing (the tick path feeds it)",
      len(g.price_history["SPY"]), before)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

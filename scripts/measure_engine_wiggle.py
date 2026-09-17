#!/usr/bin/env python3
"""Does "1 wiggle" in the LIVE ENGINE mean "1 wiggle" in the research?

    ./venv/bin/python scripts/measure_engine_wiggle.py
    ./venv/bin/python scripts/measure_engine_wiggle.py --day 2026-09-10

Written 2026-09-15. This is the check TODO.md G4b lists as owed before
`vwap_max_stretch` may be switched on, and it has never actually been run --
the comparison previously believed to be it turned out to be two minute-bar
constructions against each other, one of them reading a corrupt field.

THE QUESTION
------------
Every offline result about VWAP stretch is computed from MINUTE BARS
(`session_wiggle`). The live gate computes something different
(`engine_wiggle`): `strategy_executor` calls `_update_history` once per ~1s
evaluation tick with whatever the LAST trade print was, weighting by that one
print's size. It therefore samples roughly one print a second out of the
several hundred that actually print, and weights by a single lot rather than by
the minute's true volume.

If those two quantities are on different scales, then setting the threshold to
1.0 in the engine does NOT enforce the 1.0 the research measured -- it enforces
whatever 1.0 maps to. A gate calibrated in the wrong units is the thing this
script exists to prevent.

HOW FIDELITY IS PRESERVED
-------------------------
No part of the engine is reimplemented here; that is the whole point, and a
replica would be a second implementation of the thing under test. This drives
the REAL `SignalGenerator._update_history` and the REAL
`StrategyMarketState.apply`, in the real order, at the real 1s cadence
(`stream_driven_worker._EVAL_INTERVAL`), gated to regular trading hours exactly
as `stream_driven_worker` gates them.

ONE DELIBERATE DEVIATION: the live call passes no `ts`, so bar boundaries come
from wall-clock `utcnow()`. Replaying a recorded tape against wall-clock would
be meaningless, so the recorded event timestamp is injected instead. That makes
the replay measure the recorded session's own timeline.

`session_wiggle` is built from the Tradier 1-minute file using the `price`
field -- NOT `vwap`, which is corrupt on 1.3%-11.5% of bars depending on the
day (it falls outside the bar's own [low, high]; see scripts/distance_test.py).

Read-only: reads logs and the bar file, writes nothing.
"""
import argparse
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "api"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

from engine.signal_generator import SignalGenerator          # noqa: E402  REAL
from engine.stream_driven_worker import (                    # noqa: E402  REAL
    StrategyMarketState, _EVAL_INTERVAL,
)

ET_OFFSET = timedelta(hours=-4)          # recorded sessions are all EDT
OPEN_ET, CLOSE_ET = "09:30", "16:00"
SNAPSHOT_AT = ("10:00", "10:30", "11:00", "12:00", "13:00", "14:00", "15:00", "15:45")
BARS = os.path.join(REPO, "data", "backtest", "underlying", "SPY_1min.json")


def stream_files():
    """Every stream log, newest last."""
    out = []
    root = os.path.join(REPO, "logs")
    for d in sorted(os.listdir(root)):
        if not d.startswith("livetest-"):
            continue
        p = os.path.join(root, d)
        for f in sorted(os.listdir(p)):
            if f.startswith("stream-") and f.endswith(".jsonl"):
                full = os.path.join(p, f)
                if os.path.getsize(full) > 1_000_000:   # skip boot stubs
                    out.append(full)
    return out


def replay(path, symbol="SPY"):
    """Drive the REAL engine objects over one stream log.

    Returns {et_date: {'HH:MM': (engine_vwap, engine_wiggle, age_min)}}.
    """
    gens = {}          # et_date -> SignalGenerator (one session, one accumulator)
    states = {}
    last_eval = {}
    snaps = defaultdict(dict)

    with open(path, errors="ignore") as fh:
        for line in fh:
            if '"kind": "trade"' not in line or '"symbol": "SPY"' not in line:
                continue
            try:
                rec = json.loads(line)
                ev = rec["event"]
                ts = datetime.fromisoformat(rec["ts_utc"]).replace(tzinfo=None)
            except (ValueError, KeyError):
                continue
            et = ts + ET_OFFSET
            hhmm = et.strftime("%H:%M")
            # stream_driven_worker drops every tick while the market is closed,
            # so the accumulator genuinely starts at the bell.
            if not (OPEN_ET <= hhmm < CLOSE_ET):
                continue
            day = et.date().isoformat()

            if day not in gens:
                gens[day] = SignalGenerator()
                states[day] = StrategyMarketState(underlying_symbol=symbol)
                last_eval[day] = None

            states[day].apply(ev)                    # REAL state accumulation

            # REAL eval cadence: at most one _update_history per _EVAL_INTERVAL.
            if last_eval[day] is not None and ts - last_eval[day] < _EVAL_INTERVAL:
                continue
            last_eval[day] = ts

            md = states[day].to_market_data()        # REAL snapshot
            if not md["price"] or md["price"] <= 0:
                continue
            gens[day]._update_history(               # REAL accumulator
                symbol, md["price"], md["volume"],
                cum_volume=md["cum_volume"], ts=ts,
            )

            if hhmm in SNAPSHOT_AT and hhmm not in snaps[day]:
                snaps[day][hhmm] = (
                    gens[day]._calculate_vwap(symbol),
                    gens[day]._calculate_vwap_wiggle(symbol),
                    gens[day]._vwap_accumulator_age_minutes(symbol),
                )
    return snaps


def session_track(bars):
    """{'HH:MM': (vwap, wiggle)} from minute bars, using the CLEAN price field."""
    spv = sv = spv2 = 0.0
    out = {}
    for b in bars:
        typ = b.get("price") or b["close"]
        v = b.get("volume") or 0
        spv += typ * v; sv += v; spv2 += typ * typ * v
        if sv <= 0:
            continue
        vw = spv / sv
        var = spv2 / sv - vw * vw
        out[b["time"][11:16]] = (vw, math.sqrt(var) if var > 0 else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=None)
    args = ap.parse_args()

    with open(BARS) as fh:
        barfile = json.load(fh)

    engine = {}
    for p in stream_files():
        for day, snap in replay(p).items():
            engine.setdefault(day, {}).update(snap)

    days = sorted(d for d in engine if d in barfile)
    if args.day:
        days = [d for d in days if d == args.day] or sys.exit(f"{args.day} not replayable")
    if not days:
        sys.exit("no overlap between stream logs and the bar file")

    print("=" * 92)
    print("ENGINE WIGGLE vs SESSION WIGGLE — is the live gate calibrated in the research's units?")
    print(f"  engine_wiggle : real SignalGenerator, real StrategyMarketState, {_EVAL_INTERVAL.total_seconds():.0f}s eval cadence")
    print("  session_wiggle: Tradier 1-minute bars, clean `price` field")
    print(f"  {len(days)} sessions: {days[0]} .. {days[-1]}")
    print("=" * 92)

    ratios_all = []
    print(f"\n{'day':<12}{'time':>7}{'engine':>9}{'session':>9}{'ratio':>8}{'age':>7}")
    for day in days:
        track = session_track(barfile[day])
        for hhmm in SNAPSHOT_AT:
            e = engine[day].get(hhmm)
            s = track.get(hhmm)
            if not e or not s or e[1] is None or s[1] is None or s[1] == 0:
                continue
            r = e[1] / s[1]
            ratios_all.append(r)
            print(f"{day:<12}{hhmm:>7}{e[1]:>9.3f}{s[1]:>9.3f}{r:>8.2f}{e[2]:>7.0f}")

    if not ratios_all:
        sys.exit("\nno comparable snapshots")

    med = statistics.median(ratios_all)
    print("\n" + "=" * 92)
    print(f"  n = {len(ratios_all)} snapshots across {len(days)} sessions")
    print(f"  ratio engine/session   median {med:.3f}   mean {statistics.fmean(ratios_all):.3f}"
          f"   min {min(ratios_all):.3f}   max {max(ratios_all):.3f}")
    if len(ratios_all) > 1:
        print(f"  spread (stdev)         {statistics.stdev(ratios_all):.3f}")
    print()
    # Direction of the conversion, derived rather than remembered -- the two
    # numbers below were printed the wrong way round until 2026-09-16:
    #   engine_wiggle          = med * session_wiggle
    #   engine blocks when     |d| >= T_engine * engine_wiggle
    #                          |d| >= T_engine * med * session_wiggle
    # so a live threshold T_engine equals T_engine * med in research units, and
    # reproducing a research threshold T needs T_engine = T / med.
    print("  WHAT THIS MEANS FOR THE THRESHOLD")
    print(f"    A stretch of 1.0 measured by the ENGINE corresponds to roughly")
    print(f"    {med:.2f} in the units every offline study used.")
    print(f"    To enforce the research's 1.0, vwap_max_stretch should be about {1/med:.2f}.")
    if abs(med - 1.0) < 0.05:
        print("    -> within 5%: 1.0 is 1.0. The threshold transfers as-is.")
    else:
        # med < 1 means the engine's wiggle is SMALLER, so the same threshold
        # trips at a shorter distance -- stricter, which is the safe direction.
        direction = "LOOSER" if med > 1.0 else "STRICTER"
        print(f"    -> NOT interchangeable. Setting 1.0 is {abs(1-med)*100:.0f}% {direction}")
        print("       than the research intends. Do not set 1.0 without adjusting.")
    print("=" * 92)


if __name__ == "__main__":
    main()

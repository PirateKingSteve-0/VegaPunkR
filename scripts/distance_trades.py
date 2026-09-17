#!/usr/bin/env python3
"""Were the replayed trades that entered STRETCHED from VWAP worse?

    ./venv/bin/python scripts/distance_trades.py

Written 2026-09-15. Companion to scripts/distance_test.py, which found on 20
sessions of SPY 1-minute bars that price 0.5-2 "wiggles" from VWAP tends to drift
back toward it over the next 30 minutes. This checks the same thing against our
own trades: every round trip scripts/replay_session.py rebuilds from the live
logs, tagged with how far SPY sat from VWAP at the moment of entry.

SPY bars are rebuilt from the recorded stream (logs/livetest-*/stream-*.jsonl):
close = last print of the minute, bar price = mean print price, bar volume = the
exchange cumulative counter differenced across the minute. VWAP and the wiggle
are then built exactly as in distance_test.py. Where the 20-day minute file
overlaps a session, the two are compared and printed so the rebuild can be
checked rather than trusted.

"Stretch" is signed in the TRADE's direction: a call entered with SPY 1.2 wiggles
ABOVE VWAP and a put entered 1.2 wiggles BELOW both read +1.2 — both chasing.

Read-only. Reads log files and prints.
"""
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_session as rs  # noqa: E402
import distance_test as dt   # noqa: E402

REPO = rs.REPO


# The SPY-bar rebuild and the VWAP/wiggle track moved into replay_session.py so
# that this script's buckets and replay_session's --max-stretch gate cannot end
# up disagreeing about how far from VWAP a given entry was. Same functions, one
# definition.
spy_bars = rs.spy_bars
vwap_track = rs.vwap_track


def main():
    cfg = dict(stop=rs.DEFAULTS["stop"], target=rs.DEFAULTS["target"],
               trail_arm=rs.DEFAULTS["trail_arm"], trail_distance=rs.DEFAULTS["trail_distance"],
               trail=rs.DEFAULTS["trail"], cooldown=0.5, loss_cooldown=0.0, max_per_day=0,
               entry_start_t=rs.parse_hhmm(rs.DEFAULTS["entry_start"]),
               entry_end_t=rs.parse_hhmm(rs.DEFAULTS["entry_end"]),
               exit_by_t=rs.parse_hhmm(rs.DEFAULTS["entry_end"]))

    pairs = []
    for d in sorted(__import__("glob").glob(os.path.join(REPO, "logs", "livetest-*"))):
        pairs.extend(rs.find_pairs(d))
    trades, unresolved, _ = rs.replay(pairs, cfg)

    bars, tracks = {}, {}
    for _, st in pairs:
        for day, b in spy_bars(st).items():
            if len(b) > len(bars.get(day, {})):
                bars[day] = b
    for day, b in bars.items():
        tracks[day] = vwap_track(b)

    # ---- check the rebuild against the independent 20-day minute file --------
    ref = json.load(open(dt.DATA))
    print("=" * 90)
    print("REBUILD CHECK — session_wiggle from our stream vs the Tradier 1-minute file")
    print("  Both sides are MINUTE BARS. Neither is the engine's tick-accumulated")
    print("  engine_wiggle, so nothing here says what the live gate would have seen.")
    print("  Our rebuild is the validated side: bar closes match the file to $0.003")
    print("  mean abs error on all 9 days, volume to 1.00x, range exactly.")
    for day in sorted(tracks):
        if day not in ref:
            print("  %s  (not in the minute file — stream rebuild only)" % day)
            continue
        rb = {b["time"][11:16]: b for b in ref[day]}
        spv = sv = spv2 = 0.0
        diffs_v, diffs_w = [], []
        for hhmm in sorted(rb):
            b = rb[hhmm]
            # `price`, NOT `vwap`. The file's per-bar `vwap` field is corrupt:
            # 1.3% of bars on 09-02 rising to 11.5% on 09-10 and 10.5% on 09-11
            # sit outside their own [low, high], which is structurally impossible
            # (09-11 14:21: vwap 760.95 against low 765.20). Reading it here is
            # what made this very check appear to condemn OUR rebuild on exactly
            # the two days that carried the stretch-gate result — see TODO.md G4b.
            # `price` is the bar midpoint, (high+low)/2 on 3510 of 3510 bars: a
            # standard typical price, and less endpoint-biased than `close` on a
            # trending minute. It was NOT chosen for sitting inside [low, high] —
            # a midpoint cannot fail that test.
            typ = b.get("price") or b["close"]
            spv += typ * b["volume"]; sv += b["volume"]; spv2 += typ * typ * b["volume"]
            if hhmm in ("10:30", "12:00", "15:00") and hhmm in tracks[day] and sv:
                vw = spv / sv
                w = math.sqrt(max(0.0, spv2 / sv - vw * vw))
                diffs_v.append(abs(tracks[day][hhmm][0] - vw))
                diffs_w.append((tracks[day][hhmm][1], w))
        print("  %s  VWAP differs by avg $%.3f | wiggle ours vs file at 10:30/12:00/15:00: %s"
              % (day, statistics.mean(diffs_v) if diffs_v else float("nan"),
                 "  ".join("%.2f/%.2f" % p for p in diffs_w)))

    # ---- tag every replayed trade ---------------------------------------------
    rows = []
    for t in trades:
        et = t["entry_ts"] + rs.ET_OFFSET
        day = et.date().isoformat()
        tr = tracks.get(day)
        if not tr:
            continue
        # Last COMPLETED minute before entry: what the strategy could have known.
        prev = (et.replace(second=0, microsecond=0) - timedelta(minutes=1)).strftime("%H:%M")
        if prev not in tr or tr[prev][1] <= 0:
            continue
        vw, wig = tr[prev]
        spot = bars[day][prev][1]
        side = 1 if t["strategy"] == 3 else -1
        stretch = side * (spot - vw) / wig
        later = (et.replace(second=0, microsecond=0) + timedelta(minutes=30)).strftime("%H:%M")
        spy30 = None
        if later in bars[day]:
            spy30 = side * (bars[day][later][1] - spot) / spot * 1e4
        rows.append(dict(day=day, stretch=stretch, ret=t["ret"], pnl=t["pnl"],
                         wig=wig, gap=spot - vw, spy30=spy30, sid=t["strategy"]))

    print()
    print("=" * 90)
    print("REPLAYED TRADES BY STRETCH FROM VWAP AT ENTRY  (%d trades, %d sessions; %d unresolved excluded)"
          % (len(rows), len({r['day'] for r in rows}), unresolved))
    print("  stretch is in the trade's direction: + = chasing (call above VWAP / put below)")
    print("  %-24s %4s %6s %10s %12s %14s %13s" % (
        "stretch at entry", "n", "win%", "avg trade", "$/contract", "SPY +30m your", "avg $ from"))
    print("  %-24s %4s %6s %10s %12s %14s %13s" % ("", "", "", "", "total", "way (bp)", "VWAP"))
    groups = [("against the rule (<0)", lambda s: s < 0)]
    groups += [(label.strip(), (lambda lo, hi: (lambda s: lo <= s < hi))(lo, hi))
               for (lo, hi), (_, label) in zip(
                   [(0, .5), (.5, 1), (1, 2), (2, math.inf)], dt.BUCKETS)]
    for label, sel in groups:
        g = [r for r in rows if sel(r["stretch"])]
        if not g:
            print("  %-24s %4d" % (label, 0))
            continue
        s30 = [r["spy30"] for r in g if r["spy30"] is not None]
        print("  %-24s %4d %5.0f%% %+9.2f%% %12s %+14.2f %12s" % (
            label, len(g), 100 * sum(r["ret"] > 0 for r in g) / len(g),
            statistics.mean(r["ret"] for r in g), format(sum(r["pnl"] for r in g), "+,.0f"),
            statistics.mean(s30) if s30 else float("nan"),
            "$%.2f" % statistics.mean(abs(r["gap"]) for r in g)))

    # A two-way split with more trades per side than the four buckets allow.
    print()
    near = [r for r in rows if r["stretch"] < 0.5]
    far = [r for r in rows if r["stretch"] >= 0.5]
    for label, g in (("under 0.5 wiggle", near), ("0.5 wiggle or more", far)):
        if len(g) < 2:
            continue
        m = statistics.mean(r["ret"] for r in g)
        se = statistics.stdev(r["ret"] for r in g) / math.sqrt(len(g))
        print("  %-20s n=%-4d win %3.0f%%  avg %+6.2f%% per trade  (95%% CI %+.2f .. %+.2f)"
              % (label, len(g), 100 * sum(r["ret"] > 0 for r in g) / len(g), m, m - 1.98 * se, m + 1.98 * se))
    if near and far:
        diff = statistics.mean(r["ret"] for r in far) - statistics.mean(r["ret"] for r in near)
        se = math.sqrt(statistics.variance([r["ret"] for r in far]) / len(far)
                       + statistics.variance([r["ret"] for r in near]) / len(near))
        print("  stretched minus near: %+.2f points per trade (95%% CI %+.2f .. %+.2f)"
              % (diff, diff - 1.98 * se, diff + 1.98 * se))
    print()
    print("  per session:")
    for day in sorted({r["day"] for r in rows}):
        g = [r for r in rows if r["day"] == day]
        print("    %s  n=%-3d median stretch %+.2f  avg trade %+6.2f%%"
              % (day, len(g), statistics.median(r["stretch"] for r in g),
                 statistics.mean(r["ret"] for r in g)))


if __name__ == "__main__":
    main()

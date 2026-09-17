#!/usr/bin/env python3
"""What did last night's two entry gates actually do today?

    ./venv/bin/python scripts/gate_review.py                  # newest session
    ./venv/bin/python scripts/gate_review.py --session logs/livetest-2026-09-16

WHY A RECONSTRUCTION RATHER THAN A REPLAY
-----------------------------------------
`replay_session.py` replays the `ENTRY SIGNAL:` lines an engine actually wrote.
A BLOCKED entry never writes one — `check_entry_signal` returns None before the
log line — so the gates' work is invisible to it. On 2026-09-16 the live engine
logged exactly ONE signal all day; the interesting question is what the other
minutes were doing.

So this rebuilds the decision from the recorded SPY tape instead: one 1-minute
bar at a time, the same gate chain in the same order, and every minute labelled
with the FIRST gate that would have stopped it. Then it re-runs the day four
ways — both gates, each alone, neither — and prices the differences against the
recorded option quotes.

FAITHFUL, NOT IDENTICAL. The live engine is tick-driven (one evaluation a
second, indicators accumulated per tick); this walks completed minutes. The
precedent for how close that lands is TODO.md G3: a reconstruction of the old
stack hit 44.0% against the live engine's 45.6%. Treat counts as ±1 and the
shape as real. The self-check below is the honest test of that: it reports
whether the reconstruction reproduces the trade the engine actually took.

WHAT CANNOT BE PRICED. A contract is only streamed while it is ARMED, so a
hypothetical entry can only be priced when quotes exist for the contract armed
at that moment. On 09-16 the put stopped streaming at 10:37 ET (the exit) while
the call ran to the close — so afternoon put counterfactuals are directional
only. Those are counted separately and never silently dropped.

Read-only: reads logs, prints.
"""
import argparse
import glob
import os
import re
import statistics
import sys
from bisect import bisect_right
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_session as rs  # noqa: E402

REPO = rs.REPO
SELECT_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \w+ engine\.stream_driven_worker: "
    r"Selected (?:put|call) for \S+: (?P<opt>\S+)")

# Live prod params on strategies 3 and 4, 2026-09-16.
EMA_PERIOD = 9
VOL_LOOKBACK, VOL_MULT = 20, 1.5
ENTRY_START, ENTRY_END = "10:00", "15:45"     # entry_after_open_minutes 30
ENTRY_BEFORE = "11:30"                        # entry_before_et
MAX_STRETCH = 1.0                             # vwap_max_stretch
REENTRY_COOLDOWN_MIN = 0.5                    # strategy_executor 30s
EXIT_CFG = dict(stop=15.0, target=25.0, trail_arm=15.0, trail_distance=10.0,
                trail=True, exit_by_t=rs.parse_hhmm(ENTRY_END))


def load_arming(engine_log):
    """[(ts_et, symbol)] — what the worker armed, in order."""
    out = []
    with open(engine_log, errors="ignore") as fh:
        for line in fh:
            m = SELECT_RE.match(line)
            if m:
                # engine logs in host local (PT); ET is what every rule speaks.
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                out.append((ts + rs.PT_TO_UTC + rs.ET_OFFSET, m.group("opt")))
    return out


def armed_at(arming, ts_et, side):
    """The contract armed for this side at ts_et, or None."""
    want = "C00" if side > 0 else "P00"
    best = None
    for ts, sym in arming:
        if ts <= ts_et and want in sym:
            best = sym
    return best


def ema_series(closes, period):
    """Mirror _calculate_ema: seeded on the oldest bar held, capped at 100."""
    out = []
    for i in range(len(closes)):
        window = closes[max(0, i - 99):i + 1]
        if len(window) < period:
            out.append(None)
            continue
        k = 2 / (period + 1)
        e = window[0]
        for p in window[1:]:
            e = p * k + e * (1 - k)
        out.append(e)
    return out


def build(session_dir):
    pairs = rs.find_pairs(session_dir)
    if not pairs:
        raise SystemExit("no engine/stream log pair in %s" % session_dir)
    engine_log, stream = max(pairs, key=lambda p: os.path.getsize(p[1]))
    bars_by_day = rs.spy_bars(stream)
    day = max(bars_by_day, key=lambda d: len(bars_by_day[d]))
    bars = bars_by_day[day]
    return day, bars, rs.vwap_track(bars), rs.load_quotes(stream), load_arming(engine_log), engine_log


def minutes(day, bars, track):
    """Per minute: price, ema, vwap, wiggle, volume ratio, stretch."""
    hhmms = sorted(bars)
    closes = [bars[h][1] for h in hhmms]
    emas = ema_series(closes, EMA_PERIOD)
    rows = []
    for i, h in enumerate(hhmms):
        vols = [bars[x][2] for x in hhmms[max(0, i - VOL_LOOKBACK + 1):i + 1]]
        ratio = (bars[h][2] / statistics.mean(vols)
                 if len(vols) == VOL_LOOKBACK and statistics.mean(vols) > 0 else None)
        vwap, wig = track.get(h, (None, None))
        stretch = (abs(closes[i] - vwap) / wig) if (vwap and wig) else None
        rows.append(dict(hhmm=h, ts=datetime.strptime(day + " " + h, "%Y-%m-%d %H:%M"),
                         price=closes[i], ema=emas[i], vwap=vwap, wiggle=wig,
                         ratio=ratio, stretch=stretch))
    return rows


def would_fire(row, side):
    """The three indicator gates, in engine order. None = data not ready."""
    if row["ema"] is None or row["vwap"] is None or row["ratio"] is None:
        return None
    if side > 0 and not (row["price"] > row["ema"] and row["price"] > row["vwap"]):
        return False
    if side < 0 and not (row["price"] < row["ema"] and row["price"] < row["vwap"]):
        return False
    return row["ratio"] >= VOL_MULT


def quote_at(ticks, ts_et):
    """(mid, bid, ask) from the last quote at or before ts_et, or None."""
    if not ticks:
        return None
    ts_utc = ts_et - rs.ET_OFFSET
    i = bisect_right([t for t, _, _ in ticks], ts_utc) - 1
    if i < 0:
        return None
    _, bid, ask = ticks[i]
    if bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / 2.0, bid, ask


def run_day(rows, quotes, arming, use_wall, use_stretch, day):
    """Walk the session under one gate configuration.

    Returns (trades, blocked) where blocked counts the FIRST gate that stopped
    each would-fire minute — first, because a minute stopped by the 11:30 wall
    cannot also be credited to the stretch gate, and double-counting is how a
    gate looks busier than it is.
    """
    start, end = rs.parse_hhmm(ENTRY_START), rs.parse_hhmm(ENTRY_END)
    wall = rs.parse_hhmm(ENTRY_BEFORE)
    busy = {1: datetime.min, -1: datetime.min}
    trades, blocked = [], {"wall": 0, "stretch": 0, "no_quote": 0, "busy": 0, "window": 0}
    for row in rows:
        for side in (1, -1):
            if not would_fire(row, side):
                continue
            t = row["ts"].time()
            if not (start <= t < end):
                blocked["window"] += 1
                continue
            if use_wall and t >= wall:
                blocked["wall"] += 1
                continue
            if row["ts"] < busy[side]:
                blocked["busy"] += 1
                continue
            if use_stretch:
                if row["stretch"] is None or row["stretch"] >= MAX_STRETCH:
                    blocked["stretch"] += 1
                    continue
            sym = armed_at(arming, row["ts"], side)
            q = quote_at(quotes.get(sym), row["ts"]) if sym else None
            if q is None:
                blocked["no_quote"] += 1
                continue
            mid = q[0]
            ticks = quotes[sym]
            i = bisect_right([x[0] for x in ticks], row["ts"] - rs.ET_OFFSET)
            res = rs.walk_exit(iter(ticks[i:]), row["ts"] - rs.ET_OFFSET, mid, EXIT_CFG)
            if res is None:
                blocked["no_quote"] += 1
                continue
            xts, xpx, why = res
            busy[side] = (xts + rs.ET_OFFSET) + timedelta(minutes=REENTRY_COOLDOWN_MIN)
            if why == "unresolved":
                blocked["no_quote"] += 1
                continue
            trades.append(dict(side=side, sym=sym, entry_et=row["ts"], exit_et=xts + rs.ET_OFFSET,
                               entry=mid, exit=xpx, why=why, stretch=row["stretch"],
                               pnl=(xpx - mid) * 100.0,
                               ret=(xpx - mid) / mid * 100.0))
    return trades, blocked


def show(label, trades, blocked):
    pnl = sum(t["pnl"] for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    print("  %-34s %2d trades  %2d won  %+8s   (wall %d, stretch %d, busy %d, unpriceable %d)"
          % (label, len(trades), wins, format(pnl, "+,.0f"),
             blocked["wall"], blocked["stretch"], blocked["busy"], blocked["no_quote"]))


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--session", help="logs/livetest-YYYY-MM-DD (default: newest)")
    a = p.parse_args()
    d = a.session or max(glob.glob(os.path.join(REPO, "logs", "livetest-*")))
    day, bars, track, quotes, arming, engine_log = build(d)
    rows = minutes(day, bars, track)

    print("=" * 100)
    print("GATE REVIEW — %s   (reconstruction from the recorded tape, not a log replay)" % day)
    print("  %s | %d SPY minutes | armed: %s"
          % (os.path.relpath(engine_log, REPO), len(rows),
             ", ".join("%s@%s" % (s, t.strftime("%H:%M")) for t, s in arming)))
    print("  live config: entries %s-%s ET, wall %s ET, max stretch %.1f, volume >= %.1fx"
          % (ENTRY_START, ENTRY_END, ENTRY_BEFORE, MAX_STRETCH, VOL_MULT))
    print("=" * 100)

    print()
    print("THE DAY RE-RUN FOUR WAYS  (dollars are per 1 contract, exits on the recorded bid)")
    configs = [("both gates on (what ran today)", True, True),
               ("without the 11:30 wall", False, True),
               ("without the don't-chase gate", True, False),
               ("neither gate (last week's engine)", False, False)]
    results = {}
    for label, w, s in configs:
        tr, bl = run_day(rows, quotes, arming, w, s, day)
        results[label] = (tr, bl)
        show(label, tr, bl)

    live = results["both gates on (what ran today)"][0]
    print()
    print("SELF-CHECK — does the reconstruction reproduce the engine's real trade?")
    print("  real:  10:07 ET put SPY260916P00760000 in 2.52 -> out 2.61  trailing stop  +$9")
    if live:
        for t in live:
            print("  recon: %s ET %s %s in %.2f -> out %.2f  %s  %+.0f  (stretch %.2f)"
                  % (t["entry_et"].strftime("%H:%M"), "call" if t["side"] > 0 else "put",
                     t["sym"], t["entry"], t["exit"], t["why"], t["pnl"], t["stretch"]))
    else:
        print("  recon: NO trade — reconstruction disagrees with the engine, read results with care")

    print()
    print("WHAT THE WALL BLOCKED — minutes the rule wanted in after 11:30 ET")
    nowall = results["without the 11:30 wall"][0]
    extra = [t for t in nowall if t["entry_et"].time() >= rs.parse_hhmm(ENTRY_BEFORE)]
    if not extra:
        print("  none priceable")
    for t in extra:
        print("  %s -> %s  %-4s %-22s in %.2f out %.2f  %-14s %+7.0f  stretch %.2f"
              % (t["entry_et"].strftime("%H:%M"), t["exit_et"].strftime("%H:%M"),
                 "call" if t["side"] > 0 else "put", t["sym"], t["entry"], t["exit"],
                 t["why"], t["pnl"], t["stretch"]))
    if extra:
        print("  --> the wall cost %s by not taking these" % format(sum(t["pnl"] for t in extra), "+,.0f"))

    print()
    print("WHAT THE DON'T-CHASE GATE BLOCKED — would-fire minutes at >= %.1f wiggles" % MAX_STRETCH)
    chased = [t for t in results["without the don't-chase gate"][0]
              if t["stretch"] is not None and t["stretch"] >= MAX_STRETCH]
    if not chased:
        print("  none priceable")
    for t in chased:
        print("  %s -> %s  %-4s %-22s in %.2f out %.2f  %-14s %+7.0f  stretch %.2f"
              % (t["entry_et"].strftime("%H:%M"), t["exit_et"].strftime("%H:%M"),
                 "call" if t["side"] > 0 else "put", t["sym"], t["entry"], t["exit"],
                 t["why"], t["pnl"], t["stretch"]))
    if chased:
        print("  --> the gate cost %s by not taking these" % format(sum(t["pnl"] for t in chased), "+,.0f"))

    print()
    print("STRETCH THROUGH THE DAY — where the rule wanted to buy, in wiggles")
    print("  %-7s %6s %8s %8s %7s %6s  %s" % ("ET", "SPY", "vwap", "wiggle", "stretch", "vol x", "rule wants"))
    for row in rows:
        if row["stretch"] is None:
            continue
        sides = [s for s in (1, -1) if would_fire(row, s)]
        if not sides or not (rs.parse_hhmm(ENTRY_START) <= row["ts"].time() < rs.parse_hhmm(ENTRY_END)):
            continue
        want = "/".join("call" if s > 0 else "put" for s in sides)
        flag = ""
        if row["ts"].time() >= rs.parse_hhmm(ENTRY_BEFORE):
            flag += "  [after 11:30]"
        if row["stretch"] >= MAX_STRETCH:
            flag += "  [chasing]"
        print("  %-7s %6.2f %8.2f %8.2f %7.2f %6.2f  %s%s"
              % (row["hhmm"], row["price"], row["vwap"], row["wiggle"], row["stretch"],
                 row["ratio"] or 0, want, flag))


if __name__ == "__main__":
    main()

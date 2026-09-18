#!/usr/bin/env python3
"""Does DISTANCE from VWAP / the 9-minute EMA say anything about SPY's next move?

    ./venv/bin/python scripts/distance_test.py
    ./venv/bin/python scripts/distance_test.py --perms 2000 --seed 7

Written 2026-09-14 for TODO.md G4b. The engine's VWAP and EMA gates are yes/no —
a penny above and $3 above pass identically. This measures whether HOW FAR price
sits from each line predicts where SPY goes over the next 15 / 30 minutes.

Measured on the underlying (data/backtest/underlying/SPY_1min.json — every session
in that file, 24 as of 2026-09-16; scripts/fetch_1min_bars.py tops it up),
not on options — so it answers "does this carry directional information", not
"does an options trade on it make money". Read-only, stdlib only.

DISTANCE IS IN "WIGGLES", NOT DOLLARS
-------------------------------------
  VWAP  (close - session VWAP) / volume-weighted standard deviation of price
        around VWAP since the open. The usual VWAP-band construction.
  EMA   (close - 9-minute EMA) / standard deviation of that same gap over the
        previous 20 minutes (current minute excluded, so a sudden jump is not
        shrunk by its own size).

CUTOFFS ARE FIXED HERE, BEFORE ANY RESULT WAS SEEN. Do not tune them against the
output — trying cutoffs until one looks good manufactures a pattern. The split
half and the shuffle test exist to catch exactly that.

HOW TO READ "WITH THE STRETCH"
------------------------------
Every minute is folded so the sign means one thing: positive bp = price kept
moving AWAY from the line (runaway train), negative = it came back toward the line
(rubber band). Folding also cancels most of the tape's own drift, since above-line
and below-line minutes get pushed in opposite directions by it.

Minutes overlap heavily (a 30-minute look-ahead from 10:00 and from 10:01 share
29 minutes), so every confidence interval treats the DAY as the independent unit.
"""
import argparse
import json
import math
import os
import random
import statistics
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def data_path(symbol):
    return os.path.join(REPO, "data", "backtest", "underlying", "%s_1min.json" % symbol.upper())


# Kept for callers that import it (distance_trades.py reads it as the SPY reference).
DATA = data_path("SPY")

ENTRY_START, ENTRY_END = "10:00", "15:45"       # live strategy window, ET
HORIZONS = (15, 30)                              # minutes ahead
EMA_PERIOD, EMA_WINDOW = 9, 100                  # engine: 9 bars, deque of 100
EMA_SD_LOOKBACK = 20
VOL_LOOKBACK, VOL_MULT = 20, 1.5                 # engine volume gate, template value

# Fixed before looking. Upper edges, in wiggles.
BUCKETS = [(0.5, "on the line  (<0.5)"),
           (1.0, "a bit away   (0.5-1)"),
           (2.0, "clearly away (1-2)"),
           (math.inf, "far away     (>2)")]


def bucket_of(absz):
    for i, (edge, _) in enumerate(BUCKETS):
        if absz < edge:
            return i
    return len(BUCKETS) - 1


def engine_ema(closes):
    """Mirror signal_generator._calculate_ema: seed with the oldest bar held."""
    window = closes[-EMA_WINDOW:]
    if len(window) < EMA_PERIOD:
        return None
    k = 2 / (EMA_PERIOD + 1)
    ema = window[0]
    for p in window[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def build_minutes(data):
    """One row per minute in the entry window with both distances and outcomes."""
    rows = []
    for day in sorted(data):
        bars = data[day]
        closes = [b["close"] for b in bars]
        spv = sv = spv2 = 0.0
        gaps = []
        for i, b in enumerate(bars):
            # NOT b["vwap"]: that field in the Tradier 1-minute file is
            # corrupt. On 3,510 bars across 9 sessions it falls OUTSIDE the
            # bar's own [low, high] on 1.3%-11.5% of minutes depending on the
            # day -- e.g. 2026-09-11 14:21 reports vwap 760.95 for a bar whose
            # low is 765.20. The bad-bar rate tracks the days where a VWAP
            # rebuilt from it diverges from one rebuilt from our own stream
            # (09-02 at 1.3% agrees; 09-10 and 09-11 at ~11% do not), which is
            # what that divergence turned out to be -- a defect in the
            # reference, not in our capture and not in the engine.
            #
            # `price` is the bar midpoint, (high + low) / 2, exactly on all
            # 3,510 bars. It is chosen over `close` because HL2 is a standard
            # typical price and is less endpoint-biased on a trending minute;
            # NOT because it passes a range check, which a midpoint cannot fail.
            #
            # The finding does not depend on the choice -- >1 wiggle at +30m is
            # -1.54 bp with the corrupt field, -1.63 with close, -1.65 with
            # price, p = 0.000 in all three. Fixed for correctness, not to move
            # the result. This is `session_wiggle`; the engine's tick-level
            # `engine_wiggle` is a different construction and still unmeasured.
            typ = b.get("price") or b["close"]
            v = b["volume"] or 0
            spv += typ * v
            sv += v
            spv2 += typ * typ * v
            ema = engine_ema(closes[: i + 1])
            gaps.append(None if ema is None else b["close"] - ema)

            hhmm = b["time"][11:16]
            if not (ENTRY_START <= hhmm < ENTRY_END) or sv <= 0:
                continue
            vwap = spv / sv
            vsd = math.sqrt(max(0.0, spv2 / sv - vwap * vwap))
            prior = [g for g in gaps[max(0, i - EMA_SD_LOOKBACK):i] if g is not None]
            esd = statistics.pstdev(prior) if len(prior) >= EMA_SD_LOOKBACK else 0.0
            if vsd <= 0 or esd <= 0 or ema is None:
                continue

            vols = [x["volume"] for x in bars[max(0, i - VOL_LOOKBACK + 1): i + 1]]
            vol_ratio = (v / statistics.mean(vols)
                         if len(vols) == VOL_LOOKBACK and statistics.mean(vols) > 0 else 0.0)

            fwd = {}
            for h in HORIZONS:
                if i + h < len(bars):
                    fwd[h] = (closes[i + h] - b["close"]) / b["close"] * 1e4
            price = b["close"]
            rule = None
            if vol_ratio >= VOL_MULT:
                if price > ema and price > vwap:
                    rule = +1          # call strategy would fire
                elif price < ema and price < vwap:
                    rule = -1          # put strategy would fire
            rows.append(dict(day=day, hhmm=hhmm,
                             z={"VWAP": (price - vwap) / vsd, "EMA": (price - ema) / esd},
                             fwd=fwd, rule=rule))
    return rows


def clustered(obs):
    """obs = [(day, value)]. Mean with a day-clustered 95% CI."""
    n = len(obs)
    if n == 0:
        return None
    m = sum(x for _, x in obs) / n
    by = defaultdict(float)
    for d, x in obs:
        by[d] += x - m
    g = len(by)
    se = math.sqrt(sum(s * s for s in by.values())) / n * (math.sqrt(g / (g - 1)) if g > 1 else 0)
    return m, m - 2.09 * se, m + 2.09 * se, g


def folded_table(rows, line, h, days=None, rule_only=False):
    """Per bucket: n, % kept going, avg bp with the stretch (CI), days present."""
    out = []
    for bi in range(len(BUCKETS)):
        obs, hits = [], 0
        for r in rows:
            if days is not None and r["day"] not in days:
                continue
            if h not in r["fwd"]:
                continue
            z = r["z"][line]
            if rule_only:
                if r["rule"] is None:
                    continue
                side = r["rule"]          # the trade's direction, not the stretch's
                if (z > 0) != (side > 0):
                    continue              # cannot happen for VWAP/EMA-gated fires
            else:
                side = 1 if z >= 0 else -1
            if bucket_of(abs(z)) != bi:
                continue
            x = side * r["fwd"][h]
            obs.append((r["day"], x))
            hits += x > 0
        out.append((obs, hits))
    return out


def print_table(title, table, needed_bp=None):
    print(title)
    print("    %-22s %6s %5s %9s  %-20s %5s" % ("distance", "min", "days", "kept going",
                                                "avg bp with stretch", "(95% CI, by day)"))
    for (obs, hits), (_, label) in zip(table, BUCKETS):
        c = clustered(obs)
        if c is None:
            print("    %-22s %6d   (none)" % (label, 0))
            continue
        m, lo, hi, g = c
        flag = "" if lo <= 0 <= hi else ("  <- keeps going" if lo > 0 else "  <- comes back")
        print("    %-22s %6d %5d %8.1f%%  %+6.2f   (%+6.2f .. %+6.2f)%s" % (
            label, len(obs), g, hits / len(obs) * 100, m, lo, hi, flag))


def shuffle_pvalue(rows, line, h, perms, rng):
    """Is the far-bucket number beyond what chance produces?

    Null: distance carries no information about the next move. Within each day
    the outcome series is rotated by a random offset relative to the distance
    series. Rotation keeps each series' own smoothness (both are heavily
    autocorrelated minute to minute) and keeps each day's drift, and only breaks
    the pairing between them. Statistic: avg bp with the stretch, >1 wiggle.
    """
    by_day = defaultdict(list)
    for r in rows:
        if h in r["fwd"]:
            by_day[r["day"]].append((r["z"][line], r["fwd"][h]))

    def stat(pairs_by_day):
        tot = n = 0
        for pairs in pairs_by_day:
            for z, f in pairs:
                if abs(z) >= 1.0:
                    tot += (1 if z >= 0 else -1) * f
                    n += 1
        return tot / n if n else 0.0

    actual = stat(by_day.values())
    null = []
    for _ in range(perms):
        rotated = []
        for pairs in by_day.values():
            k = len(pairs)
            s = rng.randrange(1, k) if k > 1 else 0
            zs = [z for z, _ in pairs]
            fs = [f for _, f in pairs]
            fs = fs[s:] + fs[:s]
            rotated.append(list(zip(zs, fs)))
        null.append(stat(rotated))
    extreme = sum(1 for x in null if abs(x - statistics.mean(null)) >= abs(actual - statistics.mean(null)))
    return actual, statistics.mean(null), (extreme + 1) / (perms + 1)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--perms", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260914)
    p.add_argument("--symbol", default="SPY",
                   help="reads data/backtest/underlying/<SYMBOL>_1min.json (fetch_1min_bars.py)")
    a = p.parse_args()
    sym = a.symbol.upper()

    data = json.load(open(data_path(sym)))
    rows = build_minutes(data)
    days = sorted(data)
    first, second = set(days[: len(days) // 2]), set(days[len(days) // 2:])
    up = sum(1 for d in days if data[d][-1]["close"] > data[d][0]["open"])
    rng = random.Random(a.seed)

    print("=" * 92)
    print("DISTANCE TEST — %s 1-minute bars, %d sessions %s .. %s (%d up, %d down, open->close)"
          % (sym, len(days), days[0], days[-1], up, len(days) - up))
    print("  minutes %s-%s ET | %d usable minutes | cutoffs fixed in code: 0.5 / 1 / 2 wiggles"
          % (ENTRY_START, ENTRY_END, len(rows)))
    print("  'avg bp with stretch': + = kept moving away from the line, - = came back toward it")
    last = data[days[-1]][-1]["close"]
    print("  1 bp = 0.01%% of price, about %.1f cents on %s at %.0f" % (last / 100, sym, last))
    print("=" * 92)

    for line in ("VWAP", "EMA"):
        for h in HORIZONS:
            print()
            print_table("[%s, all minutes, +%dm]" % (line, h), folded_table(rows, line, h))
        h = 30
        print()
        # Halves are len(days)//2, so the labels count themselves rather than
        # hardcoding 10 — the file grows every time fetch_1min_bars.py runs.
        print_table("  split check — first %d days (%s..%s), +30m"
                    % (len(first), min(first), max(first)),
                    folded_table(rows, line, h, days=first))
        print_table("  split check — last %d days (%s..%s), +30m"
                    % (len(second), min(second), max(second)),
                    folded_table(rows, line, h, days=second))
        for hh in HORIZONS:
            act, nm, pv = shuffle_pvalue(rows, line, hh, a.perms, rng)
            print("  shuffle test, >1 wiggle, +%dm: actual %+.2f bp vs chance %+.2f bp -> p = %.3f"
                  % (hh, act, nm, pv))

    print()
    print("=" * 92)
    print("ONLY MINUTES THE CURRENT RULE WOULD BUY  (price vs 9m EMA and VWAP agree, volume >= %.1fx)"
          % VOL_MULT)
    print("  sign here = the TRADE's direction: + means %s moved the way the call/put wanted" % sym)
    fired = [r for r in rows if r["rule"] is not None]
    print("  %d rule minutes (%d call, %d put)" % (
        len(fired), sum(1 for r in fired if r["rule"] > 0), sum(1 for r in fired if r["rule"] < 0)))
    for line in ("VWAP", "EMA"):
        for h in HORIZONS:
            print()
            print_table("[rule minutes, grouped by distance from %s, +%dm]" % (line, h),
                        folded_table(rows, line, h, rule_only=True))


if __name__ == "__main__":
    main()

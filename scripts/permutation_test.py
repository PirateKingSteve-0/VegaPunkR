#!/usr/bin/env python3
"""Permutation test: does the entry signal beat random entry times?

    ./venv/bin/python scripts/permutation_test.py
    ./venv/bin/python scripts/permutation_test.py --perms 5000 --seed 7
    ./venv/bin/python scripts/permutation_test.py --strata session

WHY THIS EXISTS
---------------
Eight sweeps of scripts/replay_session.py moved every exit and throttle knob and
all landed between -1% and -3% expectancy. That leaves two stories that the
replay alone cannot tell apart:

  (a) the entry picks bad moments, and good exits cannot rescue it, or
  (b) the entry is irrelevant — ANY moment loses about this much once the stop,
      the spread and time decay are paid, so no entry rule would rescue it.

The test: keep everything about each replayed trade EXCEPT the moment it was
entered. Swap that moment for a random one and run the identical exit walk.
Do this a few thousand times. If the real entries sit inside the pile of random
ones, the signal's timing carries no information. If they sit at the edge, it
does (in whichever direction).

WHAT IS SHUFFLED, WHAT IS HELD FIXED
------------------------------------
Shuffled:  the entry timestamp, and with it the entry price (the mid of the
           armed contract at that instant).

Held fixed, per trade:
  * session day and strategy (calls = 3, puts = 4) — so a random call on an
    up-drifting day gets the same tailwind the real call got. This is what
    neutralises the "all sessions drifted up" caveat.
  * the ET half-hour it was entered in (--strata bucket, the default) — premium
    falls ~4x through the day and decay/stop-room change with it
    (scripts/cost_budget.py), so an unstratified shuffle would mostly measure
    time of day, not the signal.
  * the contract-selection rule — a random entry buys whatever contract the
    engine had ARMED at that second, rebuilt from its own "Selected put/call"
    and "disarming" log lines. Contract choice is not part of what is tested.
  * the exit rules (stop / trail / target / forced exit / window), via the
    same walk_exit the replay uses.
  * the number of trades.

Pricing is identical for both arms: entry at the streamed mid, exits on the bid.
The replay's known optimism (mid entry, ~half-spread) therefore cancels in the
comparison, even though it does not cancel in the absolute expectancy figures.

KNOWN LIMITS
------------
  * Random entries are not forced to avoid overlapping each other within a
    strategy. That does not bias the per-trade mean under the null, but the
    random arm is not a tradable schedule.
  * Draws whose contract stops streaming before the exit resolves are redrawn,
    mirroring how the replay drops `unresolved` trades.
  * 6 sessions. A p-value here is about THIS tape, not the signal in general.

READ-ONLY. Reads log files and prints.
"""
import argparse
import bisect
import os
import random
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from itertools import islice

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_session as rs  # noqa: E402

REPO = rs.REPO

SELECT_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \w+ engine\.stream_driven_worker: "
    r"Selected (?:put|call) for \S+: (?P<opt>\S+)")
DISARM_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \w+ engine\.stream_driven_worker: "
    r"(?:Contract (?P<a>\S+) drifted out of criteria|"
    r"Strategy \d+: armed contract (?P<b>\S+) expired)")
STOP_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ \w+ engine\.stream_driven_worker: "
    r"StreamDrivenWorker stopped")

# A random entry needs a live quote to price off. The engine's own signals log
# quote_age=0s; a minute of silence means the contract is not really armed.
MAX_QUOTE_AGE = timedelta(seconds=60)
MAX_REDRAWS = 50


def _ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S") + rs.PT_TO_UTC


def load_arming(path):
    """{strategy: ([ts_utc...], [symbol-or-None...])} — what was armed when."""
    ev = {3: ([], []), 4: ([], [])}

    def push(ts, sid, sym):
        ev[sid][0].append(ts)
        ev[sid][1].append(sym)

    with open(path, errors="ignore") as fh:
        for line in fh:
            if "stream_driven_worker" not in line:
                continue
            m = SELECT_RE.match(line)
            if m:
                sym = m.group("opt")
                push(_ts(m.group(1)), rs.strategy_of(sym), sym)
                continue
            m = DISARM_RE.match(line)
            if m:
                sym = m.group("a") or m.group("b")
                push(_ts(m.group(1)), rs.strategy_of(sym), None)
                continue
            m = STOP_RE.match(line)
            if m:
                push(_ts(m.group(1)), 3, None)
                push(_ts(m.group(1)), 4, None)
    return ev


def armed_at(arming, sid, ts):
    times, syms = arming[sid]
    i = bisect.bisect_right(times, ts) - 1
    return syms[i] if i >= 0 else None


class Book:
    """Quotes for one session, indexed for 'latest quote at or before t'."""

    def __init__(self, quotes):
        self.q = quotes
        self.times = {s: [t for t, _, _ in v] for s, v in quotes.items()}

    def quote_index(self, sym, ts):
        times = self.times.get(sym)
        if not times:
            return None
        i = bisect.bisect_right(times, ts) - 1
        if i < 0 or ts - times[i] > MAX_QUOTE_AGE:
            return None
        _, bid, ask = self.q[sym][i]
        if bid <= 0 or ask <= 0:
            return None
        return i


def bucket_bounds(entry_ts, cfg, strata):
    """UTC [lo, hi) range a random replacement for this entry may be drawn from."""
    et = entry_ts + rs.ET_OFFSET
    day = et.date()
    win_lo = datetime.combine(day, cfg["entry_start_t"])
    win_hi = datetime.combine(day, cfg["entry_end_t"])
    if strata == "bucket":
        lo = et.replace(minute=0 if et.minute < 30 else 30, second=0, microsecond=0)
        hi = lo + timedelta(minutes=30)
        lo, hi = max(lo, win_lo), min(hi, win_hi)
    else:  # session: anywhere in that day's entry window
        lo, hi = win_lo, win_hi
    return lo - rs.ET_OFFSET, hi - rs.ET_OFFSET


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--perms", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260914)
    p.add_argument("--strata", choices=("bucket", "session"), default="bucket",
                   help="bucket = same ET half-hour (default); session = anywhere that day")
    p.add_argument("--cooldown", type=float, default=0.5)
    a = p.parse_args()

    cfg = dict(stop=rs.DEFAULTS["stop"], target=rs.DEFAULTS["target"],
               trail_arm=rs.DEFAULTS["trail_arm"],
               trail_distance=rs.DEFAULTS["trail_distance"], trail=rs.DEFAULTS["trail"],
               cooldown=a.cooldown, loss_cooldown=0.0, max_per_day=0,
               entry_start_t=rs.parse_hhmm(rs.DEFAULTS["entry_start"]),
               entry_end_t=rs.parse_hhmm(rs.DEFAULTS["entry_end"]),
               exit_by_t=rs.parse_hhmm(rs.DEFAULTS["entry_end"]))

    pairs = []
    for d in sorted(__import__("glob").glob(os.path.join(REPO, "logs", "livetest-*"))):
        pairs.extend(rs.find_pairs(d))

    # Load each stream file once and hand the same object to the replay.
    books, arming, cache = {}, {}, {}
    orig_load = rs.load_quotes

    def load_once(path):
        if path not in cache:
            print("  loading %s" % os.path.relpath(path, REPO), flush=True)
            cache[path] = orig_load(path)
        return cache[path]
    rs.load_quotes = load_once

    actual_raw, unresolved, _ = rs.replay(pairs, cfg)
    for lg, st in pairs:
        books[lg] = Book(cache[st])
        arming[lg] = load_arming(lg)

    # Attach each replayed trade to its session so both arms read the same book.
    sig_session = {}
    for lg, _ in pairs:
        for ts, sym, _mid in rs.load_signals(lg):
            sig_session[(ts, sym)] = lg

    walk_cache = {}

    def outcome(lg, sym, i):
        """Return % for entering at quote i of sym (mid), exit walk on the bid."""
        key = (lg, sym, i)
        if key not in walk_cache:
            ticks = books[lg].q[sym]
            ts, bid, ask = ticks[i]
            mid = (bid + ask) / 2.0
            res = rs.walk_exit(islice(ticks, i + 1, None), ts, mid, cfg)
            walk_cache[key] = (None if res is None or res[2] == "unresolved"
                               else (res[1] - mid) / mid * 100.0)
        return walk_cache[key]

    # ---- actual arm, re-priced off the stream exactly like the random arm ----
    actual, armed_match, mid_gaps = [], 0, []
    for t in actual_raw:
        lg = sig_session[(t["entry_ts"], t["symbol"])]
        if armed_at(arming[lg], t["strategy"], t["entry_ts"]) == t["symbol"]:
            armed_match += 1
        i = books[lg].quote_index(t["symbol"], t["entry_ts"])
        if i is None:
            continue
        r = outcome(lg, t["symbol"], i)
        if r is None:
            continue
        _, bid, ask = books[lg].q[t["symbol"]][i]
        mid_gaps.append(abs((bid + ask) / 2.0 - t["entry"]))
        lo, hi = bucket_bounds(t["entry_ts"], cfg, a.strata)
        actual.append(dict(lg=lg, sid=t["strategy"], ret=r, lo=lo, hi=hi))

    rng = random.Random(a.seed)

    def draw(tr):
        span = (tr["hi"] - tr["lo"]).total_seconds()
        for _ in range(MAX_REDRAWS):
            ts = tr["lo"] + timedelta(seconds=rng.random() * span)
            sym = armed_at(arming[tr["lg"]], tr["sid"], ts)
            if not sym:
                continue
            i = books[tr["lg"]].quote_index(sym, ts)
            if i is None:
                continue
            r = outcome(tr["lg"], sym, i)
            if r is not None:
                return r
        return None

    def stats(rets):
        return statistics.mean(rets), sum(1 for x in rets if x > 0) / len(rets) * 100

    groups = {"ALL": lambda tr: True,
              "CALLS (s3)": lambda tr: tr["sid"] == 3,
              "PUTS (s4)": lambda tr: tr["sid"] == 4}
    null = {g: ([], []) for g in groups}
    failed = 0
    print("  running %d permutations..." % a.perms, flush=True)
    for _ in range(a.perms):
        draws = [(tr, draw(tr)) for tr in actual]
        if any(r is None for _, r in draws):
            failed += 1
            continue
        for g, sel in groups.items():
            rets = [r for tr, r in draws if sel(tr)]
            if rets:
                m, w = stats(rets)
                null[g][0].append(m)
                null[g][1].append(w)

    print()
    print("=" * 96)
    print("PERMUTATION TEST — recorded entry times vs random times, identical exits")
    print("  %d sessions | %d replayed trades usable (of %d; %d unresolved dropped by replay)"
          % (len(pairs), len(actual), len(actual_raw), unresolved))
    print("  strata: %s | %d permutations (%d discarded: no priceable time in stratum) | seed %d"
          % ("same session + strategy + ET half-hour" if a.strata == "bucket"
             else "same session + strategy, anywhere 10:00-15:45 ET",
             a.perms, failed, a.seed))
    print("  exits: stop %.0f%% | trail arms +%.0f%% gives back %.0f%% | target %.0f%% | forced 15:45 ET"
          % (cfg["stop"], cfg["trail_arm"], cfg["trail_distance"], cfg["target"]))
    print("  sanity: armed-contract rebuild matches the signal's contract on %d of %d trades;"
          % (armed_match, len(actual_raw)))
    if mid_gaps:
        print("          stream mid vs engine-logged mid differs by $%.3f on average"
              % statistics.mean(mid_gaps))
    print("=" * 96)
    print("  %-11s %4s | %-17s | %-27s | %-27s" % (
        "", "n", "SIGNAL exp / win", "RANDOM exp (5th-95th pct)", "RANDOM win% (5th-95th)"))
    for g, sel in groups.items():
        rets = [tr["ret"] for tr in actual if sel(tr)]
        if not rets or not null[g][0]:
            continue
        m, w = stats(rets)
        nm = sorted(null[g][0])
        nw = sorted(null[g][1])
        k = len(nm)
        pct = lambda xs, q: xs[min(k - 1, int(q * k))]
        print("  %-11s %4d | %+6.2f%% / %4.1f%%  | %+6.2f%%  (%+6.2f .. %+6.2f)  | %4.1f%%  (%4.1f .. %4.1f)" % (
            g, len(rets), m, w, statistics.mean(nm), pct(nm, .05), pct(nm, .95),
            statistics.mean(nw), pct(nw, .05), pct(nw, .95)))
        better = (1 + sum(1 for x in nm if x >= m)) / (k + 1)
        worse = (1 + sum(1 for x in nm if x <= m)) / (k + 1)
        print("  %-11s      p(signal BETTER than random) = %.3f    p(signal WORSE than random) = %.3f"
              % ("", better, worse))
    print()
    print("  Read: a p below 0.05 on one side means the signal's timing is doing something")
    print("  on this tape. Both sides well above 0.05 means random times do about as well.")


if __name__ == "__main__":
    main()

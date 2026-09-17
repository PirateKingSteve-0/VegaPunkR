#!/usr/bin/env python3
"""What would dynamic take-profit / trailing-stop rules have done on our REAL trades?

    ./venv/bin/python scripts/dynamic_exits_review.py              # winning days only
    ./venv/bin/python scripts/dynamic_exits_review.py --all-days   # every day

Companion to docs/dynamic-exits-math.md. Unlike replay_session.py, which replays
SIGNALS the account could not afford, this starts from the round trips that were
actually filled (PROD `trades`, read-only): the real entry time, real fill price,
real quantity. Each is then walked forward over the held contract's recorded bid
under several exit rules, with the 15% stop loss held fixed so only the
profit-side rule changes.

Rules compared
  live         SL 15% | trail arms +15%, gives back 10% of peak | TP 25% (never
               reached: the trail arms first and suppresses it)
  keep 70%     SL 15% | trail arms +15%, exit if 30% of the peak GAIN is given back
  keep 50%     SL 15% | trail arms +15%, exit if 50% of the peak gain is given back
  vol trail    SL 15% | trail arms +15%, exit at peak − 0.5 × delta × σ10, where σ10
               is SPY's typical 10-minute move from the trailing 30 minutes (causal)
  dyn TP       SL 15% | no trail | fixed target = entry + 2 × delta × σ30 at entry
  TP+trail     dyn TP's target, PLUS the live trail underneath it (target NOT suppressed
               when the trail arms — unlike the live engine's flat TP)
  TP+BE        dyn TP's target, PLUS a break-even stop: once up +15%, the stop moves to entry
  struct       STRUCTURE STOP + the live trail + the 15% floor. Definitions fixed on
               2026-09-17 BEFORE any result was seen, and not to be tuned against these trades:
                 - levels come from SPY 1-minute bars (completed bars only), not the option
                 - a swing low is a bar whose low is below the lows of the 2 bars on each side
                   (confirmed only once those 2 later bars have closed); for PUTS it is the
                   mirror, a swing high
                 - only swings whose pivot bar is at or after the entry minute count
                 - stop = swing low − 0.25 × typical 10-minute SPY move (puts: swing high + it)
                 - it only ever moves in the trade's favour (calls up, puts down)
                 - it fires when a completed 1-minute SPY bar CLOSES beyond it; the exit is the
                   option bid on the next tick
                 - the 15% option stop stays as the floor; the live trail stays on
  literal      the owner's first wording, for contrast: the stop is the lowest option bid
               seen since entry, so it sells on the first new low. + 15% floor + live trail.

UNRESOLVED IS NOT ZERO. A contract is only recorded while armed. When a rule would
hold longer than the real trade and the recording stops first, the outcome is
unknown — reported as "?" and excluded from that rule's total, never counted flat.

Read-only: one SELECT against PROD, then log files.
"""
import argparse
import collections
import glob
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, time as dtime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_session as rs  # noqa: E402

REPO = rs.REPO
STOP, ARM, GIVEBACK = 0.15, 0.15, 0.10
FORCED = dtime(15, 45)


def load_trips():
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text
    load_dotenv(os.path.join(REPO, ".env"))
    eng = create_engine(os.getenv("DATABASE_PROD_URL"))
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT timestamp, strategy_id, position_id, side, filled_qty, price, exit_price, pnl, notes "
            "FROM trades WHERE timestamp >= '2026-09-02' ORDER BY timestamp, id")).fetchall()
    buys, trips = {}, []
    for r in rows:
        if r.side == "buy":
            buys[(r.strategy_id, r.position_id)] = r
            continue
        b = buys.pop((r.strategy_id, r.position_id), None)
        if b is None:
            continue
        nb, ns = b.notes or {}, r.notes or {}
        trips.append(dict(
            entry_utc=b.timestamp, entry=float(b.price), qty=int(b.filled_qty or 1),
            exit_real=float(r.exit_price), pnl_real=float(r.pnl or 0),
            sym=ns.get("option_symbol") or nb.get("option_symbol"),
            delta=float((nb.get("indicators") or {}).get("delta") or 0.70),
            why=(ns.get("signal_reason") or "").split(":")[0]))
    return trips


# {et_date: {HH:MM: [open, high, low, close]}} of SPY 1-minute bars, filled by load_tape.
# Module-level so walk()'s signature (used by other callers) stays unchanged.
SPY_OHLC = collections.defaultdict(dict)


def load_tape(symbols):
    """{symbol: [(ts_utc, bid, ask)]} and {et_date: {HH:MM: close}} from every stream file.

    Also fills SPY_OHLC with 1-minute SPY bars for the structure stop."""
    quotes = collections.defaultdict(list)
    spy = collections.defaultdict(dict)
    files = [f for f in glob.glob(os.path.join(REPO, "logs", "livetest-*", "stream-*.jsonl"))
             if os.path.getsize(f) > 100_000]
    for f in sorted(files):
        with open(f, errors="ignore") as fh:
            for line in fh:
                hit = next((s for s in symbols if s in line), None)
                if hit is None and '"SPY"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ev = rec.get("event") or {}
                sym = ev.get("symbol")
                ts = datetime.fromisoformat(rec["ts_utc"]).replace(tzinfo=None)
                if rec.get("kind") == "quote" and sym in symbols:
                    try:
                        quotes[sym].append((ts, float(ev.get("bid") or 0), float(ev.get("ask") or 0)))
                    except (TypeError, ValueError):
                        pass
                elif rec.get("kind") == "trade" and sym == "SPY":
                    et = ts + rs.ET_OFFSET
                    hh = et.strftime("%H:%M")
                    if "09:30" <= hh < "16:00":
                        try:
                            px = float(ev.get("price"))
                        except (TypeError, ValueError):
                            continue
                        if px <= 0:
                            continue
                        day = et.date().isoformat()
                        spy[day][hh] = px
                        bar = SPY_OHLC[day].get(hh)
                        if bar is None:
                            SPY_OHLC[day][hh] = [px, px, px, px]
                        else:
                            bar[1] = max(bar[1], px)
                            bar[2] = min(bar[2], px)
                            bar[3] = px
    for s in quotes:
        quotes[s].sort()
    return quotes, spy


def sigma(spy_day, et, window):
    """Typical `window`-minute SPY move, from 1-min closes over the trailing 30 minutes.

    COMPLETED minutes only (`<`, not `<=`). Until 2026-09-16 this read `<=`, which
    included the minute the decision falls in — and that minute's close is the last
    print of the minute, i.e. a price from AFTER the decision. The live engine can
    never see it (SignalGenerator.price_history holds completed bars only), and
    engine/exit_shadow.py, which does not have the bug, disagreed with this script
    on exactly the trade the TP+trail result rested on (09-09 11:01: target hit at
    $4.60 here, $4.00 live). Found by running the shadow module over every real
    trade and diffing. Do not revert to `<=`.
    """
    mins = sorted(h for h in spy_day if h < et.strftime("%H:%M"))[-31:]
    closes = [spy_day[h] for h in mins]
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    if len(diffs) < 20:
        return None
    return statistics.pstdev(diffs) * math.sqrt(window)


STRUCT_PIVOT = 2          # bars on each side of a swing point
STRUCT_BUFFER = 0.25      # x typical 10-minute SPY move


def walk_struct(ticks, t, spy_day, ohlc_day, trace=None):
    """Structure stop + live trail + 15% floor. See the module docstring.

    `trace`, if a list, receives dicts describing every swing found and every stop
    move, for charting. Returns (exit_px, exit_et, reason) or None.
    """
    entry = t["entry"]
    et0 = t["entry_utc"] + rs.ET_OFFSET
    entry_min = et0.strftime("%H:%M")
    forced = datetime.combine(et0.date(), FORCED)
    is_call = re.search(r"\d{6}([CP])", t["sym"]).group(1) == "C"
    keys = sorted(ohlc_day)
    idx = {k: i for i, k in enumerate(keys)}
    stop, done_upto = None, None
    peak, armed = None, False
    for ts, bid, ask in ticks:
        if ts <= t["entry_utc"]:
            continue
        px = bid if bid > 0 else (bid + ask) / 2.0
        if px <= 0:
            continue
        et = ts + rs.ET_OFFSET
        cur = et.strftime("%H:%M")
        # Every SPY minute that has COMPLETED since the last tick, oldest first.
        fresh = [k for k in keys if k < cur and (done_upto is None or k > done_upto) and k >= entry_min]
        for m in fresh:
            done_upto = m
            o, h, l, c = ohlc_day[m]
            if stop is not None and ((is_call and c < stop) or (not is_call and c > stop)):
                if trace is not None:
                    trace.append(dict(kind="fire", minute=m, close=c, stop=stop))
                return px, et, "structure"
            i = idx[m]
            if i < 2 * STRUCT_PIVOT:
                continue
            p = keys[i - STRUCT_PIVOT]
            if p < entry_min:
                continue
            around = [keys[j] for j in range(i - 2 * STRUCT_PIVOT, i + 1) if j != i - STRUCT_PIVOT]
            if is_call:
                pivot = ohlc_day[p][2]
                is_swing = all(pivot < ohlc_day[k][2] for k in around)
            else:
                pivot = ohlc_day[p][1]
                is_swing = all(pivot > ohlc_day[k][1] for k in around)
            if not is_swing:
                continue
            s10 = sigma(spy_day, et, 10) or 0.0
            level = pivot - STRUCT_BUFFER * s10 if is_call else pivot + STRUCT_BUFFER * s10
            new = level if stop is None else (max(stop, level) if is_call else min(stop, level))
            if trace is not None:
                trace.append(dict(kind="swing", minute=p, confirmed=m, pivot=pivot,
                                  level=level, stop=new, moved=new != stop))
            stop = new
        peak = px if peak is None else max(peak, px)
        if px <= entry * (1 - STOP):
            return px, et, "stop"
        armed = armed or peak >= entry * (1 + ARM) - 1e-9
        if armed and px <= peak * (1 - GIVEBACK):
            return px, et, "trail"
        if et >= forced:
            return px, et, "15:45"
    return None


def walk_literal(ticks, t):
    """Owner's first wording: stop = lowest option bid since entry -> sell on a new low."""
    entry = t["entry"]
    et0 = t["entry_utc"] + rs.ET_OFFSET
    forced = datetime.combine(et0.date(), FORCED)
    low, peak, armed = None, None, False
    for ts, bid, ask in ticks:
        if ts <= t["entry_utc"]:
            continue
        px = bid if bid > 0 else (bid + ask) / 2.0
        if px <= 0:
            continue
        et = ts + rs.ET_OFFSET
        if px <= entry * (1 - STOP):
            return px, et, "stop"
        if low is not None and px < low:
            return px, et, "new low"
        low = px if low is None else min(low, px)
        peak = px if peak is None else max(peak, px)
        armed = armed or peak >= entry * (1 + ARM) - 1e-9
        if armed and px <= peak * (1 - GIVEBACK):
            return px, et, "trail"
        if et >= forced:
            return px, et, "15:45"
    return None


def walk(ticks, t, rule, spy_day):
    """(exit_px, exit_et, reason) or None when the recording ends first."""
    if rule == "struct":
        day = (t["entry_utc"] + rs.ET_OFFSET).date().isoformat()
        return walk_struct(ticks, t, spy_day, SPY_OHLC.get(day, {}))
    if rule == "literal":
        return walk_literal(ticks, t)
    entry, delta = t["entry"], t["delta"]
    et0 = t["entry_utc"] + rs.ET_OFFSET
    forced = datetime.combine(et0.date(), FORCED)
    target = None
    if rule in ("dyn TP", "TP+trail", "TP+BE"):
        s30 = sigma(spy_day, et0, 30)
        if s30 is None:
            return None
        target = entry + 2 * delta * s30
    peak, armed = None, False
    for ts, bid, ask in ticks:
        if ts <= t["entry_utc"]:
            continue
        px = bid if bid > 0 else (bid + ask) / 2.0
        if px <= 0:
            continue
        et = ts + rs.ET_OFFSET
        peak = px if peak is None else max(peak, px)
        if px <= entry * (1 - STOP):
            return px, et, "stop"
        if rule in ("dyn TP", "TP+trail", "TP+BE"):
            if px >= target:
                return px, et, "target"
            armed = armed or peak >= entry * (1 + ARM) - 1e-9
            if rule == "TP+trail" and armed and px <= peak * (1 - GIVEBACK):
                return px, et, "trail"
            if rule == "TP+BE" and armed and px <= entry:
                return px, et, "b-even"
        else:
            armed = armed or peak >= entry * (1 + ARM) - 1e-9
            if armed:
                if rule == "live":
                    level = peak * (1 - GIVEBACK)
                elif rule == "keep 70%":
                    level = entry + 0.70 * (peak - entry)
                elif rule == "keep 50%":
                    level = entry + 0.50 * (peak - entry)
                else:  # vol trail
                    s10 = sigma(spy_day, et, 10)
                    level = peak - 0.5 * delta * s10 if s10 else peak * (1 - GIVEBACK)
                if px <= level:
                    return px, et, "trail"
        if et >= forced:
            return px, et, "15:45"
    return None


RULES = ["live", "keep 70%", "keep 50%", "vol trail", "dyn TP", "TP+trail", "TP+BE", "struct", "literal"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all-days", action="store_true")
    a = ap.parse_args()

    trips = load_trips()
    byday = collections.defaultdict(list)
    for t in trips:
        byday[(t["entry_utc"] + rs.ET_OFFSET).date().isoformat()].append(t)
    days = sorted(d for d in byday if a.all_days or sum(x["pnl_real"] for x in byday[d]) > 0)
    chosen = [t for d in days for t in byday[d]]
    quotes, spy = load_tape({t["sym"] for t in chosen})

    print("=" * 112)
    print("DYNAMIC EXITS ON REAL TRADES — %s  (%d days, %d round trips; $ at the real quantity)"
          % ("all days" if a.all_days else "winning days only", len(days), len(chosen)))
    print("=" * 112)
    totals = collections.defaultdict(float)
    resolved = collections.Counter()
    comparable = collections.defaultdict(float)
    ncomp = 0
    for d in days:
        print("\n%s   real day P&L %+.0f" % (d, sum(x["pnl_real"] for x in byday[d])))
        print("  %-8s %-20s %3s %6s | %-11s | %s" % ("entry", "contract", "qty", "in", "real",
                                                     " | ".join("%-17s" % r for r in RULES)))
        for t in byday[d]:
            et = t["entry_utc"] + rs.ET_OFFSET
            ticks = quotes.get(t["sym"], [])
            cells, outs = [], {}
            for r in RULES:
                res = walk(ticks, t, r, spy.get(d, {}))
                if res is None:
                    cells.append("%-17s" % "?  (no recording)")
                    continue
                px, xet, why = res
                pnl = (px - t["entry"]) * 100 * t["qty"]
                outs[r] = pnl
                totals[r] += pnl
                resolved[r] += 1
                cells.append("%+5.0f %5.2f %-6s" % (pnl, px, why))
            if len(outs) == len(RULES):
                ncomp += 1
                comparable["real"] += t["pnl_real"]
                for r in RULES:
                    comparable[r] += outs[r]
            print("  %-8s %-20s %3d %6.2f | %+4.0f %-6s | %s" % (
                et.strftime("%H:%M"), t["sym"], t["qty"], t["entry"], t["pnl_real"], t["why"][:6],
                " | ".join(cells)))

    print("\n" + "-" * 112)
    real_total = sum(t["pnl_real"] for t in chosen)
    print("TOTALS over trades each rule could resolve (real total %+.0f over %d trades)" % (real_total, len(chosen)))
    for r in RULES:
        print("  %-10s %+7.0f   (%d of %d resolved)" % (r, totals[r], resolved[r], len(chosen)))
    print("\nLIKE-FOR-LIKE — only the %d trades every rule could resolve" % ncomp)
    print("  %-10s %+7.0f" % ("real", comparable["real"]))
    for r in RULES:
        print("  %-10s %+7.0f   (%+.0f vs real)" % (r, comparable[r], comparable[r] - comparable["real"]))


if __name__ == "__main__":
    main()

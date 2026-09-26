#!/usr/bin/env python3
"""Extract a per-trade replay from the recorded session logs, for the UI's trade review chart.

    ./venv/bin/python scripts/build_trade_replays.py --env prod
    ./venv/bin/python scripts/build_trade_replays.py --env prod --since 2026-09-21
    ./venv/bin/python scripts/build_trade_replays.py --env prod --position 26 --print

WHY THIS EXISTS
---------------
Tradier serves DAILY bars for an option contract and nothing finer
(`docs/tradier/market/historical_pricing_security.md`), so a 0DTE contract's whole
life is one candle and the position chart dialog has nothing to draw. The engine,
however, records that contract's every quote tick to
`logs/livetest-<ET-date>/stream-*.jsonl` whenever `--log` is on. This script turns
those recordings into one small JSON file per position:

    data/trade_replays/trade-<buy trade id>.json

READ-ONLY. It opens the database read-only (no writes, no commits), reads log
files, and writes only into `data/trade_replays/`. It never touches the engine.

WHAT IS RECOMPUTED, AND WHY
---------------------------
The engine logs WHICH gates passed at entry, never their values — there is no
stretch or volume ratio anywhere in the logs or the database. Rather than add
logging to the live entry path, this script recomputes them from the recorded
ticks, the same way `scripts/distance_test.py` does offline.

That makes them `session_wiggle`-flavoured, not the tick-accumulated
`engine_wiggle` the live gate reads. The two run within ~4% of each other
(measured 2026-09-15, `scripts/measure_engine_wiggle.py`), so a recomputed
stretch is good to about one decimal, not two. Every recomputed value is marked
`"recomputed": true` in the output so the UI can label it.

ONE FILE PER ROUND TRIP, NOT PER POSITION
---------------------------------------
A `Position` row is REUSED when the engine re-enters the same contract: on
2026-09-24 position 27 carried three separate round trips on SPY260924P00767000
(trades 81-86), its `opened_at` shows only the last of them, and its
`peak_price` / `trough_price` span all three. Keying replays by position id
therefore loses trades and mislabels the ones it keeps. Each buy is paired with
the next sell on the same position, and each pair gets its own file.

Per-trade MFE/MAE comes from the SELL trade row (`mfe_price` / `mae_price`),
which is per round trip; the position's peak/trough is not used for that reason.

PRICE CONVENTION
----------------
`bid` is what the exit rules read (stop, trail and target are all evaluated on
the bid in `signal_generator.check_exit_signal`), so it is the series the chart
draws. `ask` is carried alongside for the mid toggle. A trade therefore starts
BELOW its entry marker by the spread — that is real, not a plotting error.
"""
import argparse
import json
import math
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "api"))

ET = ZoneInfo("America/New_York")
OUT_DIR = os.path.join(REPO, "data", "trade_replays")
LOGS = os.path.join(REPO, "logs")

# How much context to keep around the trade. Wide enough to see the setup and
# what happened just after the exit; narrow enough that a file stays ~40 KB.
PAD_BEFORE = timedelta(minutes=20)
PAD_AFTER = timedelta(minutes=20)

SESSION_OPEN = (9, 30)      # ET, for VWAP accumulation
VOL_LOOKBACK = 20           # engine: volume_ratio = last completed minute / mean of last 20


# ----------------------------------------------------------------- log scanning

def _et(ts: str) -> datetime:
    """'2026-09-23T11:13:02.123-04:00' -> aware datetime in ET."""
    return datetime.fromisoformat(ts).astimezone(ET)


def _first_last_dates(path):
    """ET dates of the first and last record, without reading the whole file."""
    with open(path, "rb") as fh:
        first = fh.readline().decode("utf-8", "replace")
        try:
            fh.seek(max(0, os.path.getsize(path) - 65536))
            tail = fh.read().decode("utf-8", "replace").splitlines()
            last = next((l for l in reversed(tail) if l.startswith("{") and l.rstrip().endswith("}")), first)
        except OSError:
            last = first
    try:
        return _et(json.loads(first)["ts_et"]).date(), _et(json.loads(last)["ts_et"]).date()
    except Exception:
        return None, None


def stream_files_for(date):
    """Every stream recording whose span covers this ET date.

    A run started the night before covers the next session too, so the folder
    name is not the answer — 2026-09-22's data lives in livetest-2026-09-21/.
    """
    out = []
    for folder in sorted(os.listdir(LOGS)):
        d = os.path.join(LOGS, folder)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.startswith("stream-") or not name.endswith(".jsonl"):
                continue
            path = os.path.join(d, name)
            lo, hi = _first_last_dates(path)
            if lo and hi and lo <= date <= hi:
                out.append(path)
    return out


def engine_logs_for(date):
    out = []
    for folder in sorted(os.listdir(LOGS)):
        d = os.path.join(LOGS, folder)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.startswith("engine-") and name.endswith(".log"):
                out.append(os.path.join(d, name))
    return out


def read_session(date, contracts, underlyings):
    """One pass over the day's recordings.

    Returns (contract_quotes, underlying_trades) where
      contract_quotes[symbol] = [(dt, bid, ask), ...]
      underlying_trades[symbol] = [(dt, price, cum_volume), ...]
    """
    cq = defaultdict(list)
    ut = defaultdict(list)
    want = set(contracts)
    for path in stream_files_for(date):
        with open(path, "r") as fh:
            for line in fh:
                # The timesale firehose is most of the file and nothing here reads
                # it; skipping it by substring avoids ~300k json.loads per session.
                if '"timesale"' in line or '"summary"' in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                ev = rec.get("event") or {}
                sym = ev.get("symbol")
                if not sym:
                    continue
                kind = ev.get("type")
                if kind == "quote" and sym in want:
                    try:
                        bid, ask = float(ev["bid"]), float(ev["ask"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    t = _et(rec["ts_et"])
                    if t.date() == date and bid > 0:
                        cq[sym].append((t, bid, ask))
                elif kind == "trade" and sym in underlyings:
                    try:
                        px = float(ev["price"])
                        cv = int(ev.get("cvol") or 0)
                        size = int(ev.get("size") or 0)
                    except (TypeError, ValueError):
                        continue
                    t = _et(rec["ts_et"])
                    if t.date() == date and px > 0:
                        ut[sym].append((t, px, cv, size))
    for d in (cq, ut):
        for k in d:
            d[k].sort(key=lambda r: r[0])
    return cq, ut


def read_engine_context(date, option_symbol, entry_dt, exit_dt):
    """Gates named at entry, the exit reason, and the broker delta in force at entry.

    Engine log timestamps are the HOST clock (PT); the recordings are ET. The
    offset is read from the file rather than assumed, by matching the log's own
    date to the session.
    """
    gates, exit_reason, delta, delta_asof = [], None, None, None
    root = option_symbol[:3]
    for path in engine_logs_for(date):
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if "ENTRY SIGNAL" not in line and "EXIT SIGNAL" not in line and "delta" not in line:
                    continue
                try:
                    stamp = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                # PT -> ET. Both are US clocks, so the gap is a fixed 3 hours.
                t = (stamp + timedelta(hours=3)).replace(tzinfo=ET)
                if t.date() != date:
                    continue
                if "ENTRY SIGNAL" in line and option_symbol in line:
                    if abs((t - entry_dt).total_seconds()) <= 120 and "):" in line:
                        gates = [g.strip() for g in line.rsplit("):", 1)[1].split(",") if g.strip()]
                elif "EXIT SIGNAL" in line and f": {root} " in line and exit_dt:
                    if abs((t - exit_dt).total_seconds()) <= 120 and "reason=" in line:
                        exit_reason = line.split("reason=", 1)[1].strip()
                elif "Greeks" in line and option_symbol in line and "delta" in line:
                    if t <= entry_dt:
                        try:
                            delta = float(line.rsplit("delta", 1)[1].strip())
                            delta_asof = t
                        except ValueError:
                            pass
    return gates, exit_reason, delta, delta_asof


# ------------------------------------------------------------------- indicators

def minute_bars(trades):
    """1-minute OHLCV for the underlying, volume differenced from the exchange's
    cumulative counter exactly as `strategy_executor._update_history` does.

    REGULAR HOURS ONLY (09:30-16:00 ET). The recording spans 04:00-20:00, but the
    engine's VWAP accumulator is a session construct, and folding pre-market
    prints into it produces a VWAP the engine never saw — which would then show a
    stretch the gate never evaluated. Validated against the engine's own logged
    `Not chasing` lines; see the module docstring."""
    by_min = defaultdict(list)
    for t, px, cv, _size in trades:
        if (t.hour, t.minute) < SESSION_OPEN or t.hour >= 16:
            continue
        by_min[t.replace(second=0, microsecond=0)].append((px, cv))
    mins = sorted(by_min)
    bars, prev_cv = [], None
    for m in mins:
        pxs = [p for p, _ in by_min[m]]
        cv = max(c for _, c in by_min[m]) or 0
        vol = max(0, cv - prev_cv) if prev_cv is not None and cv else 0
        prev_cv = cv or prev_cv
        bars.append({
            "t": int(m.timestamp()),
            "o": pxs[0], "h": max(pxs), "l": min(pxs), "c": pxs[-1], "v": vol,
        })
    return bars


def vwap_series(trades):
    """Running VWAP and its volume-weighted dispersion ('wiggle'), mirroring the
    engine's accumulator rather than computing a textbook VWAP.

    `signal_generator._update_history` is fed once per evaluation tick (~1/s) with
    `tick_volume` — the SIZE OF THE MOST RECENT INDIVIDUAL TRADE
    (`stream_driven_worker.SymbolState.apply`) — not the volume traded since the
    last tick. So the engine's VWAP is a once-a-second sample weighted by one
    print's size. Rebuilding it any other way produces a different number: a
    cumulative-volume VWAP came out ~38% wider on the wiggle, and minute HL2 bars
    ~14% wider, both measured against the engine's own `Not chasing` lines
    (2026-09-23). Mirroring the sampling is what makes the recomputed stretch
    comparable to the one the live gate applied.

    Returns (per-minute samples for the chart, [(ts, vwap, wiggle)] for lookups).
    """
    spv = sv = spv2 = 0.0
    per_second = {}
    for t, px, _cv, size in trades:
        if (t.hour, t.minute) < SESSION_OPEN or t.hour >= 16:
            continue
        per_second[t.replace(microsecond=0)] = (px, size)   # last print wins, as the worker reads state
    samples, state, last_min = [], [], None
    for t in sorted(per_second):
        px, size = per_second[t]
        if size <= 0:
            continue
        spv += px * size
        sv += size
        spv2 += px * px * size
        if sv <= 0:
            continue
        vwap = spv / sv
        wig = math.sqrt(max(0.0, spv2 / sv - vwap * vwap))
        state.append((int(t.timestamp()), vwap, wig))
        m = t.replace(second=0)
        if m != last_min:
            samples.append({"t": int(m.timestamp()), "vwap": round(vwap, 4), "wiggle": round(wig, 4)})
            last_min = m
    return samples, state


def context_at(bars, state, spot, when_ts):
    """Recomputed stretch and volume ratio as of the entry second.

    `spot` is the underlying's traded price at that second — not the minute's
    close — because the engine evaluates the gate on the live tick.
    """
    ctx = {"recomputed": True}
    i = bisect_right([s[0] for s in state], when_ts) - 1
    if i >= 0 and spot:
        _, vwap, wig = state[i]
        if wig > 0:
            ctx["vwap"] = round(vwap, 4)
            ctx["wiggle"] = round(wig, 4)
            ctx["stretch"] = round(abs(spot - vwap) / wig, 2)
            ctx["above_vwap"] = spot > vwap
            ctx["spot"] = spot
    if bars:
        # The LAST COMPLETED minute, not the one in progress. `_last_bar_volume`
        # reads volume_history, which only receives a bar once the minute rolls
        # over, so an entry at 11:13:02 is judged on 11:12. Using the in-progress
        # bar instead reports a ratio near zero for any entry early in a minute —
        # it read 0.35 for an entry the 1.5x gate had just passed.
        j = max(0, bisect_right([b["t"] for b in bars], when_ts) - 1) - 1
        if j >= 1:
            prior = [b["v"] for b in bars[max(0, j - VOL_LOOKBACK + 1):j + 1] if b["v"]]
            if len(prior) >= VOL_LOOKBACK // 2 and sum(prior):
                ctx["volume_ratio"] = round(bars[j]["v"] / (sum(prior) / len(prior)), 2)
    return ctx


# ------------------------------------------------------------------------ build

def exit_levels(params, entry_price):
    """The four prices the exit rules watch, in contract dollars."""
    stop = params.get("stop_loss_pct") or params.get("stop_loss_percentage")
    target = params.get("take_profit_pct") or params.get("take_profit_percentage")
    lv = {}
    if stop:
        lv["stop"] = round(entry_price * (1 - float(stop) / 100), 2)
    if target:
        lv["target"] = round(entry_price * (1 + float(target) / 100), 2)
    if params.get("trailing_stop"):
        arm = float(params.get("trailing_stop_activation", 15))
        dist = float(params.get("trailing_stop_distance", 10))
        lv["trail_arms_at"] = round(entry_price * (1 + arm / 100), 2)
        lv["trail_gives_back_pct"] = dist
    return lv


def build(position, buy, sell, strategy, session_cache):
    """One round trip: this buy and the sell that closed it."""
    symbol = position.option_symbol or position.symbol
    root = position.symbol
    entry_dt = buy.timestamp.replace(tzinfo=timezone.utc).astimezone(ET)
    exit_dt = sell.timestamp.replace(tzinfo=timezone.utc).astimezone(ET) if sell else None
    date = entry_dt.date()

    key = (date, symbol)
    if key not in session_cache:
        session_cache[key] = read_session(date, [symbol], {root})
    cq, ut = session_cache[key]

    lo = entry_dt - PAD_BEFORE
    hi = (exit_dt or entry_dt) + PAD_AFTER
    points = [
        {"t": int(t.timestamp()), "bid": b, "ask": a}
        for t, b, a in cq.get(symbol, []) if lo <= t <= hi
    ]
    bars = minute_bars(ut.get(root, []))
    vwaps, vwap_state = vwap_series(ut.get(root, []))
    spot = next((px for t, px, _cv, _sz in reversed(ut.get(root, [])) if t <= entry_dt), None)
    gates, exit_reason, delta, delta_asof = read_engine_context(date, symbol, entry_dt, exit_dt)

    entry_price = float(buy.price)
    ctx = context_at(bars, vwap_state, spot, int(entry_dt.timestamp()))
    if delta is not None:
        ctx["broker_delta"] = delta
        ctx["broker_delta_age_min"] = round((entry_dt - delta_asof).total_seconds() / 60, 1) if delta_asof else None

    return {
        "trade_id": sell.id if sell else None,
        "buy_trade_id": buy.id,
        "position_id": position.id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "partial": sell is None,
        "contract": {
            "symbol": symbol,
            "price_series": "bid",
            "points": points,
            "levels": exit_levels(strategy.params_json or {}, entry_price) if strategy else {},
        },
        "underlying": {"symbol": root, "bars": bars, "vwap": vwaps},
        "entry": {
            "t": int(entry_dt.timestamp()),
            "price": entry_price,
            "qty": buy.qty,
            "gates": gates,
            "context": ctx,
        },
        "exit": None if not sell else {
            "t": int(exit_dt.timestamp()),
            "price": float(sell.exit_price or sell.price),
            "reason": exit_reason,
            "pnl": float(sell.pnl or 0),
        },
        "facts": {
            "strategy_id": position.strategy_id,
            "strategy_name": strategy.name if strategy else None,
            # Per ROUND TRIP. The position's peak_price/trough_price span every
            # re-entry into the same contract, so they are not used here.
            "mfe_price": sell.mfe_price if sell else None,
            "mae_price": sell.mae_price if sell else None,
            "hold_s": int((exit_dt - entry_dt).total_seconds()) if exit_dt else None,
        },
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env", choices=["dev", "prod"], default="prod")
    ap.add_argument("--since", metavar="YYYY-MM-DD", help="only positions opened on/after this ET date")
    ap.add_argument("--position", type=int, help="rebuild just this position id")
    ap.add_argument("--print", dest="show", action="store_true", help="print a summary of each replay")
    args = ap.parse_args()

    os.environ["APP_ENV"] = args.env
    from database import SessionLocals, Environment
    from models import Position, Strategy, Trade

    db = SessionLocals[Environment.PROD if args.env == "prod" else Environment.DEV]()
    strategies = {s.id: s for s in db.query(Strategy).all()}
    trades = defaultdict(list)
    for t in db.query(Trade).filter(Trade.status == "executed").order_by(Trade.id).all():
        if t.position_id:
            trades[t.position_id].append(t)

    q = db.query(Position).order_by(Position.id)
    if args.position:
        q = q.filter(Position.id == args.position)
    positions = q.all()

    os.makedirs(OUT_DIR, exist_ok=True)
    cache, written, skipped = {}, 0, []
    for p in positions:
        # Pair each buy with the next sell on the same position. A trailing buy
        # with no sell is a position still open: it still gets a (partial) file.
        pairs, open_buy = [], None
        for t in trades.get(p.id) or []:
            if t.side == "buy" and open_buy is None:
                open_buy = t
            elif t.side == "sell" and open_buy is not None:
                pairs.append((open_buy, t))
                open_buy = None
        if open_buy is not None:
            pairs.append((open_buy, None))
        if not pairs:
            skipped.append((p.id, "no buy trade"))
            continue

        for buy, sell in pairs:
            opened_et = buy.timestamp.replace(tzinfo=timezone.utc).astimezone(ET)
            if args.since and str(opened_et.date()) < args.since:
                continue
            rec = build(p, buy, sell, strategies.get(p.strategy_id), cache)
            if not rec["contract"]["points"]:
                skipped.append((buy.id, f"no recorded quotes for {rec['contract']['symbol']} on {opened_et.date()}"))
                continue
            path = os.path.join(OUT_DIR, f"trade-{buy.id}.json")
            with open(path, "w") as fh:
                json.dump(rec, fh, separators=(",", ":"))
            written += 1
            if args.show:
                c, e, x = rec["contract"], rec["entry"], rec["exit"]
                print(f"  trade {buy.id:3d} (pos {p.id:2d}) {c['symbol']:22s} {len(c['points']):5d} quotes  "
                      f"entry ${e['price']:.2f} {'-> $%.2f' % x['price'] if x else '(open)'}  "
                      f"{'%+.0f' % x['pnl'] if x else '':>6s}  stretch {e['context'].get('stretch', '—')}")

    print(f"\nwrote {written} replay(s) to {os.path.relpath(OUT_DIR, REPO)}/")
    for pid, why in skipped:
        print(f"  skipped position {pid}: {why}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Replay a recorded live session's entry signals against its recorded quotes.

    ./venv/bin/python scripts/replay_session.py --all
    ./venv/bin/python scripts/replay_session.py --session logs/livetest-2026-09-08
    ./venv/bin/python scripts/replay_session.py --all --entry-end 12:00
    ./venv/bin/python scripts/replay_session.py --all --sweep window

WHY THIS EXISTS
---------------
The account funds roughly three entries per session (T+1 settlement on a cash
account: sale proceeds are unusable until the next day, so a day's trades come
out of the balance you woke up with). TODO E11 wants ~62 closed round trips
before anyone judges the strategy, and E2b names the problem — at three
samples a day that is months away, and funding more just measures the cash
constraint again.

But every signal the strategy ever produced is already on disk, and so is the
option quote that priced it. `ENTRY SIGNAL:` lines in engine-*.log say when the
strategy wanted in, on which contract, at what mid; stream-*.jsonl carries that
contract's bid/ask tick by tick. That is enough to price the trades the account
could not afford. 2026-09-02..09-09 yields ~110 round trips from 5 sessions
instead of 14.

READ-ONLY. Touches no database, places no orders, changes no settings. It reads
log files and prints.

WHAT IT IS NOT
--------------
Not a backtest of the ENTRY rule. The entry signals are taken as recorded — this
cannot tell you what a different EMA period would have done, because no quote
history for an unselected contract exists. It answers exactly one question:
given the entries the strategy actually generated, what do the EXIT rules and
the trading window do with them?

Two known biases, both stated so nobody has to rediscover them:

  * Entry fills at the mid the engine logged; a real buy pays closer to the ask.
    So results here are optimistic by roughly half the spread (~0.35% on these
    contracts). Exits evaluate on the bid, which is what strategy_executor does.
  * A contract stops being streamed once the worker re-arms to a different
    strike, so a position still open at that moment cannot be resolved. Those
    are reported separately as `unresolved` and excluded from every statistic,
    never silently counted as flat.
"""
import argparse
import glob
import json
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Engine logs are written in the host's local time (America/Los_Angeles); the
# stream jsonl carries an explicit UTC stamp. Everything below is normalised to
# UTC and only converted to ET for display and for the window gates, because ET
# is the only clock the trading rules are written in.
PT_TO_UTC = timedelta(hours=7)
ET_OFFSET = timedelta(hours=-4)

SIGNAL_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO engine\.strategy_executor: "
    r"ENTRY SIGNAL: (?P<under>\S+) option=(?P<opt>\S+) price=\$(?P<px>[\d.]+)")

# Defaults mirror the live params_json on strategies 3 and 4 as of 2026-09-09.
# Printed on every run so a result can always be tied back to the rules that
# produced it — an unlabelled number from this tool is worthless.
DEFAULTS = dict(stop=15.0, target=25.0, trail_arm=15.0, trail_distance=10.0,
                trail=True, entry_start="10:00", entry_end="15:45")


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def parse_hhmm(s):
    h, m = s.split(":")
    return dtime(int(h), int(m))


def load_signals(path):
    """[(ts_utc, option_symbol, mid)] from one engine log, in order."""
    out = []
    with open(path, errors="ignore") as fh:
        for line in fh:
            m = SIGNAL_RE.match(line)
            if not m:
                continue
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S") + PT_TO_UTC
            out.append((ts, m.group("opt"), float(m.group("px"))))
    return out


def load_quotes(path):
    """{option_symbol: [(ts_utc, bid, ask)]}, sorted.

    Skips the underlying: SPY quotes outnumber option quotes ~8:1 in these
    files and are not what any exit rule reads.
    """
    q = defaultdict(list)
    with open(path, errors="ignore") as fh:
        for line in fh:
            if '"kind": "quote"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            ev = rec.get("event") or {}
            sym = ev.get("symbol") or ""
            if len(sym) < 15:          # "SPY", not "SPY260908P00769000"
                continue
            try:
                bid = float(ev.get("bid") or 0)
                ask = float(ev.get("ask") or 0)
                ts = datetime.fromisoformat(rec["ts_utc"]).replace(tzinfo=None)
            except (TypeError, ValueError, KeyError):
                continue
            q[sym].append((ts, bid, ask))
    for s in q:
        q[s].sort()
    return q


def find_pairs(session_dir, min_bytes=100_000):
    """Pair engine-<stamp>.log with stream-<stamp>.jsonl inside one session dir.

    A session folder holds every restart from that morning, most of them a few
    kilobytes from a process that died on boot. Only the pair that actually
    traded is worth loading, hence the size floor.
    """
    pairs = []
    for lg in sorted(glob.glob(os.path.join(session_dir, "engine-*.log"))):
        stamp = os.path.basename(lg)[len("engine-"):-len(".log")]
        st = os.path.join(session_dir, "stream-%s.jsonl" % stamp)
        if not os.path.exists(st):
            continue
        if os.path.getsize(lg) < min_bytes or os.path.getsize(st) < min_bytes:
            continue
        pairs.append((lg, st))
    return pairs


# --------------------------------------------------------------------------
# the exit walk — a faithful copy of signal_generator.check_exit_signal
# --------------------------------------------------------------------------
def walk_exit(ticks, entry_ts, entry_px, cfg):
    """Return (exit_ts, exit_px, reason) or None if the ticks run out first.

    Rule order matches the engine exactly, and the order is load-bearing:
      1. stop loss, evaluated first so the downside bound is never gated
      2. trailing stop, armed off the PEAK (not the live price)
      3. flat target, SUPPRESSED while the trail is armed
      4. forced exit at the session's cutoff

    The forced-exit instant is derived from the ENTRY's own ET date. One engine
    log can span several sessions (the 2026-09-03 log runs into 09-04), and
    pinning it to the folder name makes every later day look like it opened
    after the close.
    """
    et_day = (entry_ts + ET_OFFSET).date()
    forced = datetime.combine(et_day, cfg["exit_by_t"]) - ET_OFFSET
    peak = None
    last = None
    for ts, bid, ask in ticks:
        if ts <= entry_ts:
            continue
        # strategy_executor prefers the streamed bid and falls back to the mid
        # on a one-sided book.
        px = bid if bid > 0 else (bid + ask) / 2.0
        if px <= 0:
            continue
        if peak is None or px > peak:
            peak = px
        last = (ts, px)
        pnl_pct = (px - entry_px) / entry_px * 100.0

        if pnl_pct <= -cfg["stop"]:
            return ts, px, "stop loss"

        armed = (cfg["trail"]
                 and (peak - entry_px) / entry_px * 100.0 >= cfg["trail_arm"] - 1e-9)
        if armed and px <= peak * (1 - cfg["trail_distance"] / 100.0):
            return ts, px, "trailing stop"

        if cfg["target"] and not armed and pnl_pct >= cfg["target"]:
            return ts, px, "take profit"

        if ts >= forced:
            return ts, px, "forced exit"

    # Ticks ran out with the position still open — the worker re-armed to a
    # different strike and this contract stopped being streamed. Returned as a
    # real (ts, px) rather than None so the caller can advance the busy clock:
    # a position we cannot resolve still blocks re-entry, and without that the
    # same dead contract is retried on every subsequent signal tick and counted
    # hundreds of times. Excluded from every statistic by its reason.
    if last is not None:
        return last[0], last[1], "unresolved"
    return None


def strategy_of(option_symbol):
    """Calls are strategy 3, puts strategy 4 — they never share a direction."""
    return 3 if "C00" in option_symbol else 4


def replay(pairs, cfg):
    """Walk every session under one config. Returns (trades, unresolved, late)."""
    trades, unresolved, late = [], 0, 0
    for lg, st in pairs:
        sigs = load_signals(lg)
        quotes = load_quotes(st)
        # Each strategy holds at most one position (max_positions=1), so a
        # signal arriving while that strategy is still in a trade is not an
        # opportunity — it is the same trade still running.
        busy = {3: datetime.min, 4: datetime.min}
        taken_today = defaultdict(int)          # (et_date, strategy) -> count
        for ts, sym, mid in sigs:
            sid = strategy_of(sym)
            if ts < busy[sid]:
                continue
            et_dt = ts + ET_OFFSET
            et = et_dt.time()
            if not (cfg["entry_start_t"] <= et < cfg["entry_end_t"]):
                late += 1
                continue
            if cfg["max_per_day"] and taken_today[(et_dt.date(), sid)] >= cfg["max_per_day"]:
                continue
            ticks = quotes.get(sym)
            if not ticks:
                continue
            res = walk_exit(ticks, ts, mid, cfg)
            if res is None:
                continue
            xts, xpx, why = res
            # Cooldown: how long the strategy sits out after closing. The plain
            # cooldown applies to every exit; the loss cooldown applies only
            # after a losing one and is the LONGER of the two, so it can never
            # shorten the general rule.
            wait = cfg["cooldown"]
            if xpx < mid:
                wait = max(wait, cfg["loss_cooldown"])
            busy[sid] = xts + timedelta(minutes=wait)
            if why == "unresolved":
                unresolved += 1
                continue
            taken_today[(et_dt.date(), sid)] += 1
            trades.append(dict(
                strategy=sid, symbol=sym, entry_ts=ts, exit_ts=xts,
                entry=mid, exit=xpx, reason=why,
                ret=(xpx - mid) / mid * 100.0,
                pnl=(xpx - mid) * 100.0,
                held_min=(xts - ts).total_seconds() / 60.0))
    trades.sort(key=lambda t: t["entry_ts"])
    return trades, unresolved, late


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
def summarise(trades):
    if not trades:
        return None
    r = [t["ret"] for t in trades]
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x <= 0]
    n = len(r)
    exp = statistics.mean(r)
    sd = statistics.stdev(r) if n > 1 else 0.0
    se = sd / (n ** 0.5) if n else 0.0
    aw = statistics.mean(wins) if wins else 0.0
    al = statistics.mean(losses) if losses else 0.0
    return dict(
        n=n, wins=len(wins), losses=len(losses), win_rate=len(wins) / n * 100,
        avg_win=aw, avg_loss=al,
        payoff=(aw / abs(al)) if al else 0.0,
        # Break-even against the payoff the exits ACTUALLY produce, which is not
        # stop/(stop+target) unless every win really lands at the full target.
        breakeven=(abs(al) / (abs(al) + aw) * 100) if (aw + abs(al)) else 0.0,
        exp=exp, sd=sd, se=se,
        ci_lo=exp - 1.98 * se, ci_hi=exp + 1.98 * se,
        pnl=sum(t["pnl"] for t in trades))


def print_summary(s, unresolved, late, label=""):
    if s is None:
        print("  no trades matched")
        return
    if label:
        print(label)
    print("  round trips        %d   (%d won / %d lost)   unresolved %d, outside window %d"
          % (s["n"], s["wins"], s["losses"], unresolved, late))
    print("  win rate           %5.1f%%      break-even needed %5.1f%%"
          % (s["win_rate"], s["breakeven"]))
    print("  avg win           %+6.1f%%      avg loss %+6.1f%%      payoff %.2fx"
          % (s["avg_win"], s["avg_loss"], s["payoff"]))
    print("  expectancy        %+6.2f%% per trade    (%s per contract)"
          % (s["exp"], format(s["pnl"], "+,.0f")))
    verdict = "contains zero — no conclusion" if s["ci_lo"] <= 0 <= s["ci_hi"] else "excludes zero"
    print("  95%% CI            %+6.2f%% to %+6.2f%%   <- %s" % (s["ci_lo"], s["ci_hi"], verdict))


def print_trades(trades):
    print("%-5s %-11s %-9s %-9s %6s %-22s %6s %6s %8s %9s  %s" % (
        "strat", "date", "entry ET", "exit ET", "held", "contract",
        "in", "out", "return", "$/ct", "exit reason"))
    for t in trades:
        a = t["entry_ts"] + ET_OFFSET
        b = t["exit_ts"] + ET_OFFSET
        print("%-5d %-11s %-9s %-9s %5.1fm %-22s %6.2f %6.2f %+7.1f%% %9s  %s" % (
            t["strategy"], a.date().isoformat(), a.strftime("%H:%M:%S"),
            b.strftime("%H:%M:%S"), t["held_min"], t["symbol"],
            t["entry"], t["exit"], t["ret"], format(t["pnl"], "+,.0f"), t["reason"]))


def print_breakdowns(trades):
    print()
    print("BY EXIT REASON")
    by = defaultdict(list)
    for t in trades:
        by[t["reason"]].append(t)
    for k in sorted(by, key=lambda k: -len(by[k])):
        v = by[k]
        print("  %-16s n=%-4d avg %+6.1f%%   %s" % (
            k, len(v), statistics.mean(x["ret"] for x in v),
            format(sum(x["pnl"] for x in v), "+,.0f")))

    print()
    print("BY ENTRY TIME (ET half hours) — cumulative column is the money chart")
    buck = defaultdict(list)
    for t in trades:
        et = t["entry_ts"] + ET_OFFSET
        buck[et.replace(minute=0 if et.minute < 30 else 30,
                        second=0, microsecond=0).time()].append(t)
    cum = 0.0
    print("  %-8s %4s %6s %10s %11s %11s %9s" % (
        "bucket", "n", "win%", "exp/trade", "$/contract", "cumulative", "avg prem"))
    for k in sorted(buck):
        v = buck[k]
        cum += sum(x["pnl"] for x in v)
        w = sum(1 for x in v if x["ret"] > 0)
        print("  %-8s %4d %5.0f%% %+9.2f%% %11s %11s %9s" % (
            k.strftime("%H:%M"), len(v), w / len(v) * 100,
            statistics.mean(x["ret"] for x in v),
            format(sum(x["pnl"] for x in v), "+,.0f"), format(cum, "+,.0f"),
            "$%.2f" % statistics.mean(x["entry"] for x in v)))

    print()
    print("BY DIRECTION")
    for kind, sel in (("CALL (s3)", [t for t in trades if t["strategy"] == 3]),
                      ("PUT  (s4)", [t for t in trades if t["strategy"] == 4])):
        if not sel:
            continue
        w = sum(1 for t in sel if t["ret"] > 0)
        print("  %-10s n=%-4d win %4.0f%%   avg %+6.1f%%   %s" % (
            kind, len(sel), w / len(sel) * 100,
            statistics.mean(t["ret"] for t in sel),
            format(sum(t["pnl"] for t in sel), "+,.0f")))


def verify_against_live(trades):
    """Side-by-side against the trades that actually filled. Read-only.

    The point of this mode: a replay nobody has checked against reality is a
    number generator. The overlap is small by construction — the account could
    only fund the first two or three entries of each session — but those are
    exactly the ones where the tool can be caught lying.

    Expect entries to match within a cent or two (the engine logs the mid it
    sized off, the fill lands near it) and exits to be close but not exact:
    exits here read the streamed bid, while the live exit was a market order
    that could fill through it.
    """
    from dotenv import load_dotenv
    from sqlalchemy import create_engine, text

    load_dotenv(os.path.join(REPO, ".env"))
    url = os.getenv("DATABASE_PROD_URL")
    if not url:
        print("  DATABASE_PROD_URL not set — cannot verify")
        return
    days = sorted({(t["entry_ts"] + ET_OFFSET).date() for t in trades})
    if not days:
        return
    eng = create_engine(url)
    with eng.connect() as conn:
        legs = conn.execute(text(
            "SELECT timestamp, side, price, exit_price, pnl, strategy_id "
            "FROM trades WHERE timestamp::date BETWEEN :a AND :b "
            "ORDER BY strategy_id, timestamp"),
            {"a": days[0], "b": days[-1]}).fetchall()

    # A round trip is a buy leg followed by its sell leg. The sell row carries
    # the P&L and the exit price, but its `timestamp` is the EXIT — the entry
    # time only exists on the buy row, and matching the replay on exit time
    # would pair trades by when they happened to close.
    rows = []
    open_leg = {}
    for ts, side, price, exit_price, pnl, sid in legs:
        if side == "buy":
            open_leg[sid] = (ts, price)
        elif sid in open_leg:
            ents, entp = open_leg.pop(sid)
            rows.append((ents, entp, exit_price, ts, pnl, sid))
    rows.sort()

    print()
    print("VERIFY — replay vs the fills that actually happened")
    if not rows:
        print("  no live trades in this date range")
        return
    print("  %-11s %-9s | %-19s | %-19s" % ("date", "entry ET", "LIVE  in -> out", "REPLAY  in -> out"))
    matched, agree, entry_gaps = 0, 0, []
    for ts, entry_px, exit_px, xts, pnl, sid in rows:  # ts is the ENTRY
        # match on entry time: the live BUY and the replayed entry are the same
        # signal, so they sit within a couple of seconds of each other.
        best, bestgap = None, timedelta(minutes=3)
        for t in trades:
            if t["strategy"] != sid:
                continue
            gap = abs(t["entry_ts"] - ts)
            if gap < bestgap:
                best, bestgap = t, gap
        et = (ts + ET_OFFSET)
        if best is None:
            print("  %-11s %-9s | %5.2f -> %5.2f %+7.0f | %s" % (
                et.date().isoformat(), et.strftime("%H:%M:%S"),
                entry_px, exit_px, pnl, "(no replayed trade near this entry)"))
            continue
        matched += 1
        entry_gaps.append(abs(best["entry"] - entry_px))
        same_sign = (pnl > 0) == (best["pnl"] > 0)
        agree += same_sign
        print("  %-11s %-9s | %5.2f -> %5.2f %+7.0f | %5.2f -> %5.2f %+7.0f  %-14s %s" % (
            et.date().isoformat(), et.strftime("%H:%M:%S"),
            entry_px, exit_px, pnl, best["entry"], best["exit"], best["pnl"],
            best["reason"], "" if same_sign else "<-- DISAGREES on direction"))

    print("  matched %d of %d live round trips" % (matched, len(rows)))
    if matched:
        print("  entry price agrees to $%.3f on average; %d of %d agree on win/loss"
              % (statistics.mean(entry_gaps), agree, matched))
    if matched < len(rows):
        print("  unmatched rows are trades whose replay could not be resolved (the")
        print("  contract left the quote stream) or that predate a rules change.")


SWEEP_HDR = "  %-26s %4s %6s %8s %8s %10s %11s %20s" % (
    "variant", "n", "win%", "avg win", "avg loss", "exp/trade", "$/contract", "95% CI")


def sweep_row(label, trades):
    s = summarise(trades)
    if s is None:
        print("  %-26s   (no trades)" % label)
        return
    print("  %-26s %4d %5.0f%% %+7.1f%% %+7.1f%% %+9.2f%% %11s  %+6.2f%% to %+6.2f%%" % (
        label, s["n"], s["win_rate"], s["avg_win"], s["avg_loss"], s["exp"],
        format(s["pnl"], "+,.0f"), s["ci_lo"], s["ci_hi"]))


def run_sweep(kind, pairs, cfg):
    """Grid over one dimension.

    Every row is the SAME five sessions. Searching a grid on a sample this small
    will always surface a flattering row — that is what searching does. Read the
    shape across rows, and read the CI column before believing any single one.
    """
    print()
    print("SWEEP: %s" % kind)
    print(SWEEP_HDR)
    CUTOFFS = [(10, 30, "10:30 (1h)"), (11, 0, "11:00 (1.5h)"), (11, 30, "11:30 (2h)"),
               (12, 0, "12:00 (2.5h)"), (12, 30, "12:30 (3h)"), (13, 0, "13:00 (3.5h)"),
               (14, 0, "14:00 (4.5h)"), (15, 45, "15:45 (current)")]
    if kind == "window":
        # Entry cutoff moves; the forced exit stays at 15:45 so a position
        # opened inside the window still runs its normal course. Isolates the
        # question "are late entries worth taking?" from "should we be flat
        # by lunchtime?" — NOTE this shape needs a code change to run live.
        print("  (entry cutoff moves, forced exit held at 15:45 ET)")
        for hh, mm, lab in CUTOFFS:
            c = dict(cfg, entry_end_t=dtime(hh, mm), exit_by_t=dtime(15, 45))
            sweep_row("entries until " + lab, replay(pairs, c)[0])
    elif kind == "close":
        # Both move together — this is what the engine can do today by setting
        # exit_before_close_minutes, since the entry gate reuses that time.
        print("  (entry cutoff AND forced exit move together — today's single knob)")
        for hh, mm, lab in CUTOFFS:
            c = dict(cfg, entry_end_t=dtime(hh, mm), exit_by_t=dtime(hh, mm))
            sweep_row("flat by " + lab, replay(pairs, c)[0])
    elif kind == "stop":
        for v in (8, 10, 12, 15, 20):
            sweep_row("stop %d%%" % v, replay(pairs, dict(cfg, stop=float(v)))[0])
    elif kind == "trail":
        for v in (3, 5, 7, 10, 15):
            sweep_row("trail gives back %d%%" % v,
                      replay(pairs, dict(cfg, trail_distance=float(v)))[0])
        sweep_row("no trail (flat target)", replay(pairs, dict(cfg, trail=False))[0])
    elif kind == "target":
        for v in (15, 20, 25, 30):
            sweep_row("target %d%% (no trail)" % v,
                      replay(pairs, dict(cfg, target=float(v), trail=False))[0])
    elif kind == "cooldown":
        for v in (0, 2, 5, 10, 15, 30, 60):
            sweep_row("wait %dm after any exit" % v,
                      replay(pairs, dict(cfg, cooldown=float(v)))[0])
    elif kind == "losscooldown":
        for v in (0, 2, 5, 10, 15, 30, 60):
            sweep_row("wait %dm after a LOSS" % v,
                      replay(pairs, dict(cfg, loss_cooldown=float(v)))[0])
    elif kind == "maxday":
        for v in (1, 2, 3, 4, 5, 8, 0):
            sweep_row("max %s entries/day" % (v or "unlimited"),
                      replay(pairs, dict(cfg, max_per_day=v))[0])
    else:
        raise SystemExit("unknown sweep: %s" % kind)


# --------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(
        description="Replay recorded entry signals against recorded quotes. Read-only.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--session", help="one logs/livetest-YYYY-MM-DD directory")
    src.add_argument("--all", action="store_true", help="every session under logs/")
    p.add_argument("--stop", type=float, default=DEFAULTS["stop"])
    p.add_argument("--target", type=float, default=DEFAULTS["target"])
    p.add_argument("--trail-arm", type=float, default=DEFAULTS["trail_arm"])
    p.add_argument("--trail-distance", type=float, default=DEFAULTS["trail_distance"])
    p.add_argument("--no-trail", action="store_true")
    p.add_argument("--entry-start", default=DEFAULTS["entry_start"], metavar="HH:MM")
    # These are ONE knob in the engine today — check_entry_signal reuses
    # forced_exit_time_et() as its upper bound, so entries stop exactly when
    # exits start (TODO, 2026-08-25: that fix killed 174 pointless round trips).
    # They are split here because they answer different questions, and an
    # entry cutoff earlier than the forced exit would need a code change to
    # actually run. Defaults keep them equal, i.e. today's behaviour.
    p.add_argument("--entry-end", default=DEFAULTS["entry_end"], metavar="HH:MM",
                   help="latest ET time a position may be OPENED")
    p.add_argument("--exit-by", default=None, metavar="HH:MM",
                   help="forced-exit time (default: same as --entry-end, as the engine does)")
    # The engine already enforces one: strategy_executor.REENTRY_COOLDOWN_SECONDS
    # = 30.0, checked before check_entry_signal. Defaulting to 0 here made the
    # replay strictly more permissive than the live engine — it took re-entries
    # that would have been blocked (2026-09-09 11:34:58 -> 11:35:10 is 12s).
    p.add_argument("--cooldown", type=float, default=0.5, metavar="MIN",
                   help="minutes to sit out after ANY exit (default 0.5 = the engine's 30s)")
    p.add_argument("--loss-cooldown", type=float, default=0.0, metavar="MIN",
                   help="minutes to sit out after a LOSING exit (takes the longer of the two)")
    p.add_argument("--max-per-day", type=int, default=0, metavar="N",
                   help="cap entries per strategy per session (0 = no cap)")
    p.add_argument("--sweep", choices=("window", "close", "stop", "trail", "target",
                                       "cooldown", "losscooldown", "maxday"))
    p.add_argument("--trades", action="store_true", help="print every round trip")
    p.add_argument("--verify", action="store_true",
                   help="compare against the fills that actually happened (reads PROD, read-only)")
    p.add_argument("--json", metavar="PATH", help="write the trade list as JSON")
    args = p.parse_args()

    if args.session:
        dirs = [args.session if os.path.isabs(args.session)
                else os.path.join(REPO, args.session)]
    else:
        dirs = sorted(glob.glob(os.path.join(REPO, "logs", "livetest-*")))

    pairs = []
    for d in dirs:
        pairs.extend(find_pairs(d))
    if not pairs:
        raise SystemExit("no engine/stream log pairs found in: %s" % ", ".join(dirs))

    cfg = dict(stop=args.stop, target=args.target, trail_arm=args.trail_arm,
               trail_distance=args.trail_distance, trail=not args.no_trail,
               cooldown=args.cooldown, loss_cooldown=args.loss_cooldown,
               max_per_day=args.max_per_day,
               entry_start_t=parse_hhmm(args.entry_start),
               entry_end_t=parse_hhmm(args.entry_end),
               exit_by_t=parse_hhmm(args.exit_by or args.entry_end))

    print("=" * 100)
    print("REPLAY  —  %d session log pair(s)" % len(pairs))
    for lg, _ in pairs:
        print("   %s" % os.path.relpath(lg, REPO))
    print()
    print("exit rules: stop %.0f%% | %s | target %.0f%%%s" % (
        cfg["stop"],
        ("trail arms +%.0f%% gives back %.0f%%" % (cfg["trail_arm"], cfg["trail_distance"]))
        if cfg["trail"] else "no trail",
        cfg["target"], " (suppressed while trail armed)" if cfg["trail"] else ""))
    print("window:     entries %s-%s ET, forced exit %s ET" % (
        args.entry_start, args.entry_end, cfg["exit_by_t"].strftime("%H:%M")))
    print("entries fill at the logged mid; exits evaluate on the bid — optimistic")
    print("by about half the spread. See the module docstring.")
    print("=" * 100)

    if args.sweep:
        run_sweep(args.sweep, pairs, cfg)
        return

    trades, unresolved, late = replay(pairs, cfg)
    s = summarise(trades)
    print()
    print_summary(s, unresolved, late)
    if trades:
        print_breakdowns(trades)
    if args.verify and trades:
        verify_against_live(trades)
    if args.trades and trades:
        print()
        print_trades(trades)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump([dict(t, entry_ts=t["entry_ts"].isoformat(),
                            exit_ts=t["exit_ts"].isoformat()) for t in trades],
                      fh, indent=1)
        print()
        print("wrote %d trades to %s" % (len(trades), args.json))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Top up data/backtest/underlying/<SYM>_1min.json before Tradier drops the days.

    ./venv/bin/python scripts/fetch_1min_bars.py             # SPY, dry run
    ./venv/bin/python scripts/fetch_1min_bars.py --write
    ./venv/bin/python scripts/fetch_1min_bars.py --symbol TSLA --write

WHY THIS EXISTS
---------------
Tradier keeps 1-minute history for **20 days** at session_filter=open
(docs/tradier/market/time_and_sales.md). The G4b "don't chase" measurement rests
entirely on this file, so every week it is not topped up is a week permanently
lost to the sample -- the same perishability argument as C1 Phase 0. The file was
originally built ad hoc; this makes it repeatable.

WHAT IT DOES NOT DO
-------------------
Read-only against the market-data endpoint. It does not touch accounts, orders,
positions or the database, and it never overwrites a day already on disk -- the
days already captured are precisely the ones the API is about to forget, so a
"refresh" would destroy the only copy. New days are merged in; existing days are
left exactly as they are and reported as kept.

A timestamped backup of the file is written beside it before any change.
"""
import argparse
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "api"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))

# Market data is identical on both, but the sandbox key is rate-limited harder
# and its history is shallower. Prefer live; it is a read-only quote endpoint.
TOKEN = os.getenv("TRADIER_LIVE_API_KEY") or os.getenv("TRADIER_SANDBOX_API_KEY")
BASE = (os.getenv("TRADIER_LIVE_BASE_URL") or "https://api.tradier.com").rstrip("/")

RETENTION_DAYS = 20          # session_filter=open, per the Tradier docs
SESSION_OPEN, SESSION_CLOSE = "09:30", "16:00"


def data_path(symbol):
    return os.path.join(REPO, "data", "backtest", "underlying", f"{symbol}_1min.json")


def get(path, **params):
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def open_market_days(start, end):
    """Trading days between two dates, from Tradier's own calendar."""
    days = []
    cursor = start.replace(day=1)
    while cursor <= end:
        cal = get("/v1/markets/calendar", month=cursor.month, year=cursor.year)
        for d in cal["calendar"]["days"]["day"]:
            day = datetime.strptime(d["date"], "%Y-%m-%d").date()
            if d["status"] == "open" and start <= day <= end:
                days.append(d["date"])
        cursor = (cursor.replace(day=28) + timedelta(days=7)).replace(day=1)
    return sorted(set(days))


def fetch_day(symbol, day):
    r = get("/v1/markets/timesales", symbol=symbol, interval="1min",
            start=f"{day} {SESSION_OPEN}", end=f"{day} {SESSION_CLOSE}",
            session_filter="open")
    series = (r or {}).get("series")
    if not series or not series.get("data"):
        return []
    bars = series["data"]
    return bars if isinstance(bars, list) else [bars]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--write", action="store_true",
                    help="actually merge and save (default is a dry run)")
    args = ap.parse_args()

    if not TOKEN:
        sys.exit("No TRADIER_LIVE_API_KEY / TRADIER_SANDBOX_API_KEY in .env")

    path = data_path(args.symbol)
    existing = {}
    if os.path.exists(path):
        with open(path) as fh:
            existing = json.load(fh)

    today = datetime.now().date()
    earliest = today - timedelta(days=RETENTION_DAYS)
    want = open_market_days(earliest, today)

    have = sorted(existing)
    missing = [d for d in want if d not in existing]
    expired = [d for d in have if d < earliest.isoformat()]

    print(f"{args.symbol}: {len(have)} days on disk"
          + (f" ({have[0]} .. {have[-1]})" if have else ""))
    print(f"Tradier still serves: {want[0]} .. {want[-1]}  ({len(want)} sessions)")
    print(f"  already captured and NO LONGER fetchable: {len(expired)}"
          + (f"  ({expired[0]} .. {expired[-1]}) — this file is the only copy"
             if expired else ""))
    print(f"  fetchable and missing: {len(missing)}  {missing}")

    if not missing:
        print("\nNothing to fetch — already current.")
        return
    if not args.write:
        print("\nDry run. Re-run with --write to fetch and merge.")
        return

    fetched = {}
    for day in missing:
        bars = fetch_day(args.symbol, day)
        print(f"  {day}: {len(bars)} bars")
        if bars:
            fetched[day] = bars

    if not fetched:
        print("\nNothing returned; file untouched.")
        return

    # Back up only a file that exists. A first run for a new symbol (IWM,
    # 2026-09-18) has nothing to back up, and copy2 on a missing path raised
    # AFTER the fetch -- so the download was thrown away and nothing was saved.
    backup = None
    if os.path.exists(path):
        backup = f"{path}.bak-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    merged = dict(existing)
    merged.update(fetched)          # only ever ADDS days; never rewrites one
    with open(path, "w") as fh:
        json.dump(merged, fh, separators=(",", ":"))

    print(f"\nbackup  {os.path.relpath(backup, REPO) if backup else 'none (new file)'}")
    print(f"merged  {len(existing)} -> {len(merged)} days "
          f"({min(merged)} .. {max(merged)})")


if __name__ == "__main__":
    main()

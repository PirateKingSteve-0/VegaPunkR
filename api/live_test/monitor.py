"""Read-only live-test monitor: broker state vs. local ledger, side by side.

Polls Tradier (balances / positions / orders) and the local DB (today's
Trade.pnl, open Position rows) on an interval, prints a compact diff, and
appends every snapshot to ``logs/livetest-<ET-date>/reconcile-*.jsonl``.

This NEVER places or cancels orders. Safe to run against live.

Usage (from the api/ dir, with the venv):
    python -m live_test                         # dev DB, 60s, until Ctrl-C
    python -m live_test.monitor --env prod --interval 60
    python -m live_test.monitor --env prod --once     # single snapshot

Flags:
    --env {dev,prod}   which DATABASE_*_URL to read (default: dev)
    --user-email       whose account to watch (default: kingofpirates92@gmail.com)
    --interval         seconds between snapshots (default: 60)
    --duration         stop after N seconds (default: run until Ctrl-C)
    --once             take one snapshot and exit
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

# Load .env from the api/ parent before importing app modules that read env.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from models import User, Trade, Position  # noqa: E402
from utils.market_hours import user_day_start_utc  # noqa: E402
from engine.trading_client_manager import trading_manager  # noqa: E402
from live_test.logging_setup import get_jsonl_logger  # noqa: E402


def _fmt(v, width=10):
    try:
        return f"{float(v):>{width}.2f}"
    except (TypeError, ValueError):
        return f"{str(v):>{width}}"


def _broker_snapshot(client) -> dict:
    """Best-effort read of broker state; each call guarded independently."""
    snap: dict = {"errors": []}
    try:
        b = client.get_balances()
        snap["close_pl"] = float(b.get("close_pl", 0) or 0)
        snap["open_pl"] = float(b.get("open_pl", 0) or 0)
        snap["total_equity"] = float(b.get("total_equity", 0) or 0)
        snap["total_cash"] = float(b.get("total_cash", 0) or 0)
    except Exception as e:  # noqa: BLE001
        snap["errors"].append(f"balances: {e}")
    try:
        positions = client.get_positions()
        snap["positions"] = [
            {"symbol": p.get("symbol"), "quantity": p.get("quantity"),
             "cost_basis": p.get("cost_basis")}
            for p in positions
        ]
    except Exception as e:  # noqa: BLE001
        snap["positions"] = None
        snap["errors"].append(f"positions: {e}")
    try:
        orders = client.get_orders()
        # Flag the exact failure mode the live-fill fix targets: a filled order
        # with no avg_fill_price (would force estimated-price bookkeeping).
        filled_no_price, in_flight = [], []
        for o in orders:
            status = (o.get("status") or "").lower()
            oid = o.get("id")
            if status == "filled" and not o.get("avg_fill_price"):
                filled_no_price.append(oid)
            if status in ("open", "pending", "partially_filled"):
                in_flight.append({"id": oid, "status": status})
        snap["orders_total"] = len(orders)
        snap["orders_filled_without_price"] = filled_no_price
        snap["orders_in_flight"] = in_flight
    except Exception as e:  # noqa: BLE001
        snap["errors"].append(f"orders: {e}")
    return snap


def _local_snapshot(db, user) -> dict:
    day_start = user_day_start_utc(user.timezone)
    realized = db.query(func.sum(Trade.pnl)).filter(
        Trade.user_id == user.id,
        Trade.timestamp >= day_start,
        Trade.status == "executed",
        Trade.pnl.isnot(None),
    ).scalar() or 0.0
    open_positions = db.query(Position).filter(
        Position.user_id == user.id, Position.qty > 0,
    ).all()
    unrealized = sum(float(p.unrealized_pnl or 0) for p in open_positions)
    return {
        "realized_today": float(realized),
        "unrealized_open": float(unrealized),
        "day_start_utc": day_start.isoformat(),
        "open_positions": [
            {"symbol": p.symbol, "option_symbol": p.option_symbol,
             "qty": p.qty, "avg_entry_price": p.avg_entry_price}
            for p in open_positions
        ],
    }


def _diff_and_flags(broker: dict, local: dict) -> list[str]:
    flags = []
    b_pos = broker.get("positions")
    if b_pos is not None:
        b_open = [p for p in b_pos if float(p.get("quantity") or 0) != 0]
        if len(b_open) != len(local["open_positions"]):
            flags.append(
                f"POSITION COUNT MISMATCH: broker={len(b_open)} local={len(local['open_positions'])} "
                f"(possible stacking or reconcile drift)"
            )
    if broker.get("orders_filled_without_price"):
        flags.append(
            f"FILLED ORDER(S) WITHOUT avg_fill_price: {broker['orders_filled_without_price']} "
            f"(estimated-price bookkeeping risk — the live-fill fix should prevent this)"
        )
    if "close_pl" in broker:
        drift = broker["close_pl"] - local["realized_today"]
        if abs(drift) > 1.0:
            flags.append(
                f"REALIZED DRIFT: broker close_pl={broker['close_pl']:.2f} "
                f"local={local['realized_today']:.2f} (Δ {drift:+.2f})"
            )
    return flags


def snapshot(db, user, client, recon_log) -> None:
    now = datetime.now(timezone.utc)
    broker = _broker_snapshot(client)
    local = _local_snapshot(db, user)
    flags = _diff_and_flags(broker, local)

    recon_log.emit({"event": "snapshot", "broker": broker, "local": local, "flags": flags})

    et = now.astimezone().strftime("%H:%M:%S")
    print(f"\n─── {et} ─────────────────────────────────────────────")
    print(f"  broker: close_pl {_fmt(broker.get('close_pl'))}  open_pl {_fmt(broker.get('open_pl'))}  "
          f"equity {_fmt(broker.get('total_equity'))}  cash {_fmt(broker.get('total_cash'))}")
    print(f"  local : realized {_fmt(local['realized_today'])}  unreal  {_fmt(local['unrealized_open'])}")
    b_pos = broker.get("positions")
    b_open = [p for p in (b_pos or []) if float(p.get('quantity') or 0) != 0]
    print(f"  positions: broker={len(b_open)}  local={len(local['open_positions'])}"
          f"   orders_in_flight={len(broker.get('orders_in_flight') or [])}")
    if broker.get("errors"):
        for e in broker["errors"]:
            print(f"  ⚠ broker error: {e}")
    if flags:
        for f in flags:
            print(f"  🚩 {f}")
    else:
        print("  ✓ broker and local agree")


def main() -> None:
    ap = argparse.ArgumentParser(description="Read-only live-test monitor (broker vs local)")
    ap.add_argument("--env", choices=["dev", "prod"], default="dev")
    ap.add_argument("--user-email", default="kingofpirates92@gmail.com")
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    url = os.getenv("DATABASE_PROD_URL" if args.env == "prod" else "DATABASE_DEV_URL")
    if not url:
        raise SystemExit(f"DATABASE_{args.env.upper()}_URL not set")

    db = sessionmaker(bind=create_engine(url, connect_args={"connect_timeout": 8}))()
    user = db.query(User).filter(User.email == args.user_email).first()
    if not user:
        raise SystemExit(f"user {args.user_email} not found in {args.env} DB")
    client = trading_manager.get_client(user)
    recon_log = get_jsonl_logger("reconcile")

    print(f"live_test monitor — env={args.env} user={user.email} "
          f"mode={user.selected_trading_mode or 'paper'} tz={user.timezone}")
    print(f"logging snapshots -> {recon_log.path}")

    started = time.monotonic()
    try:
        while True:
            snapshot(db, user, client, recon_log)
            if args.once:
                break
            if args.duration and (time.monotonic() - started) >= args.duration:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        recon_log.close()
        db.close()


if __name__ == "__main__":
    main()

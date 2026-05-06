#!/usr/bin/env python3
"""
Strategy management / panic-stop script for VegaPunkR.

Use this when a strategy is misbehaving (runaway loop, bad fills, broker
rejections) and you need to halt trading immediately without restarting
the API server.

Usage:
    python manage_strategies.py list                 # show all strategies + status
    python manage_strategies.py list --active-only   # only currently active
    python manage_strategies.py stop <strategy_id>   # disable one strategy
    python manage_strategies.py stop-all             # PANIC: disable everything
    python manage_strategies.py start <strategy_id>  # re-enable one strategy

Notes:
  - Sets `is_active=False` in the DB. The StreamDrivenWorker reads this
    on its 30s strategy refresh and will exit the loop on the next tick;
    in the meantime, no new orders fire because the rate-limit + cooldown
    guards reject them.
  - Does NOT close open positions. After stopping, manually close in the
    Tradier dashboard or use the close-position UI.
  - Works across all environments (dev/test/prod) via --env flag.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from config import Environment
from database import SessionLocals
from models import Strategy, User


def _session(env: Environment):
    return SessionLocals[env]()


def cmd_list(args):
    db = _session(args.env)
    try:
        q = db.query(Strategy)
        if args.active_only:
            q = q.filter(Strategy.is_active == True)
        rows = q.order_by(Strategy.id).all()
        if not rows:
            print(f"No strategies found in {args.env.value}")
            return
        print(f"{'id':<5} {'active':<7} {'user_id':<8} {'name':<40} {'type':<20} instruments")
        print("-" * 110)
        for s in rows:
            active = "yes" if s.is_active else "no"
            instr = ",".join(s.instruments or [])
            name = (s.name or "")[:40]
            stype = (s.strategy_type or "")[:20]
            print(f"{s.id:<5} {active:<7} {s.user_id:<8} {name:<40} {stype:<20} {instr}")
    finally:
        db.close()


def cmd_stop(args):
    db = _session(args.env)
    try:
        s = db.query(Strategy).filter(Strategy.id == args.strategy_id).first()
        if not s:
            print(f"Strategy {args.strategy_id} not found in {args.env.value}", file=sys.stderr)
            sys.exit(1)
        if not s.is_active:
            print(f"Strategy {args.strategy_id} ({s.name}) was already inactive")
            return
        s.is_active = False
        db.commit()
        print(f"Stopped strategy {args.strategy_id}: {s.name}")
    finally:
        db.close()


def cmd_stop_all(args):
    db = _session(args.env)
    try:
        active = db.query(Strategy).filter(Strategy.is_active == True).all()
        if not active:
            print(f"No active strategies in {args.env.value} — nothing to stop")
            return
        if not args.yes:
            print(f"About to stop {len(active)} active strateg{'y' if len(active)==1 else 'ies'} in {args.env.value}:")
            for s in active:
                print(f"  - id={s.id} {s.name!r} (user_id={s.user_id})")
            confirm = input("Type STOP to confirm: ").strip()
            if confirm != "STOP":
                print("Aborted")
                sys.exit(1)
        for s in active:
            s.is_active = False
        db.commit()
        ts = datetime.utcnow().isoformat()
        print(f"[{ts}] PANIC STOP: disabled {len(active)} strateg{'y' if len(active)==1 else 'ies'} in {args.env.value}")
        for s in active:
            print(f"  - id={s.id} {s.name}")
        print("\nNext steps:")
        print("  1. Verify in Tradier dashboard that no orders are still firing")
        print("  2. Manually close any open positions if needed")
        print("  3. Investigate the cause before re-enabling with `start <id>`")
    finally:
        db.close()


def cmd_start(args):
    db = _session(args.env)
    try:
        s = db.query(Strategy).filter(Strategy.id == args.strategy_id).first()
        if not s:
            print(f"Strategy {args.strategy_id} not found in {args.env.value}", file=sys.stderr)
            sys.exit(1)
        if s.is_active:
            print(f"Strategy {args.strategy_id} ({s.name}) is already active")
            return
        s.is_active = True
        db.commit()
        print(f"Started strategy {args.strategy_id}: {s.name}")
        print("Note: the worker may take up to 30s to pick this up via its strategy refresh.")
    finally:
        db.close()


def _parse_env(value: str) -> Environment:
    try:
        return Environment(value)
    except ValueError:
        valid = ", ".join(e.value for e in Environment)
        raise argparse.ArgumentTypeError(f"invalid env {value!r} (valid: {valid})")


def main():
    parser = argparse.ArgumentParser(
        description="Strategy management / panic-stop for VegaPunkR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--env",
        type=_parse_env,
        default=Environment.DEV,
        help="Environment to operate on (default: dev)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List strategies")
    p_list.add_argument("--active-only", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_stop = sub.add_parser("stop", help="Disable a single strategy")
    p_stop.add_argument("strategy_id", type=int)
    p_stop.set_defaults(func=cmd_stop)

    p_stop_all = sub.add_parser("stop-all", help="PANIC: disable every active strategy")
    p_stop_all.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_stop_all.set_defaults(func=cmd_stop_all)

    p_start = sub.add_parser("start", help="Re-enable a strategy")
    p_start.add_argument("strategy_id", type=int)
    p_start.set_defaults(func=cmd_start)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

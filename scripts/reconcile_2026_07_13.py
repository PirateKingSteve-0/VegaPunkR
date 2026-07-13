#!/usr/bin/env python3
"""
One-off reconciliation of 2026-07-13 against Tradier's actual fills.

On that day the engine's DB reported -1,619 while the broker reported -1,851. The
$232 gap was NOT a P&L bug — it was three fills the engine never wrote down, plus one
row priced against a stale cost basis:

  1. order 35112148 — buy_to_open 3x TSLA260713C00405000 @ 1.84
     Filled at the broker, but `_await_terminal_order` timed out after 30s and the
     engine left local state untouched (ORDER_UNCONFIRMED at 13:45:48).

  2. order 35112265 — buy_to_open 3x TSLA260713C00405000 @ 3.30
     Same failure, 13:46:20.

  3. order 35129974 — sell_to_close 2x SPY260713C00751000 @ 1.82
     Closed by hand in the Tradier portal. `_reconcile_position` correctly zeroed the
     position but never wrote the closing Trade row, so its -$104 vanished from P&L.

  4. order 35112488 — the sell that closed the 6 contracts from (1) and (2).
     `_reconcile_position` adopted that position using Tradier's cost_basis and
     recorded entry=2.36. The real fills average (3*1.84 + 3*3.30) / 6 = 2.57, so the
     exit was booked against a cost basis $126 too low, flattering P&L by $128.

All four root causes are fixed going forward (2026-07-13): unconfirmed orders now block
new entries and get backfilled on the reconcile tick, external closes write a Trade row
with the broker's real fill price, and the account event stream pushes fills so the
poll window rarely expires. This script only repairs the historical rows.

Idempotent: re-running is a no-op. Run with --apply to commit; default is a dry run.
"""
import argparse
import sys
from datetime import datetime

sys.path.insert(0, "/Users/pirateking/Github/VegaPunkR/api")

from sqlalchemy import func  # noqa: E402
from database import SessionLocals, Environment  # noqa: E402
from models import Trade, Position  # noqa: E402

DAY = "2026-07-13"
BROKER_TRUTH = -1851.00

# The 6 contracts from the two unconfirmed buys, as actually filled.
TRUE_ADOPTED_ENTRY = (3 * 1.84 + 3 * 3.30) / 6  # = 2.57


def main(apply: bool) -> int:
    db = SessionLocals[Environment.DEV]()
    rows = db.query(Trade).filter(func.date(Trade.timestamp) == DAY).all()
    by_order = {str((t.notes or {}).get("order_id")): t for t in rows}

    before = db.query(func.sum(Trade.pnl)).filter(func.date(Trade.timestamp) == DAY).scalar() or 0.0
    print(f"DB total before : {before:>10,.2f}")

    tsla_pos = db.query(Position).filter(Position.strategy_id == 2).first()
    spy_pos = db.query(Position).filter(Position.strategy_id == 3).first()
    changes = 0

    def note(order_id, reason, **extra):
        return {
            "signal_type": "entry" if reason == "unconfirmed_buy" else "exit",
            "signal_reason": {
                "unconfirmed_buy": "Filled at broker after terminal-status timeout (ORDER_UNCONFIRMED)",
                "manual_close": "Closed externally in the Tradier portal",
            }[reason],
            "order_id": order_id,
            "reconciled": True,
            "reconciled_by": "scripts/reconcile_2026_07_13.py",
            **extra,
        }

    # (1) + (2) — the two unconfirmed opening legs. No pnl: P&L lives on the closing row.
    for oid, price in (("35112148", 1.84), ("35112265", 3.30)):
        if oid in by_order:
            print(f"  skip   buy  {oid} (already present)")
            continue
        db.add(Trade(
            user_id=tsla_pos.user_id, strategy_id=2, position_id=tsla_pos.id,
            symbol="TSLA", side="buy", order_type="market",
            qty=3, filled_qty=3, price=price,
            status="executed", timestamp=datetime(2026, 7, 13, 13, 45, 48),
            notes=note(oid, "unconfirmed_buy", option_symbol="TSLA260713C00405000"),
        ))
        print(f"  INSERT buy  {oid}  3 @ {price}")
        changes += 1

    # (3) — the hand-closed SPY position.
    if "35129974" not in by_order:
        entry, exit_px, qty = 2.34, 1.82, 2
        pnl = round((exit_px - entry) * qty * 100, 2)
        db.add(Trade(
            user_id=spy_pos.user_id, strategy_id=3, position_id=spy_pos.id,
            symbol="SPY", side="sell", order_type="market",
            qty=qty, filled_qty=qty, price=entry, exit_price=exit_px,
            exit_timestamp=datetime(2026, 7, 13, 18, 6, 39), pnl=pnl,
            status="executed", timestamp=datetime(2026, 7, 13, 18, 6, 39),
            notes=note("35129974", "manual_close", option_symbol="SPY260713C00751000",
                       exit_price_source="broker_fill"),
        ))
        print(f"  INSERT sell 35129974  2 @ {exit_px}  entry {entry}  pnl {pnl}")
        changes += 1
    else:
        print("  skip   sell 35129974 (already present)")

    # (4) — reprice the adopted-position exit against the real fills.
    adopted = by_order.get("35112488")
    if adopted and abs((adopted.price or 0) - TRUE_ADOPTED_ENTRY) > 0.001:
        old_price, old_pnl = adopted.price, adopted.pnl
        adopted.price = round(TRUE_ADOPTED_ENTRY, 4)
        adopted.pnl = round((adopted.exit_price - TRUE_ADOPTED_ENTRY) * adopted.qty * 100, 2)
        adopted.notes = {
            **(adopted.notes or {}),
            "reconciled": True,
            "reconciled_by": "scripts/reconcile_2026_07_13.py",
            "cost_basis_corrected": (
                f"entry {old_price:.4f} -> {TRUE_ADOPTED_ENTRY:.4f}; adopted from broker "
                "cost_basis, repriced against the real fills of orders 35112148 + 35112265"
            ),
        }
        print(f"  UPDATE sell 35112488  entry {old_price:.4f} -> {adopted.price}  "
              f"pnl {old_pnl:.2f} -> {adopted.pnl}")
        changes += 1
    else:
        print("  skip   sell 35112488 (already repriced)")

    if not changes:
        print("\nNothing to do — already reconciled.")
        return 0

    if not apply:
        db.rollback()
        print(f"\nDRY RUN — {changes} change(s) NOT written. Re-run with --apply.")
        return 0

    db.commit()
    after = db.query(func.sum(Trade.pnl)).filter(func.date(Trade.timestamp) == DAY).scalar() or 0.0
    print(f"\nDB total after  : {after:>10,.2f}")
    print(f"broker truth    : {BROKER_TRUTH:>10,.2f}")
    ok = abs(after - BROKER_TRUTH) < 0.01
    print(f"reconciled      : {'YES' if ok else 'NO — investigate'}")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="commit the changes (default: dry run)")
    sys.exit(main(ap.parse_args().apply))

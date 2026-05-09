"""
Concurrency probe for the in-process buy-reservation ledger.

Verifies that when N buys are fired concurrently against the same user
account, the cash gate in `OrderManager._preview_or_abort` correctly
serializes them — i.e., only `floor(effective_cash / required_per_order)`
pass and the rest are rejected with "Insufficient settled cash".

Default mode: PREVIEW-ONLY. No orders are placed at the broker. We invoke
`_preview_or_abort` directly so the test isolates the reservation-ledger
behavior from order placement / fill / reconciliation. Reservations
acquired during the probe are released explicitly at the end.

Usage:
  python -m debug.probe_buy_reservations \\
      --user-email you@example.com \\
      --strategy-id 3 \\
      --option-symbol SPY260509P00500000 \\
      --concurrency 5 \\
      --qty 1

  # End-to-end (places real sandbox orders):
  python -m debug.probe_buy_reservations ... --live
"""
import argparse
import asyncio
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Environment
from database import SessionLocals
from models import User, Strategy
from engine.order_manager import OrderManager


def _fetch_user_and_strategy(db, email: str, strategy_id: int):
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise SystemExit(f"User not found: {email}")
    if (user.selected_trading_mode or "paper") != "paper":
        raise SystemExit(
            f"User {email} is in trading_mode={user.selected_trading_mode!r}; "
            "the probe only runs against Tradier sandbox (paper). Switch the "
            "user to paper mode before running."
        )
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == user.id,
    ).first()
    if not strategy:
        raise SystemExit(
            f"Strategy {strategy_id} not found for user {email}. "
            "Pass --strategy-id pointing to a strategy you own."
        )
    return user, strategy


async def _probe_preview(om, user, strategy, symbol, qty, option_symbol):
    """One iteration: call _preview_or_abort and return the result tuple."""
    return await om._preview_or_abort(
        user=user,
        strategy=strategy,
        symbol=symbol,
        qty=qty,
        side="buy",
        option_symbol=option_symbol,
        order_type="market",
    )


async def _run(args):
    env = Environment(args.env)
    db = SessionLocals[env]()
    try:
        user, strategy = _fetch_user_and_strategy(db, args.user_email, args.strategy_id)
        print(f"User: {user.email} (id={user.id}, role={user.role}, "
              f"env={user.selected_environment}, mode={user.selected_trading_mode})")
        print(f"Strategy: {strategy.name} (id={strategy.id})")
        print(f"Underlying: {args.symbol}  Contract: {args.option_symbol}  "
              f"Qty/order: {args.qty}  Concurrency: {args.concurrency}")
        print()

        om = OrderManager(db)

        # Defensive: clear any leaked reservations from a prior run in the
        # same process. Process-scoped dict, so this only matters if the
        # script is re-run in an interactive session.
        OrderManager._pending_buy_reservations.clear()

        # Pre-flight: fetch balance and a single preview so we can compute
        # the expected accept count.
        client = om.trading_client.get_client(user)
        balances = await asyncio.to_thread(client.get_balances)
        cash_block = balances.get("cash") or {}
        settled_cash = float(cash_block.get("cash_available")
                             or balances.get("total_cash") or 0.0)
        print(f"Settled cash (cash.cash_available or total_cash fallback): "
              f"${settled_cash:.2f}")

        warmup_preview = await om.trading_client.preview_order(
            user=user,
            symbol=args.symbol,
            qty=args.qty,
            side="buy",
            order_type="market",
            option_symbol=args.option_symbol,
        )
        if warmup_preview is None:
            raise SystemExit(
                "Warmup preview returned None — the user is not in a mode "
                "that supports preview. Check selected_trading_mode."
            )
        preview_cost = float(warmup_preview.get("cost")
                             or warmup_preview.get("order_cost") or 0.0)
        fee_buffer = OrderManager._estimate_fee_buffer(user, args.qty, args.option_symbol)
        required_per = preview_cost + fee_buffer
        expected_ok = math.floor(settled_cash / required_per) if required_per > 0 else 0
        expected_ok = min(expected_ok, args.concurrency)

        print(f"Per-order cost: ${preview_cost:.2f}  Fee buffer: ${fee_buffer:.2f}  "
              f"Required: ${required_per:.2f}")
        print(f"Expected accepts (floor({settled_cash:.2f} / {required_per:.2f})"
              f", capped at concurrency): {expected_ok}")
        print()

        # Reset the rate-limit so the warmup preview's stamp doesn't gate the
        # probe. (preview_order via the manager doesn't stamp, but execute_signal
        # does — only matters if --live is passed.)
        OrderManager._last_order_at.pop((user.id, args.symbol), None)

        # Fire N concurrent previews.
        tasks = [
            _probe_preview(om, user, strategy, args.symbol, args.qty, args.option_symbol)
            for _ in range(args.concurrency)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        accepted = []
        rejected = []
        errored = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                errored.append((i, repr(r)))
                print(f"  [{i:02d}] ERROR  {r!r}")
                continue
            ok, _preview, msg, reservation_id = r
            if ok:
                accepted.append((i, reservation_id, msg))
                print(f"  [{i:02d}] ACCEPT rid={reservation_id} {msg}")
            else:
                rejected.append((i, msg))
                print(f"  [{i:02d}] REJECT {msg}")

        print()
        print(f"Accepted: {len(accepted)}  Rejected: {len(rejected)}  "
              f"Errored: {len(errored)}  Expected accepts: {expected_ok}")

        active_after = OrderManager._active_reservations_total(user.id)
        print(f"Active reservations after probe (sum): ${active_after:.2f}")

        # Verdict.
        if errored:
            verdict = "FAIL (errors)"
        elif len(accepted) == expected_ok:
            verdict = "PASS"
        else:
            verdict = (f"FAIL (accepted={len(accepted)} != expected={expected_ok})")
        print(f"Verdict: {verdict}")

        if args.live:
            # Live mode: hand the accepted previews off to execute_signal so
            # real sandbox orders land. Skipping for now — the original test
            # is the cash-gate, not order placement. Implement when needed.
            print("\n(--live mode is a stub. Wire to execute_signal once the "
                  "preview-only verification has been observed in sandbox traffic.)")

        # Cleanup: release every reservation we acquired so the in-process
        # ledger is clean for the next run / for a real strategy worker.
        for _idx, rid, _msg in accepted:
            OrderManager._release_buy_reservation(rid)
        leftover = OrderManager._active_reservations_total(user.id)
        if leftover > 0:
            print(f"WARNING: ${leftover:.2f} of reservations remain after cleanup "
                  "(probably acquired by something other than this probe).")
        else:
            print("Cleanup OK: no reservations remain.")
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user-email", required=True,
                   help="Email of the user whose Tradier sandbox account to probe.")
    p.add_argument("--strategy-id", required=True, type=int,
                   help="Strategy id (must belong to the user). Used for event logging.")
    p.add_argument("--option-symbol", required=True,
                   help="OCC option symbol to preview-buy (e.g. SPY260509P00500000).")
    p.add_argument("--symbol", default="SPY",
                   help="Underlying symbol (default: SPY).")
    p.add_argument("--qty", type=int, default=1,
                   help="Contracts per attempt (default: 1).")
    p.add_argument("--concurrency", type=int, default=5,
                   help="Number of concurrent preview attempts (default: 5).")
    p.add_argument("--env", default="dev", choices=["dev", "test", "prod"],
                   help="Database environment to read user/strategy from (default: dev).")
    p.add_argument("--live", action="store_true",
                   help="Stub: enable end-to-end execute_signal mode (currently a no-op).")
    args = p.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

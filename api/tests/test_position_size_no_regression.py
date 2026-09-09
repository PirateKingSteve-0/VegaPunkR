"""The `max_position_size_usd` change must not alter a single order tomorrow.

`tests/test_position_size_cap.py` proves the cap WORKS. This proves it is
INVISIBLE with the live configuration — a different claim, and the one that
matters before a session opens with real money.

Method: differential. `_sizing_at_HEAD` below is the pre-change function copied
verbatim from git HEAD (`risk_manager.py` before 2026-09-08). Every live strategy
config is swept against both it and the real, patched
`RiskManager.calculate_position_size` across the full range of contract prices
and account sizes the book has actually operated in. If the two agree on every
input, no order can differ tomorrow — not because sizing was spot-checked, but
because the functions are indistinguishable over the whole domain.

Account size is swept rather than fixed because it moves between sessions: the
engine logged $1,060.00 / $1,248.64 (09-02), $1,202.46 / $1,214.25 (09-03) and
$1,214.07 / $1,259.53 (09-08). A test pinned to one value would not cover
tomorrow's.

The strategy params below are copied from the live PROD rows on 2026-09-08 after
`scripts/null_position_size_cap.py` ran. `test_live_rows_have_no_cap` re-checks
the real database when it is reachable, so this file cannot quietly go stale if
someone sets a cap later.

No network and no DB required for the differential sweep.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))

from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


# --------------------------------------------------------------------------
# The function exactly as it was before the change. Do not "tidy" this — its
# only job is to be the old behaviour, including the redundant branch shape.
# --------------------------------------------------------------------------
def _sizing_at_HEAD(user, strategy, current_price):
    account_size = float(user.account_size_usd or 10000)
    max_trade_pct = float(user.max_trade_percentage or 2.0)
    strategy_risk_pct = float(strategy.params_json.get('risk_per_trade_pct', 1.0))
    effective_risk_pct = min(max_trade_pct, strategy_risk_pct)
    effective_capital = account_size * (effective_risk_pct / 100.0)

    if current_price <= 0:
        return 0

    _is_options = strategy.trades_options
    if _is_options:
        safety_factor = 2.0
        max_contracts = int(effective_capital / (current_price * 100 * safety_factor))
    else:
        max_contracts = int(effective_capital / current_price)

    strategy_max = strategy.params_json.get('max_contracts', 3)
    final_qty = min(max_contracts, strategy_max)

    if final_qty < 1:
        one_unit_cost = current_price * 100 if _is_options else current_price
        if effective_capital >= one_unit_cost:
            final_qty = 1

    return max(0, final_qty)


class FakeUser:
    def __init__(self, account_size):
        self.id = 1
        self.account_size_usd = account_size
        self.max_trade_percentage = 50.0


class FakeStrategy:
    def __init__(self, params, options=True):
        self.params_json = params
        self.trades_options = options


# Live PROD rows, 2026-09-08, post-null. Both strategies are identical apart
# from `direction`, which sizing does not read.
LIVE_PARAMS = {
    "risk_per_trade_pct": 50,
    "max_contracts": 3,
    "max_position_size_usd": None,
    "delta_min": 0.6,
    "delta_max": 0.85,
    "min_open_interest": 3000,
}

# Every account value the engine has logged, plus headroom either side.
ACCOUNT_SIZES = [1000.00, 1060.00, 1202.46, 1214.07, 1214.25, 1248.64,
                 1259.53, 1300.00, 1500.00, 2000.00, 5000.00]

# $0.05 to $25.00 in 5c steps: every price a 0DTE contract realistically prints.
PRICES = [round(0.05 * i, 2) for i in range(1, 501)]

rm = RiskManager(None)

print("1. differential sweep — patched code vs pre-change code, live params:")
mismatches = []
comparisons = 0
for acct in ACCOUNT_SIZES:
    user = FakeUser(acct)
    strat = FakeStrategy(dict(LIVE_PARAMS))
    for px in PRICES:
        comparisons += 1
        old = _sizing_at_HEAD(user, strat, px)
        new = rm.calculate_position_size(user, strat, px)
        if old != new:
            mismatches.append((acct, px, old, new))
check(f"identical across {comparisons:,} (account, price) pairs", mismatches, [])

print("\n2. same sweep for a SHARES strategy (the non-options branch):")
share_mismatch = []
for acct in ACCOUNT_SIZES:
    user = FakeUser(acct)
    strat = FakeStrategy(dict(LIVE_PARAMS), options=False)
    for px in PRICES:
        if _sizing_at_HEAD(user, strat, px) != rm.calculate_position_size(user, strat, px):
            share_mismatch.append((acct, px))
check("identical on the shares branch too", share_mismatch, [])

print("\n3. the cap being ABSENT behaves the same as being None:")
absent = {k: v for k, v in LIVE_PARAMS.items() if k != "max_position_size_usd"}
absent_mismatch = []
for acct in ACCOUNT_SIZES:
    user = FakeUser(acct)
    for px in PRICES:
        a = rm.calculate_position_size(user, FakeStrategy(dict(absent)), px)
        n = rm.calculate_position_size(user, FakeStrategy(dict(LIVE_PARAMS)), px)
        if a != n:
            absent_mismatch.append((acct, px, a, n))
check("absent == None everywhere", absent_mismatch, [])

print("\n4. the exact contracts traded on 2026-09-08, at that day's account size:")
user_0908 = FakeUser(1259.53)
strat_0908 = FakeStrategy(dict(LIVE_PARAMS))
for px, filled, note in [(5.72, 1, "773P entry, the +$55 winner"),
                         (2.72, 1, "769P entry"),
                         (2.24, 1, "769P entry"),
                         (1.40, 2, "12:04 signal, engine logged qty=2")]:
    check(f"${px:<5} -> {filled}   ({note})",
          rm.calculate_position_size(user_0908, strat_0908, px), filled)

print("\n5. degenerate prices still refuse to size:")
check("price 0", rm.calculate_position_size(user_0908, strat_0908, 0), 0)
check("negative price", rm.calculate_position_size(user_0908, strat_0908, -1.0), 0)


# --------------------------------------------------------------------------
# Live-row check. Skipped, not failed, when the database is unreachable — this
# file must stay runnable in the offline gate.
# --------------------------------------------------------------------------
print("\n6. live strategy rows really do carry no cap:")
try:
    from dotenv import load_dotenv
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    load_dotenv('.env')
    from models import Strategy

    seen = 0
    for env in ("DEV", "PROD"):
        url = os.environ.get(f"DATABASE_{env}_URL")
        if not url:
            continue
        db = sessionmaker(bind=create_engine(url, connect_args={"connect_timeout": 5}))()
        try:
            for s in db.query(Strategy).order_by(Strategy.id).all():
                seen += 1
                check(f"{env} s{s.id} {s.name[:28]:<28} cap is None",
                      (s.params_json or {}).get("max_position_size_usd", "<absent>"), None)
        finally:
            db.close()
    if not seen:
        print("  SKIP  no strategies found")
except Exception as e:
    print(f"  SKIP  database unreachable ({type(e).__name__}) — offline run")

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

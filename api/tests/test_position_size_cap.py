"""`max_position_size_usd` must cap the position — and must default to OFF.

The key shipped in all eight strategy templates and was read by no code at all
(audited 2026-09-08). Every existing strategy therefore carries a value that has
never been enforced, so switching enforcement on is only safe if "no value" and
"nonsense value" both mean NO CAP rather than "cap at zero".

The properties that matter, in order:
  1. Absent / None / <= 0  ->  no cap. Sizing is byte-for-byte what it was.
  2. A positive cap is the FINAL word — it must beat the "at least 1 contract"
     floor, which ignores cost and would otherwise silently override it.
  3. It may legitimately size to zero. The caller (strategy_executor.py:371)
     treats qty <= 0 as "no trade", so a cap that blocks is a skipped entry,
     never a zero-quantity order.

Real numbers throughout: the account and the three contract prices are the
actual 2026-09-08 session. No network, no DB.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))

from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<58} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class FakeUser:
    id = 1
    account_size_usd = 1259.53          # the live account on 2026-09-08
    max_trade_percentage = 50.0


class FakeStrategy:
    """Only the fields calculate_position_size actually reads."""
    trades_options = True

    def __init__(self, **params):
        self.params_json = {"risk_per_trade_pct": 50, "max_contracts": 3, **params}


rm = RiskManager(None)          # sizing touches no session


def qty(price, **params):
    return rm.calculate_position_size(FakeUser(), FakeStrategy(**params), price)


# The session actually traded these three, one contract each.
P773, P769B, P769C = 5.72, 2.72, 2.24
CHEAP = 1.40                    # 12:04 signal; the log recorded qty=2

print("1. no cap — sizing is unchanged from the live session:")
check("$5.72 contract (the +$55 winner)", qty(P773), 1)
check("$2.72 contract", qty(P769B), 1)
check("$2.24 contract", qty(P769C), 1)
check("$1.40 contract sizes to 2, as logged", qty(CHEAP), 2)

print("\n2. absent, None and non-positive all mean NO CAP:")
check("key absent", qty(P773), 1)
check("None", qty(P773, max_position_size_usd=None), 1)
check("zero is not 'cap at zero'", qty(P773, max_position_size_usd=0), 1)
check("negative is ignored", qty(P773, max_position_size_usd=-100), 1)

print("\n3. a positive cap beats the 'at least 1' floor:")
# $572 > $500. Without the ordering fix the floor would hand back 1 anyway.
check("$500 cap blocks the $5.72 contract", qty(P773, max_position_size_usd=500), 0)
check("...and that is the trade we would have lost", qty(P773, max_position_size_usd=500), 0)
check("$600 cap admits it", qty(P773, max_position_size_usd=600), 1)
check("$1000 cap admits it", qty(P773, max_position_size_usd=1000), 1)

print("\n4. the cap trims quantity, not just admit/deny:")
check("$1.40 contract, no cap -> 2", qty(CHEAP), 2)
check("$200 cap -> 1", qty(CHEAP, max_position_size_usd=200), 1)
check("$139 cap -> 0 (one unit costs $140)", qty(CHEAP, max_position_size_usd=139), 0)

print("\n5. the cap never RAISES the quantity:")
# max_contracts=3 and risk sizing both still bind above it.
check("huge cap cannot exceed max_contracts", qty(CHEAP, max_position_size_usd=10_000_000), 2)
check("huge cap on an expensive contract", qty(P773, max_position_size_usd=10_000_000), 1)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

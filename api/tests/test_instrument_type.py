"""Options vs shares must be a stored fact, not a guess from a name.

Position sizing divides by `price * 100 * 2` for options and by `price` for
shares. Answer that wrong and the size is out by two orders of magnitude. It
used to be answered independently at two call sites by string-matching
`strategy_type` for 'option' / '0dte' / 'scalping', so renaming a strategy to
anything missing those words silently switched it to the share formula.

Measured on the live account 2026-09-06 ($1,214.25, 50% risk, $3.00 contract):
`scalping_0dte` -> 1 contract; `momentum` -> 3, and the uncapped figure was 202
($60,600 of options on a $1,214 account), stopped only by `max_contracts` and
the broker's buying-power check.

The load-bearing assertions are the last two: a strategy carrying
`instrument_type='option'` sizes as options NO MATTER WHAT its name says, and a
row with NULL still behaves exactly as it did before — which is what makes this
change incapable of altering behaviour for data it has not touched.

Scratch SQLite, no broker, no network.
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base, User, Strategy
from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<64} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


eng = create_engine("sqlite:///:memory:")
Base.metadata.create_all(eng)
db = sessionmaker(bind=eng)()

# The live account, so the numbers below are the real ones.
u = User(email="i@t.com", hashed_password="x", name="I", role="user",
         account_size_usd=1214.25, max_trade_percentage=50.0)
db.add(u); db.flush()
rm = RiskManager(db)


def strat(stype, instrument=None):
    """A strategy created the way the router creates one.

    `instrument=None` means "do not pass it", so the model default applies —
    which is exactly what a new strategy from the API or the template cloner
    gets. Use `strat_null` for a row that predates the column.
    """
    kwargs = {} if instrument is None else {"instrument_type": instrument}
    s = Strategy(user_id=u.id, name="S", strategy_type=stype, max_positions=1,
                 params_json={"risk_per_trade_pct": 50, "max_contracts": 3}, **kwargs)
    db.add(s); db.flush()
    return s


def strat_null(stype):
    """A row with instrument_type NULL — what every strategy looked like before
    migration b7c3d9e4f2a8. NULLed with raw SQL because the model default now
    prevents one being created any other way, which is the point."""
    s = strat(stype)
    db.execute(text("UPDATE strategies SET instrument_type = NULL WHERE id = :i"), {"i": s.id})
    db.expire(s)
    return s


print("\nnew strategies are never born NULL:")
_new = strat("momentum")          # exactly how routers/strategies.py builds one
check("a strategy created without the field defaults to 'option'", _new.instrument_type, "option")
check("...so a bare 'momentum' name can no longer size as shares", _new.trades_options, True)
check("an explicit equity strategy is still respected",
      strat("momentum", "equity").trades_options, False)


print("\nthe stored fact wins:")
check("instrument_type='option' -> options", strat("anything", "option").trades_options, True)
check("instrument_type='equity' -> shares", strat("scalping_0dte", "equity").trades_options, False)
check("case and whitespace are tolerated", strat("x", "  Option ").trades_options, True)

print("\na pre-migration NULL row still falls back to the old string match:")
for stype, want in [("scalping_0dte", True), ("momentum_0dte", True), ("options_wheel", True),
                    ("momentum", False), ("mean_reversion", False), ("", False), (None, False)]:
    check(f"NULL + strategy_type={stype!r} -> {want}", strat_null(stype).trades_options, want)

print("\nsizing: the fact overrides the name (the footgun, closed):")

# $607 of capital, $3.00 contract.
#   options: 607 / (3 * 100 * 2) = 1  -> 1 contract
#   shares:  607 / 3 = 202, capped by max_contracts 3 -> 3 contracts
check("NULL + legacy 'scalping_0dte' -> 1 contract",
      rm.calculate_position_size(u, strat_null("scalping_0dte"), 3.00), 1)
check("NULL + bare 'momentum' -> 3 (the old bug, preserved ONLY for NULL rows)",
      rm.calculate_position_size(u, strat_null("momentum"), 3.00), 3)
check("BARE 'momentum' + instrument_type='option' -> 1 contract (FIXED)",
      rm.calculate_position_size(u, strat("momentum", "option"), 3.00), 1)
check("today's prod shape 'momentum_0dte' + 'option' -> 1 contract",
      rm.calculate_position_size(u, strat("momentum_0dte", "option"), 3.00), 1)

# Every non-options type in the UI dropdown is now harmless once the fact is set.
print("\nevery dropdown type is safe once instrument_type is recorded:")
for stype in ("momentum", "mean_reversion", "breakout", "arbitrage", "ml_based", "custom"):
    check(f"{stype!r} + 'option' -> 1 contract",
          rm.calculate_position_size(u, strat(stype, "option"), 3.00), 1)

print()
if fails:
    print(f"FAILED ({len(fails)}):")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("all instrument-type checks passed")

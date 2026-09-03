"""The account-wide "done trading for today" halt (TODO item D).

Two modes, one shared predicate. Both stop new entries; only 'flatten' brings
the forced exit forward. The things worth pinning down:

  - sells are NEVER blocked (exits are sacred — a halted account must still be
    able to close what it holds),
  - the halt expires on its own at the next ET market day,
  - 'ride' does not touch the exit path at all,
  - 'flatten' can only pull the forced exit EARLIER, never later.
"""
import os, sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

from utils.market_hours import (
    HALT_MODE_FLATTEN,
    HALT_MODE_RIDE,
    current_market_date_et,
    trading_halt_state,
)
from engine.signal_generator import forced_exit_time_et, FORCED_EOD_EXIT_FLOOR_MINUTES
from engine.risk_manager import RiskManager

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<62} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


class FakeUser:
    """Duck-typed stand-in — the halt predicate reads via getattr precisely so
    it needs no DB and no models import."""
    def __init__(self, halted_on=None, mode=None):
        self.id = 1
        self.trading_halted_on = halted_on
        self.trading_halt_mode = mode
        self.trading_window_enabled = False
        self.trading_window_start = None
        self.trading_window_end = None


TODAY = current_market_date_et()

print("the predicate — when is a halt live:")
check("no stamp is not halted", trading_halt_state(FakeUser()), (False, None))
check("today's stamp, ride", trading_halt_state(FakeUser(TODAY, 'ride')), (True, 'ride'))
check("today's stamp, flatten", trading_halt_state(FakeUser(TODAY, 'flatten')), (True, 'flatten'))
check("YESTERDAY's stamp has expired",
      trading_halt_state(FakeUser(TODAY - timedelta(days=1), 'flatten')), (False, None))
check("a stamp for tomorrow is not honoured either",
      trading_halt_state(FakeUser(TODAY + timedelta(days=1), 'flatten')), (False, None))
check("a garbage mode falls back to the NON-destructive one",
      trading_halt_state(FakeUser(TODAY, 'sell_everything_now')), (True, 'ride'))
check("a missing mode falls back to ride too",
      trading_halt_state(FakeUser(TODAY, None)), (True, 'ride'))

print("\nthe entry gate — buys blocked, sells never:")
rm = RiskManager.__new__(RiskManager)  # no DB needed; the gate touches none

for mode in (HALT_MODE_RIDE, HALT_MODE_FLATTEN):
    halted_user = FakeUser(TODAY, mode)
    check(f"[{mode}] buy is rejected",
          rm._check_user_trading_halt(halted_user, 'buy').approved, False)
    check(f"[{mode}] SELL IS ALLOWED (exits are sacred)",
          rm._check_user_trading_halt(halted_user, 'sell').approved, True)

check("an un-halted user's buy passes",
      rm._check_user_trading_halt(FakeUser(), 'buy').approved, True)
check("an expired halt stops blocking buys",
      rm._check_user_trading_halt(FakeUser(TODAY - timedelta(days=1), 'flatten'), 'buy').approved,
      True)

print("\nthe exit side — only flatten moves the forced-exit time:")
# 10:00 ET, mid-session: the EOD floor is hours away, so any change here is
# unambiguously the halt's doing.
current_et = datetime.now().astimezone().replace(microsecond=0)
from utils.market_hours import ET
current_et = ET.localize(datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, 0))
params = {'exit_before_close_minutes': 15}

base_time, base_reason = forced_exit_time_et(params, FakeUser(), current_et)
check("un-halted: exit is still the EOD bound, hours out",
      base_time > current_et, True)

ride_time, ride_reason = forced_exit_time_et(params, FakeUser(TODAY, 'ride'), current_et)
check("RIDE leaves the exit time untouched", ride_time, base_time)
check("...and the reason untouched", ride_reason, base_reason)

flat_time, flat_reason = forced_exit_time_et(params, FakeUser(TODAY, 'flatten'), current_et)
check("FLATTEN pulls the forced exit to now", flat_time, current_et)
check("...with a reason naming the halt", 'stopped for the day' in (flat_reason or ''), True)
check("...which is EARLIER than the EOD bound (never later)", flat_time < base_time, True)

print("\nflatten cannot push an exit LATER when we're already past EOD:")
# 15:59 ET — past the 15:45 floor. The specific EOD reason must survive.
late_et = ET.localize(datetime(TODAY.year, TODAY.month, TODAY.day, 15, 59, 0))
late_base, late_base_reason = forced_exit_time_et(params, FakeUser(), late_et)
late_flat, late_flat_reason = forced_exit_time_et(params, FakeUser(TODAY, 'flatten'), late_et)
check("exit time is unchanged past the EOD bound", late_flat, late_base)
check("and keeps the more specific EOD reason", late_flat_reason, late_base_reason)
check("both are already due", late_et >= late_flat, True)

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

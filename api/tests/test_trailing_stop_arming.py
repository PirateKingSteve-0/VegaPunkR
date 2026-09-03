"""The trailing stop must arm off the PEAK and must displace the flat target.

Two defects, both live until 2026-09-02 (TODO.md E1, docs/live-test-results-
2026-09-02.md F1):

1. Arming re-tested the LIVE `pnl_pct` every tick, so the trail switched itself
   off during the pullback it exists to catch. With activation=15/distance=10
   nothing could fire below a peak of 1.15/0.90 = +27.8%.
2. The flat take-profit returned first and fires on the way UP, before any
   pullback exists for the trail to react to — so the trail was unreachable by
   construction regardless of branch order. It has never executed in prod.

Fix: arming latches on position.peak_price/trough_price, and the flat target
stands down while the trail is armed. Stop loss is untouched and still wins.
No network, no DB: check_exit_signal is called directly.
"""
import os, sys
from datetime import datetime, time as dtime

sys.path.insert(0, os.path.join(os.getcwd(), 'api'))
from dotenv import load_dotenv; load_dotenv('.env')

import engine.signal_generator as sg
from engine.signal_generator import SignalGenerator

fails = []


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label:<64} {got!r}")
    if not ok:
        fails.append(f"{label}: got {got!r} want {want!r}")


# Freeze the clock mid-session so the unconditional EOD floor (step 5) never
# participates — these cases are about steps 1-3 only.
sg._market_hours.get_current_et_time = lambda: datetime(2026, 9, 2, 10, 30)
sg._market_hours.get_market_close_time_et = lambda: dtime(16, 0)


class FakeStrategy:
    def __init__(self, **params):
        self.params_json = params


GEN = SignalGenerator()

# Strategy 3's live configuration.
PROD = dict(trailing_stop=True, trailing_stop_activation=15,
            trailing_stop_distance=10, take_profit_pct=25, stop_loss_pct=15)


def exit_for(entry, current, peak=None, trough=None, side='long', **overrides):
    params = {**PROD, **overrides}
    sig = GEN.check_exit_signal(
        strategy=FakeStrategy(**params), symbol='SPY', entry_price=entry,
        current_price=current, entry_timestamp=datetime.utcnow(),
        position_side=side, current_high=peak, current_low=trough, user=None,
    )
    if sig is None:
        return 'hold'
    return sig.reason.split(':')[0].lower().replace(' ', '_')


print("1. arming latches on the peak (defect 1) — entry 2.00, peak 2.30 = +15%:")
# Stop level 2.30 * 0.90 = 2.07. Live P&L there is +3.5%, below the 15%
# activation the old code re-checked, so the old code held and rode it down.
STOP_AT_2_30 = 2.30 * (1 - 10 / 100)   # 2.0699999999999998 — compare, never a literal
check("a tick through the stop level exits", exit_for(2.00, 2.06, peak=2.30), 'trailing_stop_hit')
check("exactly at the stop level exits", exit_for(2.00, STOP_AT_2_30, peak=2.30), 'trailing_stop_hit')
check("just above the stop level holds", exit_for(2.00, 2.08, peak=2.30), 'hold')
check("peak exactly at activation arms", exit_for(2.00, 2.06, peak=2.30), 'trailing_stop_hit')
check("peak a cent under activation does NOT arm", exit_for(2.00, 2.05, peak=2.29), 'hold')

print("\n2. the flat target stands down while armed (defect 2) — the 09-02 runner:")
# SPY260902C00760000: entry 3.27, ran to 6.40. The flat +25% (4.09) took it at
# 4.68 and again after re-entry, spending $750 of settled cash for +$189.
check("at 4.68 (+43%) the target no longer fires", exit_for(3.27, 4.68, peak=4.68), 'hold')
check("at the 6.40 peak it still holds", exit_for(3.27, 6.40, peak=6.40), 'hold')
check("10% off the 6.40 peak (5.76) exits", exit_for(3.27, 5.76, peak=6.40), 'trailing_stop_hit')
check("5.80 is not yet 10% off the peak", exit_for(3.27, 5.80, peak=6.40), 'hold')

print("\n3. nothing changes below activation, or with the trail off:")
check("peak +5%, small pullback -> no exit", exit_for(2.00, 1.95, peak=2.10), 'hold')
check("trail disabled -> target fires at +25%", 
      exit_for(2.00, 2.52, peak=2.52, trailing_stop=False), 'take_profit_hit')
check("trail enabled but peak below activation -> target fires",
      exit_for(2.00, 2.55, peak=2.55, trailing_stop_activation=30), 'take_profit_hit')
check("no peak recorded yet -> target still governs",
      exit_for(2.00, 2.52, peak=None), 'take_profit_hit')

print("\n4. exits stay sacred — stop loss is untouched and outranks the trail:")
check("armed, then -20% -> STOP LOSS, not the trail",
      exit_for(2.00, 1.60, peak=2.60), 'stop_loss_hit')
check("unarmed -15% -> stop loss", exit_for(2.00, 1.70, peak=2.05), 'stop_loss_hit')

print("\n5. shorts mirror longs off the trough:")
# Short entry 2.00, trough 1.70 is +15% for a short; stop = 1.70 * 1.10 = 1.87.
check("bounce to the stop level exits", exit_for(2.00, 1.87, trough=1.70, side='short'), 'trailing_stop_hit')
check("below the stop level holds", exit_for(2.00, 1.86, trough=1.70, side='short'), 'hold')
check("trough above activation does NOT arm", exit_for(2.00, 1.90, trough=1.75, side='short'), 'hold')

print("\n" + ("ALL PASSED" if not fails else f"{len(fails)} FAILURE(S): " + "; ".join(fails)))
sys.exit(1 if fails else 0)

"""
Market Hours Detection and Timezone Handling
Determines when US stock and options markets are open/closed

Primary source: Tradier /v1/markets/clock (authoritative — handles holidays
and early closes). Falls back to local pytz logic if the API is unavailable.
"""

import logging
from datetime import datetime, time
from typing import Dict, Optional

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')


def market_day_start_utc(now_utc: Optional[datetime] = None) -> datetime:
    """Start of the current US/Eastern *trading day*, as a naive UTC datetime.

    The engine's timestamp columns (e.g. ``Trade.timestamp``) are naive UTC
    (written via ``datetime.utcnow()``), so any window compared against them
    must also be naive UTC. We anchor "today" to the Eastern calendar day — the
    market day — rather than UTC midnight, which in ET lands at ~8 PM the prior
    evening and would roll the trading day over mid-evening.

    Used by the daily-loss risk gates so the loss window tracks the market
    session, not an arbitrary UTC cutoff. Changing only the window boundary:
    during a normal session both cutoffs cover the same trades; the ET anchor
    can only hold a loss/halt longer into the evening, never release it early.
    """
    now = now_utc or datetime.utcnow()
    if now.tzinfo is None:
        now = pytz.utc.localize(now)
    now_et = now.astimezone(ET)
    start_et = ET.localize(datetime(now_et.year, now_et.month, now_et.day, 0, 0, 0))
    return start_et.astimezone(pytz.utc).replace(tzinfo=None)


def user_day_start_utc(timezone_name: Optional[str], now_utc: Optional[datetime] = None) -> datetime:
    """Start of the current calendar day in the *viewer's* timezone, as a naive
    UTC datetime.

    For display/monitoring surfaces ("today's P&L" on the dashboard tile) we
    bucket by the user's own day so the number matches what they perceive as
    today, rather than the market/ET day. Falls back to the Eastern market day
    when no usable timezone is set — the model default is the literal string
    ``'UTC'``, which for a US-market app we treat as "unset" and resolve to ET.
    """
    tz = None
    if timezone_name and timezone_name != 'UTC':
        try:
            tz = pytz.timezone(timezone_name)
        except Exception:
            logger.warning("Unknown user timezone %r; falling back to ET", timezone_name)
            tz = None
    if tz is None:
        return market_day_start_utc(now_utc)
    now = now_utc or datetime.utcnow()
    if now.tzinfo is None:
        now = pytz.utc.localize(now)
    now_local = now.astimezone(tz)
    start_local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, 0, 0, 0))
    return start_local.astimezone(pytz.utc).replace(tzinfo=None)


class MarketHours:
    """US Market hours detection with timezone awareness."""

    CLOCK_CACHE_TTL = 60  # seconds between Tradier clock refreshes

    def __init__(self):
        """Initialize with US Eastern timezone"""
        self.eastern = pytz.timezone('US/Eastern')

        # US Market hours (Eastern Time) — used as fallback
        self.market_open = time(9, 30)    # 9:30 AM ET
        self.market_close = time(16, 0)   # 4:00 PM ET

        # Tradier clock cache
        self._clock_cache: Optional[Dict] = None
        self._clock_cache_time: float = 0.0
        self._clock_error_until: float = 0.0  # back off until this monotonic time on API failure

        # Market holidays (major ones - update annually)
        self.holidays_2024 = [
            datetime(2024, 1, 1),   # New Year's Day
            datetime(2024, 1, 15),  # MLK Day
            datetime(2024, 2, 19),  # Presidents Day
            datetime(2024, 3, 29),  # Good Friday
            datetime(2024, 5, 27),  # Memorial Day
            datetime(2024, 6, 19),  # Juneteenth
            datetime(2024, 7, 4),   # Independence Day
            datetime(2024, 9, 2),   # Labor Day
            datetime(2024, 11, 28), # Thanksgiving
            datetime(2024, 12, 25), # Christmas
        ]

        self.holidays_2025 = [
            datetime(2025, 1, 1),   # New Year's Day
            datetime(2025, 1, 20),  # MLK Day
            datetime(2025, 2, 17),  # Presidents Day
            datetime(2025, 4, 18),  # Good Friday
            datetime(2025, 5, 26),  # Memorial Day
            datetime(2025, 6, 19),  # Juneteenth
            datetime(2025, 7, 4),   # Independence Day
            datetime(2025, 9, 1),   # Labor Day
            datetime(2025, 11, 27), # Thanksgiving
            datetime(2025, 12, 25), # Christmas
        ]

        self.holidays_2026 = [
            datetime(2026, 1, 1),   # New Year's Day
            datetime(2026, 1, 19),  # MLK Day
            datetime(2026, 2, 16),  # Presidents Day
            datetime(2026, 4, 3),   # Good Friday
            datetime(2026, 5, 25),  # Memorial Day
            datetime(2026, 6, 19),  # Juneteenth
            datetime(2026, 7, 3),   # Independence Day (observed, July 4 is Saturday)
            datetime(2026, 9, 7),   # Labor Day
            datetime(2026, 11, 26), # Thanksgiving
            datetime(2026, 12, 25), # Christmas
        ]

    CLOCK_ERROR_BACKOFF = 30  # seconds to wait before retrying after an API failure

    def _get_tradier_clock(self) -> Optional[Dict]:
        """Fetch market clock from Tradier with a 60s TTL cache and 30s error backoff."""
        import time as _time
        now = _time.monotonic()
        if self._clock_cache is not None and (now - self._clock_cache_time) < self.CLOCK_CACHE_TTL:
            return self._clock_cache
        if now < self._clock_error_until:
            return None  # still in backoff window, use local fallback
        try:
            from tradier_integration.client import get_tradier_client
            clock = get_tradier_client().get_market_clock()
            self._clock_cache = clock
            self._clock_cache_time = now
            self._clock_error_until = 0.0  # clear any previous backoff
            return clock
        except Exception as exc:
            self._clock_error_until = now + self.CLOCK_ERROR_BACKOFF
            logger.warning(f"Tradier clock unavailable, retrying in {self.CLOCK_ERROR_BACKOFF}s: {exc}")
            return None

    def get_current_et_time(self) -> datetime:
        """Get current time in Eastern timezone"""
        utc_now = datetime.utcnow().replace(tzinfo=pytz.utc)
        return utc_now.astimezone(self.eastern)

    def is_market_day(self, dt: datetime = None) -> bool:
        """Check if it's a trading day (Monday-Friday, not holiday)"""
        if dt is None:
            dt = self.get_current_et_time()

        # Check if weekend
        if dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

        # Check if holiday
        date_only = dt.date()
        holidays = self.holidays_2024 + self.holidays_2025 + self.holidays_2026
        holiday_dates = [h.date() for h in holidays]

        return date_only not in holiday_dates

    def is_market_open(self, dt: datetime = None) -> bool:
        """Check if US stock/options markets are currently open.

        Uses Tradier /v1/markets/clock as the authoritative source — it handles
        all holidays and early closes automatically. Falls back to local timezone
        logic if the API is unavailable.
        """
        clock = self._get_tradier_clock()
        if clock is not None:
            return clock.get("state") == "open"

        # Fallback: local timezone logic
        if dt is None:
            dt = self.get_current_et_time()
        if not self.is_market_day(dt):
            return False
        current_time = dt.time()
        return self.market_open <= current_time <= self.market_close

    def get_market_close_time_et(self) -> time:
        """Return today's actual market close time in ET.

        On early-close days (e.g. day before Thanksgiving, Christmas Eve),
        Tradier reports the real close via next_change. Falls back to 16:00.
        """
        clock = self._get_tradier_clock()
        if clock and clock.get("state") == "open" and clock.get("next_state") in ("postmarket", "post"):
            next_change = str(clock.get("next_change", ""))
            if ":" in next_change:
                try:
                    h, m = next_change.split(":")[:2]
                    return time(int(h), int(m))
                except (ValueError, IndexError):
                    pass
        return self.market_close

    def get_market_status(self) -> Dict[str, any]:
        """Get comprehensive market status."""
        current_et = self.get_current_et_time()
        is_open = self.is_market_open()

        status = {
            'current_time_et': current_et.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'is_trading_day': is_open or self.is_market_day(current_et),
            'is_market_open': is_open,
            'market_hours': f"{self.market_open.strftime('%H:%M')} - {self.market_close.strftime('%H:%M')} ET",
            'available_streams': self._get_available_streams(is_open)
        }

        clock = self._get_tradier_clock()
        if clock:
            status['message'] = clock.get('description', 'Market status from Tradier')
            status['market_state'] = clock.get('state')
            status['next_state'] = clock.get('next_state')
            status['next_change'] = clock.get('next_change')
        elif not is_open:
            current_time = current_et.time()
            if current_time < self.market_open:
                status['message'] = f"Markets closed: Pre-market (opens at {self.market_open.strftime('%H:%M')} ET)"
            else:
                status['message'] = f"Markets closed: After-hours (closed at {self.market_close.strftime('%H:%M')} ET)"
        else:
            status['message'] = "Markets open: Regular trading hours"

        return status

    def _get_available_streams(self, is_market_open: bool) -> Dict[str, bool]:
        """Determine which streams are available"""
        return {
            'crypto': True,              # Always available (24/7)
            'news': True,                # Always available (24/7)
            'stocks': is_market_open,    # Only during market hours
            'options': is_market_open    # Only during market hours
        }

    def get_streaming_strategy(self) -> Dict[str, str]:
        """Get streaming strategy based on market hours"""
        is_open = self.is_market_open()

        if is_open:
            return {
                'crypto': 'available',      # Can stream
                'news': 'available',        # Can stream
                'stocks': 'available',      # Can stream
                'options': 'available'      # Can stream
            }
        else:
            return {
                'crypto': 'available',      # Can stream
                'news': 'available',        # Can stream
                'stocks': 'unavailable',    # Market closed
                'options': 'unavailable'    # Market closed
            }

    def print_market_status(self):
        """Print detailed market status"""
        status = self.get_market_status()

        print("\nMARKET STATUS")
        print("="*60)
        print(f"Current time: {status['current_time_et']}")
        print(f"Trading day: {'Yes' if status['is_trading_day'] else 'No'}")
        print(f"Market open: {'Yes' if status['is_market_open'] else 'No'}")
        print(f"Market hours: {status['market_hours']}")
        print(f"Status: {status['message']}")

        print(f"\nAVAILABLE STREAMS:")
        streams = status['available_streams']
        for stream_type, available in streams.items():
            status_text = "Available" if available else "Unavailable"
            print(f"  {stream_type.capitalize()}: {status_text}")
        print()


# Global instance for convenience
_market_hours = MarketHours()


def get_market_status() -> Dict:
    """Quick access to market status"""
    return _market_hours.get_market_status()


def is_market_open() -> bool:
    """Quick check if market is open"""
    return _market_hours.is_market_open()


def get_available_streams() -> Dict[str, bool]:
    """Quick access to available streams"""
    status = _market_hours.get_market_status()
    return status['available_streams']

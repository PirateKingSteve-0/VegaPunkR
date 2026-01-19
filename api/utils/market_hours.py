"""
Market Hours Detection and Timezone Handling
Determines when US stock and options markets are open/closed
Extracted from alpaca-data-main and adapted for async usage
"""

from datetime import datetime, time
import pytz
from typing import Dict


class MarketHours:
    """US Market hours detection with timezone awareness"""

    def __init__(self):
        """Initialize with US Eastern timezone"""
        self.eastern = pytz.timezone('US/Eastern')

        # US Market hours (Eastern Time)
        self.market_open = time(9, 30)    # 9:30 AM ET
        self.market_close = time(16, 0)   # 4:00 PM ET

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
        holidays = self.holidays_2024 + self.holidays_2025
        holiday_dates = [h.date() for h in holidays]

        return date_only not in holiday_dates

    def is_market_open(self, dt: datetime = None) -> bool:
        """Check if US stock/options markets are currently open"""
        if dt is None:
            dt = self.get_current_et_time()

        # Must be a trading day
        if not self.is_market_day(dt):
            return False

        # Check time
        current_time = dt.time()
        return self.market_open <= current_time <= self.market_close

    def get_market_status(self) -> Dict[str, any]:
        """Get comprehensive market status"""
        current_et = self.get_current_et_time()
        is_trading_day = self.is_market_day(current_et)
        is_open = self.is_market_open(current_et)

        status = {
            'current_time_et': current_et.strftime('%Y-%m-%d %H:%M:%S %Z'),
            'is_trading_day': is_trading_day,
            'is_market_open': is_open,
            'market_hours': f"{self.market_open.strftime('%H:%M')} - {self.market_close.strftime('%H:%M')} ET",
            'available_streams': self._get_available_streams(is_open)
        }

        # Add helpful messages
        if not is_trading_day:
            if current_et.weekday() >= 5:
                status['message'] = "Markets closed: Weekend"
            else:
                status['message'] = "Markets closed: Holiday"
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

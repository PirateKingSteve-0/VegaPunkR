"""
Symbol identification and parsing utilities.
"""
import re
from datetime import date as _date
from typing import Optional


def is_option_symbol(symbol: str) -> bool:
    """
    Check if a symbol is an option contract.

    OCC option symbols follow the format: ROOT + YYMMDD + C/P + 8-digit strike
    Example: TSLA250423C00270000

    Components:
    - ROOT: Underlying symbol (e.g., TSLA)
    - YYMMDD: Expiration date (e.g., 250423 = April 23, 2025)
    - C/P: Call or Put
    - 8-digit strike: Strike price in thousandths (e.g., 00270000 = $270.00)

    Args:
        symbol: The symbol to check

    Returns:
        True if the symbol matches OCC option format, False otherwise
    """
    return bool(re.search(r'\d{6}[CP]\d{8}$', symbol or ''))


class OccContract:
    """Parsed OCC option symbol. Attributes: root, expiry (date), right
    ('C'/'P'), strike (float)."""

    __slots__ = ("root", "expiry", "right", "strike")

    def __init__(self, root: str, expiry, right: str, strike: float):
        self.root = root
        self.expiry = expiry
        self.right = right
        self.strike = strike

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"OccContract({self.root} {self.strike} {self.right} {self.expiry})"


def parse_occ_symbol(symbol: str):
    """Split an OCC symbol into its parts, or return None if it isn't one.

    Format: ROOT + YYMMDD + C|P + strike in thousandths, zero-padded to 8.
    e.g. "SPY260825C00745000" -> SPY, 2026-08-25, C, 745.0
    """
    m = re.match(r'^([A-Z]{1,6})(\d{6})([CP])(\d{8})$', (symbol or '').strip().upper())
    if not m:
        return None
    root, ymd, right, strike_raw = m.groups()
    try:
        expiry = _date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    return OccContract(root, expiry, right, int(strike_raw) / 1000.0)


def format_contract(option_symbol: Optional[str], fallback: str = "") -> str:
    """Human-readable contract name for notifications: "SPY $745 CALL 8/25".

    Falls back to the raw symbol (then `fallback`) when it isn't a parseable
    OCC symbol, so this is always safe to call on an equity ticker.
    """
    parsed = parse_occ_symbol(option_symbol or "")
    if parsed is None:
        return option_symbol or fallback
    strike = (
        f"{parsed.strike:,.0f}" if float(parsed.strike).is_integer()
        else f"{parsed.strike:,.2f}".rstrip('0').rstrip('.')
    )
    kind = "CALL" if parsed.right == "C" else "PUT"
    return f"{parsed.root} ${strike} {kind} {parsed.expiry.strftime('%-m/%-d')}"

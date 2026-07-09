"""
Symbol identification and parsing utilities.
"""
import re


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

"""
Trading Engine Module

This module contains the core trading execution components:
- trading_client_manager: Manages API clients (Alpaca/Schwab) with hot-swapping
"""
from .trading_client_manager import trading_manager, TradingClientManager

__all__ = ["trading_manager", "TradingClientManager"]

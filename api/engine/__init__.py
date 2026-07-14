"""
Trading Engine Module

This module contains the core trading execution components:
- trading_client_manager: Routes paper/live to Tradier SANDBOX/LIVE (only broker)
"""
from .trading_client_manager import trading_manager, TradingClientManager

__all__ = ["trading_manager", "TradingClientManager"]

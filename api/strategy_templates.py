"""
Predefined strategy templates for scalping and day trading.

Based on proven scalping strategies optimized for small accounts (<$25k).
These templates are READ-ONLY and serve as starting points for users to clone.
"""

from typing import Dict, Any, List


class StrategyTemplates:
    """Collection of predefined trading strategy templates (READ-ONLY)."""

    # Strategy type constants
    SCALPING_0DTE = "scalping_0dte"
    GAMMA_SCALPING = "gamma_scalping"
    MOMENTUM_SCALPING = "momentum_scalping"

    @staticmethod
    def get_all_templates() -> List[Dict[str, Any]]:
        """Get all available strategy templates."""
        return [
            StrategyTemplates.spy_0dte_scalping(),
            StrategyTemplates.tsla_0dte_scalping(),
            StrategyTemplates.qqq_0dte_scalping(),
            StrategyTemplates.nvda_0dte_scalping(),
            StrategyTemplates.aapl_0dte_scalping(),
            StrategyTemplates.amd_0dte_scalping(),
            StrategyTemplates.meta_0dte_scalping(),
            StrategyTemplates.amzn_0dte_scalping(),
        ]

    @staticmethod
    def get_template_by_id(template_id: str) -> Dict[str, Any]:
        """Get a specific template by ID."""
        templates = {t["template_id"]: t for t in StrategyTemplates.get_all_templates()}
        return templates.get(template_id)

    @staticmethod
    def spy_0dte_scalping() -> Dict[str, Any]:
        """
        SPY 0DTE Options Scalping Strategy

        Best for: Small accounts, highest liquidity, tightest spreads
        Risk: 1-2% per trade
        """
        return {
            "template_id": "spy_0dte_scalping",
            "name": "SPY 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Best strategy for small accounts. SPY has the tightest spreads and highest liquidity. Recommended for beginners.",
            "is_template": True,  # Flag to indicate this is a template
            "instruments": ["SPY"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                # Entry conditions
                "ema_period": 9,
                "use_vwap": True,

                # $TICK indicator (optional - disabled by default)
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",

                # Options criteria
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,

                # Liquidity filters (CRITICAL)
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.0,

                # Entry signals
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,

                # Risk management
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,

                # Exit conditions
                "take_profit_pct": 25,
                "stop_loss_pct": 50,
                "trailing_stop": True,
                "trailing_stop_activation": 15,
                "trailing_stop_distance": 10,

                # Time-based exits
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 30,

                # Filters
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 50.0,
            "take_profit_percentage": 25.0,
            "recommended_min_account_size": 1000,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "spy", "beginner-friendly"],
        }

    @staticmethod
    def tsla_0dte_scalping() -> Dict[str, Any]:
        """TSLA 0DTE Options Scalping - High volatility, experienced traders only."""
        return {
            "template_id": "tsla_0dte_scalping",
            "name": "TSLA 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Best single stock for scalping. Extremely liquid with violent moves. Higher risk than SPY - for experienced traders.",
            "is_template": True,
            "instruments": ["TSLA"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.5,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.0,
                "max_position_size_usd": 400,
                "max_contracts": 2,
                "take_profit_pct": 30,
                "stop_loss_pct": 40,
                "trailing_stop": True,
                "trailing_stop_activation": 20,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 20,
                "max_hold_time_minutes": 20,
                "avoid_economic_news": True,
                "check_market_regime": True,
                "gamma_scalping_mode": True,
            },
            "max_positions": 1,
            "stop_loss_percentage": 40.0,
            "take_profit_percentage": 30.0,
            "recommended_min_account_size": 2000,
            "difficulty": "advanced",
            "tags": ["options", "scalping", "0dte", "tsla", "high-volatility", "gamma"],
        }

    @staticmethod
    def qqq_0dte_scalping() -> Dict[str, Any]:
        """QQQ 0DTE Options Scalping - Tech-focused."""
        return {
            "template_id": "qqq_0dte_scalping",
            "name": "QQQ 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Tech-heavy index scalping. Slightly slower than SPY but still excellent liquidity.",
            "is_template": True,
            "instruments": ["QQQ"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.0,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,
                "take_profit_pct": 25,
                "stop_loss_pct": 50,
                "trailing_stop": True,
                "trailing_stop_activation": 15,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 30,
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 50.0,
            "take_profit_percentage": 25.0,
            "recommended_min_account_size": 1000,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "qqq", "tech"],
        }

    @staticmethod
    def nvda_0dte_scalping() -> Dict[str, Any]:
        """NVDA 0DTE Options Scalping - Highest gamma/vega."""
        return {
            "template_id": "nvda_0dte_scalping",
            "name": "NVDA 0DTE Scalping",
            "strategy_type": StrategyTemplates.GAMMA_SCALPING,
            "description": "Highest gamma/vega exposure. Moves violently. Only for experienced scalpers.",
            "is_template": True,
            "instruments": ["NVDA"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 3.0,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.0,
                "max_position_size_usd": 400,
                "max_contracts": 2,
                "take_profit_pct": 35,
                "stop_loss_pct": 40,
                "trailing_stop": True,
                "trailing_stop_activation": 20,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 20,
                "max_hold_time_minutes": 20,
                "avoid_economic_news": True,
                "check_market_regime": True,
                "gamma_scalping_mode": True,
            },
            "max_positions": 1,
            "stop_loss_percentage": 40.0,
            "take_profit_percentage": 35.0,
            "recommended_min_account_size": 2000,
            "difficulty": "advanced",
            "tags": ["options", "scalping", "0dte", "nvda", "gamma", "high-volatility"],
        }

    @staticmethod
    def aapl_0dte_scalping() -> Dict[str, Any]:
        """AAPL 0DTE scalping - Very good liquidity."""
        return {
            "template_id": "aapl_0dte_scalping",
            "name": "AAPL 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Very good single stock option. Tighter spreads than most, slower moves than TSLA.",
            "is_template": True,
            "instruments": ["AAPL"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.0,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,
                "take_profit_pct": 25,
                "stop_loss_pct": 50,
                "trailing_stop": True,
                "trailing_stop_activation": 15,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 30,
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 50.0,
            "take_profit_percentage": 25.0,
            "recommended_min_account_size": 1500,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "aapl"],
        }

    @staticmethod
    def amd_0dte_scalping() -> Dict[str, Any]:
        """AMD 0DTE scalping - Good liquidity."""
        return {
            "template_id": "amd_0dte_scalping",
            "name": "AMD 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Good tech stock for scalping. Similar to NVDA but less volatile.",
            "is_template": True,
            "instruments": ["AMD"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.5,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,
                "take_profit_pct": 30,
                "stop_loss_pct": 45,
                "trailing_stop": True,
                "trailing_stop_activation": 18,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 25,
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 45.0,
            "take_profit_percentage": 30.0,
            "recommended_min_account_size": 1500,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "amd", "tech"],
        }

    @staticmethod
    def meta_0dte_scalping() -> Dict[str, Any]:
        """META 0DTE scalping - Good liquidity."""
        return {
            "template_id": "meta_0dte_scalping",
            "name": "META 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Good liquidity META scalping. Decent option chains.",
            "is_template": True,
            "instruments": ["META"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.0,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,
                "take_profit_pct": 25,
                "stop_loss_pct": 50,
                "trailing_stop": True,
                "trailing_stop_activation": 15,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 30,
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 50.0,
            "take_profit_percentage": 25.0,
            "recommended_min_account_size": 1500,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "meta"],
        }

    @staticmethod
    def amzn_0dte_scalping() -> Dict[str, Any]:
        """AMZN 0DTE scalping - Good liquidity."""
        return {
            "template_id": "amzn_0dte_scalping",
            "name": "AMZN 0DTE Scalping",
            "strategy_type": StrategyTemplates.SCALPING_0DTE,
            "description": "Solid scalping option with good liquidity. Large cap stability.",
            "is_template": True,
            "instruments": ["AMZN"],
            "asset_type": "options",
            "timeframe": "1m",
            "params_json": {
                "ema_period": 9,
                "use_vwap": True,
                "use_tick_indicator": False,
                "tick_threshold": 800,
                "tick_direction": "either",
                "option_type": "0DTE",
                "delta_min": 0.60,
                "delta_max": 0.85,
                "min_open_interest": 3000,
                "max_bid_ask_spread": 0.20,
                "volume_spike_required": True,
                "min_volume_multiplier": 2.0,
                "entry_signal": "price_above_9ema_and_vwap",
                "confirmation_required": True,
                "risk_per_trade_pct": 1.5,
                "max_position_size_usd": 500,
                "max_contracts": 3,
                "take_profit_pct": 25,
                "stop_loss_pct": 50,
                "trailing_stop": True,
                "trailing_stop_activation": 15,
                "trailing_stop_distance": 10,
                "exit_before_close_minutes": 15,
                "max_hold_time_minutes": 30,
                "avoid_economic_news": True,
                "check_market_regime": True,
            },
            "max_positions": 2,
            "stop_loss_percentage": 50.0,
            "take_profit_percentage": 25.0,
            "recommended_min_account_size": 1500,
            "difficulty": "intermediate",
            "tags": ["options", "scalping", "0dte", "amzn"],
        }


# Best choice order for small accounts (priority ranking)
RECOMMENDED_ORDER = [
    "spy_0dte_scalping",  # #1 - Best overall
    "tsla_0dte_scalping",  # #2 - Best single stock
    "qqq_0dte_scalping",  # #3 - Tech index
    "nvda_0dte_scalping",  # #4 - High gamma
    "aapl_0dte_scalping",  # #5 - Stable single stock
    "amd_0dte_scalping",
    "meta_0dte_scalping",
    "amzn_0dte_scalping",
]

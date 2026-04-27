"""
Signal Generator - Technical indicators and entry/exit signal detection
Aligned with Strategy.params_json structure from strategy_templates.py
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
import numpy as np
from collections import deque

from models import Strategy
from utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

_market_hours = MarketHours()


class Signal:
    """Represents a trading signal"""
    def __init__(
        self,
        signal_type: str,  # 'entry' or 'exit'
        action: str,       # 'buy' or 'sell'
        symbol: str,
        confidence: float,  # 0.0 to 1.0
        reason: str,
        price: Optional[float] = None,
        indicators: Optional[Dict] = None
    ):
        self.signal_type = signal_type
        self.action = action
        self.symbol = symbol
        self.confidence = confidence
        self.reason = reason
        self.price = price
        self.indicators = indicators or {}
        self.timestamp = datetime.utcnow()

    def __repr__(self):
        return f"<Signal {self.signal_type.upper()} {self.action.upper()} {self.symbol} @ {self.confidence:.2f}>"


class SignalGenerator:
    """
    Generates trading signals based on:
    - Technical indicators (EMA, VWAP, RSI)
    - Volume analysis
    - Price action patterns
    - Strategy-specific parameters from params_json
    """

    def __init__(self):
        # Price history cache for indicator calculations
        self.price_history: Dict[str, deque] = {}
        self.volume_history: Dict[str, deque] = {}

        # Intraday VWAP accumulators — reset each trading day
        # { symbol: { 'date': date, 'sum_pv': float, 'sum_v': int } }
        self._vwap_accumulators: Dict[str, dict] = {}

        # Configuration
        self.max_history_length = 100  # Keep last 100 bars

    def check_entry_signal(
        self,
        strategy: Strategy,
        symbol: str,
        current_price: float,
        current_volume: int,
        additional_data: Optional[Dict] = None
    ) -> Optional[Signal]:
        """
        Check if current market conditions generate an entry signal
        Based on strategy.params_json structure from strategy_templates.py

        Args:
            strategy: Strategy object with params_json
            symbol: Trading symbol
            current_price: Current market price
            current_volume: Current volume
            additional_data: Additional market data (bid, ask, delta, greeks, etc.)

        Returns:
            Signal object if entry conditions met, None otherwise
        """
        # Update price history
        self._update_history(symbol, current_price, current_volume)

        params = strategy.params_json
        indicators = {}

        # 0. Enforce opening noise blackout window
        entry_after_open_minutes = params.get('entry_after_open_minutes', 0)
        if entry_after_open_minutes:
            current_et = _market_hours.get_current_et_time()
            market_open_et = current_et.replace(hour=9, minute=30, second=0, microsecond=0)
            minutes_since_open = (current_et - market_open_et).total_seconds() / 60
            if minutes_since_open < entry_after_open_minutes:
                logger.debug(
                    f"{symbol}: Opening noise window — {minutes_since_open:.1f} min since open "
                    f"(waiting for {entry_after_open_minutes} min)"
                )
                return None

        # 1. Check EMA condition
        ema_period = params.get('ema_period', 9)
        if ema_period:
            ema_value = self._calculate_ema(symbol, ema_period)
            if ema_value is not None:
                indicators['ema'] = ema_value

                # Check entry signal pattern
                entry_signal = params.get('entry_signal', 'price_above_9ema_and_vwap')

                # Price vs EMA check
                if 'above' in entry_signal.lower() and 'ema' in entry_signal.lower():
                    if current_price <= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above EMA ${ema_value:.2f}")
                        return None
                elif 'below' in entry_signal.lower() and 'ema' in entry_signal.lower():
                    if current_price >= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not below EMA ${ema_value:.2f}")
                        return None

        # 2. Check VWAP condition
        use_vwap = params.get('use_vwap', False)
        if use_vwap:
            vwap_value = self._calculate_vwap(symbol)
            if vwap_value is not None:
                indicators['vwap'] = vwap_value

                entry_signal = params.get('entry_signal', '')

                # Price vs VWAP check
                if 'above' in entry_signal.lower() and 'vwap' in entry_signal.lower():
                    if current_price <= vwap_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above VWAP ${vwap_value:.2f}")
                        return None
                elif 'below' in entry_signal.lower() and 'vwap' in entry_signal.lower():
                    if current_price >= vwap_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not below VWAP ${vwap_value:.2f}")
                        return None

        # 3. Check volume spike condition
        volume_spike_required = params.get('volume_spike_required', False)
        if volume_spike_required:
            min_volume_multiplier = params.get('min_volume_multiplier', 2.0)
            avg_volume = self._calculate_avg_volume(symbol, period=20)

            if avg_volume and avg_volume > 0:
                volume_ratio = current_volume / avg_volume
                indicators['volume_ratio'] = volume_ratio

                if volume_ratio < min_volume_multiplier:
                    logger.debug(
                        f"{symbol}: Volume spike {volume_ratio:.2f}x insufficient "
                        f"(need {min_volume_multiplier}x)"
                    )
                    return None

        # 4. Check delta range for options
        if additional_data and additional_data.get('delta') is not None:
            delta = abs(additional_data['delta'])
            delta_min = params.get('delta_min', 0.0)
            delta_max = params.get('delta_max', 1.0)

            indicators['delta'] = delta

            if not (delta_min <= delta <= delta_max):
                logger.debug(f"{symbol}: Delta {delta:.2f} outside range [{delta_min}, {delta_max}]")
                return None

        # 5. Check liquidity filters for options
        if additional_data:
            # Open interest check
            if additional_data.get('open_interest') is not None:
                min_oi = params.get('min_open_interest', 0)
                if additional_data['open_interest'] < min_oi:
                    logger.debug(f"{symbol}: Open interest {additional_data['open_interest']} < {min_oi}")
                    return None
                indicators['open_interest'] = additional_data['open_interest']

            # Bid-ask spread check
            bid = additional_data.get('bid')
            ask = additional_data.get('ask')
            if bid is not None and ask is not None and ask > 0:
                spread = (ask - bid) / ask
                max_spread = params.get('max_bid_ask_spread', 1.0)

                indicators['bid_ask_spread'] = spread

                if spread > max_spread:
                    logger.debug(f"{symbol}: Bid-ask spread {spread:.2%} > {max_spread:.2%}")
                    return None

        # 6. Check $TICK indicator if configured
        use_tick = params.get('use_tick_indicator', False)
        if use_tick and additional_data and 'tick_value' in additional_data:
            tick_value = additional_data['tick_value']
            tick_threshold = params.get('tick_threshold', 800)
            tick_direction = params.get('tick_direction', 'either')

            indicators['tick'] = tick_value

            # Check tick conditions
            if tick_direction == 'bullish' and tick_value < tick_threshold:
                logger.debug(f"{symbol}: $TICK {tick_value} not bullish (need > {tick_threshold})")
                return None
            elif tick_direction == 'bearish' and tick_value > -tick_threshold:
                logger.debug(f"{symbol}: $TICK {tick_value} not bearish (need < -{tick_threshold})")
                return None
            elif tick_direction == 'either':
                if abs(tick_value) < tick_threshold:
                    logger.debug(f"{symbol}: $TICK {tick_value} not strong enough (need |{tick_threshold}|)")
                    return None

        # 7. Confirmation required check
        confirmation_required = params.get('confirmation_required', False)
        if confirmation_required:
            # Require at least 2 indicators to align
            if len(indicators) < 2:
                logger.debug(f"{symbol}: Confirmation required but only {len(indicators)} indicators available")
                return None

        # All conditions passed - generate entry signal
        confidence = self._calculate_signal_confidence(indicators, params)

        # Determine action based on entry signal
        entry_signal_pattern = params.get('entry_signal', 'price_above_9ema_and_vwap')
        action = 'buy'  # Default to buy for long positions

        # Parse entry signal for direction
        if 'above' in entry_signal_pattern.lower():
            action = 'buy'  # Bullish
        elif 'below' in entry_signal_pattern.lower():
            action = 'sell'  # Bearish

        signal = Signal(
            signal_type='entry',
            action=action,
            symbol=symbol,
            confidence=confidence,
            reason=f"Entry conditions met: {', '.join(indicators.keys())}",
            price=current_price,
            indicators=indicators
        )

        logger.debug(f"Entry signal generated: {signal}")
        return signal

    def check_exit_signal(
        self,
        strategy: Strategy,
        symbol: str,
        entry_price: float,
        current_price: float,
        entry_timestamp: datetime,
        position_side: str,  # 'long' or 'short'
        current_high: Optional[float] = None,
        current_low: Optional[float] = None
    ) -> Optional[Signal]:
        """
        Check if exit conditions are met for an open position
        Based on strategy.params_json exit parameters

        Args:
            strategy: Strategy object with params_json
            symbol: Trading symbol
            entry_price: Original entry price
            current_price: Current market price
            entry_timestamp: When position was opened
            position_side: 'long' or 'short'
            current_high: Today's high for trailing stop
            current_low: Today's low for trailing stop

        Returns:
            Signal object if exit conditions met, None otherwise
        """
        params = strategy.params_json

        # Calculate P&L percentage
        if position_side == 'long':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # short
            pnl_pct = ((entry_price - current_price) / entry_price) * 100

        indicators = {
            'pnl_pct': pnl_pct,
            'entry_price': entry_price,
            'current_price': current_price
        }

        # 1. Take Profit check
        take_profit_pct = params.get('take_profit_pct') or params.get('take_profit_percentage')
        if take_profit_pct and pnl_pct >= take_profit_pct:
            return Signal(
                signal_type='exit',
                action='sell' if position_side == 'long' else 'buy',
                symbol=symbol,
                confidence=1.0,
                reason=f"Take profit hit: {pnl_pct:.2f}% >= {take_profit_pct}%",
                price=current_price,
                indicators=indicators
            )

        # 2. Stop Loss check
        stop_loss_pct = params.get('stop_loss_pct') or params.get('stop_loss_percentage')
        if stop_loss_pct and pnl_pct <= -stop_loss_pct:
            return Signal(
                signal_type='exit',
                action='sell' if position_side == 'long' else 'buy',
                symbol=symbol,
                confidence=1.0,
                reason=f"Stop loss hit: {pnl_pct:.2f}% <= -{stop_loss_pct}%",
                price=current_price,
                indicators=indicators
            )

        # 3. Trailing Stop check
        use_trailing_stop = params.get('trailing_stop', False)
        if use_trailing_stop:
            activation_pct = params.get('trailing_stop_activation', 15)
            trail_distance_pct = params.get('trailing_stop_distance', 10)

            # Only activate trailing stop if we've reached activation threshold
            if pnl_pct >= activation_pct:
                if position_side == 'long' and current_high:
                    # For longs: stop is trail_distance below the high
                    trailing_stop_price = current_high * (1 - trail_distance_pct / 100)
                    if current_price <= trailing_stop_price:
                        return Signal(
                            signal_type='exit',
                            action='sell',
                            symbol=symbol,
                            confidence=1.0,
                            reason=f"Trailing stop hit: ${current_price:.2f} <= ${trailing_stop_price:.2f}",
                            price=current_price,
                            indicators={**indicators, 'trailing_stop_price': trailing_stop_price}
                        )
                elif position_side == 'short' and current_low:
                    # For shorts: stop is trail_distance above the low
                    trailing_stop_price = current_low * (1 + trail_distance_pct / 100)
                    if current_price >= trailing_stop_price:
                        return Signal(
                            signal_type='exit',
                            action='buy',
                            symbol=symbol,
                            confidence=1.0,
                            reason=f"Trailing stop hit: ${current_price:.2f} >= ${trailing_stop_price:.2f}",
                            price=current_price,
                            indicators={**indicators, 'trailing_stop_price': trailing_stop_price}
                        )

        # 4. Max hold time exit
        max_hold_minutes = params.get('max_hold_time_minutes', None)
        if max_hold_minutes:
            time_held = (datetime.utcnow() - entry_timestamp).total_seconds() / 60
            if time_held >= max_hold_minutes:
                return Signal(
                    signal_type='exit',
                    action='sell' if position_side == 'long' else 'buy',
                    symbol=symbol,
                    confidence=0.8,
                    reason=f"Max hold time reached: {time_held:.1f} >= {max_hold_minutes} minutes",
                    price=current_price,
                    indicators={**indicators, 'time_held_minutes': time_held}
                )

        # 5. Exit before market close (for 0DTE strategies)
        exit_before_close_minutes = params.get('exit_before_close_minutes', None)
        if exit_before_close_minutes:
            current_et = _market_hours.get_current_et_time()
            close_time = _market_hours.get_market_close_time_et()
            market_close_et = current_et.replace(
                hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
            )
            exit_time_et = market_close_et - timedelta(minutes=exit_before_close_minutes)

            if current_et >= exit_time_et:
                return Signal(
                    signal_type='exit',
                    action='sell' if position_side == 'long' else 'buy',
                    symbol=symbol,
                    confidence=1.0,
                    reason=f"Market close approaching: {exit_before_close_minutes} minutes before close",
                    price=current_price,
                    indicators=indicators
                )

        # No exit signal
        return None

    # ========== Technical Indicator Calculations ==========

    def _update_history(self, symbol: str, price: float, volume: int):
        """Update price/volume history and intraday VWAP accumulator."""
        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history_length)
            self.volume_history[symbol] = deque(maxlen=self.max_history_length)

        self.price_history[symbol].append(price)
        self.volume_history[symbol].append(volume)

        # Intraday VWAP — cumulative from market open, resets each day
        today = date.today()
        acc = self._vwap_accumulators.get(symbol)
        if acc is None or acc["date"] != today:
            self._vwap_accumulators[symbol] = {"date": today, "sum_pv": 0.0, "sum_v": 0}
            acc = self._vwap_accumulators[symbol]
        if volume > 0:
            acc["sum_pv"] += price * volume
            acc["sum_v"] += volume

    def _calculate_ema(self, symbol: str, period: int) -> Optional[float]:
        """Calculate Exponential Moving Average"""
        if symbol not in self.price_history:
            return None

        prices = list(self.price_history[symbol])
        if len(prices) < period:
            return None

        # Simple EMA calculation
        multiplier = 2 / (period + 1)
        ema = prices[0]  # Start with first price

        for price in prices[1:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))

        return ema

    def _calculate_vwap(self, symbol: str) -> Optional[float]:
        """Intraday VWAP — cumulative sum(price * volume) / sum(volume) from market open."""
        acc = self._vwap_accumulators.get(symbol)
        if acc is None or acc["sum_v"] == 0:
            return None
        return acc["sum_pv"] / acc["sum_v"]

    def _calculate_avg_volume(self, symbol: str, period: int = 20) -> Optional[float]:
        """Calculate average volume over period"""
        if symbol not in self.volume_history:
            return None

        volumes = list(self.volume_history[symbol])
        if len(volumes) < period:
            return None

        return sum(volumes[-period:]) / period

    def _calculate_rsi(self, symbol: str, period: int = 14) -> Optional[float]:
        """Calculate Relative Strength Index"""
        if symbol not in self.price_history:
            return None

        prices = list(self.price_history[symbol])
        if len(prices) < period + 1:
            return None

        # Calculate price changes
        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Separate gains and losses
        gains = [c if c > 0 else 0 for c in changes[-period:]]
        losses = [-c if c < 0 else 0 for c in changes[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0  # No losses means RSI is 100

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_signal_confidence(
        self,
        indicators: Dict,
        params: Dict
    ) -> float:
        """
        Calculate confidence score for a signal based on how many
        conditions are met and their strength

        Returns:
            float: Confidence between 0.0 and 1.0
        """
        # Base confidence
        confidence = 0.6

        # Boost confidence based on indicator alignment
        if 'ema' in indicators and 'vwap' in indicators:
            confidence += 0.1  # Both trend indicators aligned

        if 'volume_ratio' in indicators and indicators['volume_ratio'] > 2.0:
            confidence += 0.1  # Strong volume confirmation

        if 'delta' in indicators:
            delta = indicators['delta']
            # Delta between 0.60-0.85 is ideal for 0DTE per templates
            delta_min = params.get('delta_min', 0.60)
            delta_max = params.get('delta_max', 0.85)
            if delta_min <= delta <= delta_max:
                confidence += 0.1

        if 'tick' in indicators:
            tick_threshold = params.get('tick_threshold', 800)
            if abs(indicators['tick']) >= tick_threshold:
                confidence += 0.1  # Strong market breadth confirmation

        if 'bid_ask_spread' in indicators and indicators['bid_ask_spread'] < 0.10:
            confidence += 0.05  # Tight spreads = better execution

        # Cap at 0.95 (never 100% certain)
        return min(confidence, 0.95)

    def clear_history(self, symbol: Optional[str] = None):
        """Clear price history and VWAP state for a symbol or all symbols."""
        if symbol:
            self.price_history.pop(symbol, None)
            self.volume_history.pop(symbol, None)
            self._vwap_accumulators.pop(symbol, None)
        else:
            self.price_history.clear()
            self.volume_history.clear()
            self._vwap_accumulators.clear()

"""
Signal Generator - Technical indicators and entry/exit signal detection
Aligned with Strategy.params_json structure from strategy_templates.py
"""
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
import numpy as np
from collections import deque

from models import Strategy, User
from utils.market_hours import MarketHours

logger = logging.getLogger(__name__)

_market_hours = MarketHours()

# Hard floor on the forced end-of-day exit, in minutes before the real close.
# The engine only ever holds 0DTE contracts, so anything still open at the bell
# either expires worthless or gets auto-exercised into stock a cash account
# cannot settle.
#
# `exit_before_close_minutes` already implements this and, where it is set, it
# works — it is the single most common exit reason in the trade history. The
# floor exists because it is OPT-IN: it is falsy when absent and when 0, and
# the strategy form defaulted it to 0, so a hand-built strategy silently had no
# time-of-day exit at all. The floor removes the off switch.
#
# It can only ever pull an exit EARLIER: combined with the strategy param and
# the account trading window by taking the MINIMUM exit time, so a strategy
# asking for 30 minutes still gets 30, while 0 or absent now gets 15.
#
# It is also the upper bound on ENTRIES (check_entry_signal), so the engine
# cannot open a position it is already obliged to close.
FORCED_EOD_EXIT_FLOOR_MINUTES = 15


# Which side of the option chain a strategy trades. This is the ONLY place
# direction is decided; the contract selector and the entry-signal path both
# call this so they cannot disagree about what we are about to buy.
VALID_DIRECTIONS = ('call', 'put')


def _names_a_bound(entry_signal: str, indicator: str) -> bool:
    """Does `entry_signal` ask for a price-vs-`indicator` bound at all?

    Requires BOTH the indicator name and a direction word, exactly as the
    pre-direction code did (`'above' in es and 'ema' in es`). Dropping the
    direction-word half would silently ADD a constraint to any hand-written
    entry_signal that names an indicator without one — "ema_crossover" imposed
    no price-vs-EMA bound before and must not start imposing one now.

    Which WAY the bound points is no longer read from here; that comes from
    resolve_direction. This only answers whether the bound exists.
    """
    es = (entry_signal or '').lower()
    return indicator in es and ('above' in es or 'below' in es)


def resolve_direction(params: Optional[Dict]) -> str:
    """Return 'call' or 'put' for a strategy's params_json.

    Direction is a property of the CONTRACT WE SELECT, never of the order side.
    A long put is opened with buy_to_open and closed with sell_to_close exactly
    like a long call — bearish intent is expressed by buying a put, not by
    selling. See the note in check_entry_signal.

    Explicit `direction` wins. Absent it, infer from the `entry_signal` phrasing
    so the shipped templates ("price_above_9ema_and_vwap") keep resolving to
    'call' with no migration. Anything unrecognised falls back to 'call', which
    is what every strategy did before this existed.
    """
    params = params or {}
    explicit = str(params.get('direction', '') or '').strip().lower()
    if explicit in VALID_DIRECTIONS:
        return explicit
    if explicit:
        logger.warning(
            f"Unknown direction {explicit!r} in params_json — defaulting to 'call'"
        )
        return 'call'

    pattern = str(params.get('entry_signal', '') or '').lower()
    # 'above' is tested FIRST, matching the order the pre-direction code used.
    # A pattern naming both bounds therefore reads as bullish, exactly as it did
    # before this function existed. Do not reorder these two tests: it would
    # silently invert the side traded by any range-phrased strategy.
    if 'above' in pattern:
        return 'call'
    if 'below' in pattern:
        return 'put'
    return 'call'


def _parse_hhmm(value: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse "HH:MM" into (hour, minute), or return None if invalid/empty."""
    if not value or ":" not in value:
        return None
    try:
        h_str, m_str = value.split(":", 1)
        h, m = int(h_str), int(m_str)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except (ValueError, TypeError):
        pass
    return None


def forced_exit_time_et(
    params: Dict,
    user: Optional[User],
    current_et: datetime,
) -> Tuple[Optional[datetime], Optional[str]]:
    """The wall-clock ET time after which an open position MUST be closed, and
    why. Returns (time, reason).

    Effective time is the earliest of:
      - floor:    market_close - FORCED_EOD_EXIT_FLOOR_MINUTES  (unconditional)
      - strategy: market_close - params['exit_before_close_minutes']
      - account:  user.trading_window_end (when trading_window_enabled)

    Most-restrictive-bound wins: any input can pull the exit earlier, none can
    push it later. Module-level rather than a method because the executor needs
    the same answer to decide whether to force a close when no quote is
    available — the rule must not be written down twice.
    """
    close_time = _market_hours.get_market_close_time_et()
    market_close_et = current_et.replace(
        hour=close_time.hour, minute=close_time.minute, second=0, microsecond=0
    )

    # The floor always participates. A strategy asking to exit EARLIER wins
    # below; one asking for later — or asking for nothing at all — is clamped
    # to the floor. Nothing this engine holds is safe overnight.
    exit_time_et: Optional[datetime] = market_close_et - timedelta(
        minutes=FORCED_EOD_EXIT_FLOOR_MINUTES
    )
    exit_reason: Optional[str] = (
        f"End of day: forced exit {FORCED_EOD_EXIT_FLOOR_MINUTES} minutes before close"
    )

    exit_before_close_minutes = (params or {}).get('exit_before_close_minutes', None)
    if exit_before_close_minutes:
        strategy_exit_et = market_close_et - timedelta(minutes=exit_before_close_minutes)
        if strategy_exit_et < exit_time_et:
            exit_time_et = strategy_exit_et
            exit_reason = (
                f"Market close approaching: {exit_before_close_minutes} minutes before close"
            )

    if user is not None and getattr(user, 'trading_window_enabled', False):
        window_end = _parse_hhmm(getattr(user, 'trading_window_end', None))
        if window_end is not None:
            account_end_et = current_et.replace(
                hour=window_end[0], minute=window_end[1], second=0, microsecond=0
            )
            if account_end_et < exit_time_et:
                exit_time_et = account_end_et
                exit_reason = (
                    f"Account trading window ended at {account_end_et.strftime('%H:%M')} ET"
                )

    return exit_time_et, exit_reason


def forced_exit_due(params: Dict, user: Optional[User]) -> Optional[str]:
    """Reason string if an open position is past its forced-exit time right now,
    else None. Used by the executor to close a position even when it cannot
    price it — a market sell needs no quote, and an unsold 0DTE is worse than
    an unpriced one."""
    current_et = _market_hours.get_current_et_time()
    exit_time_et, reason = forced_exit_time_et(params, user, current_et)
    if exit_time_et is not None and current_et >= exit_time_et:
        return reason or "Forced exit: trading window closed"
    return None


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
        additional_data: Optional[Dict] = None,
        user: Optional[User] = None
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

        # Which way this strategy needs price to break. Resolved ONCE here and
        # used both for the comparisons below and for the contract the worker
        # arms, so the trigger and the instrument can never disagree.
        #
        # This used to be read off the `entry_signal` wording independently of
        # `direction`, which meant a strategy set to Puts still required price
        # ABOVE the 9EMA/VWAP — it bought puts into upward momentum. The form
        # exposes `direction` and not `entry_signal`, so that was the DEFAULT
        # outcome of choosing Puts, not an edge case.
        #
        # `entry_signal` still selects WHICH indicators gate the entry (naming
        # 'ema' and/or 'vwap'); only the direction of the comparison moved.
        direction = resolve_direction(params)
        wants_upside = direction == 'call'

        # 0. Entry-time gate — a lower AND an upper bound on when we may open.
        #
        # LOWER: later of market_open + entry_after_open_minutes (opening-noise
        # blackout) and user.trading_window_start, so neither can widen the other.
        #
        # UPPER: the forced-exit time itself. Never open a position we are
        # already obliged to close — the very next tick would sell it. Until
        # this bound existed the upper bound came ONLY from the account trading
        # window, which is opt-in and was off: between 2026-07-15 and 08-21 the
        # engine placed 174 entries after the 15:45 forced exit, each sold
        # within seconds for a net -$1,064 in spread. One of them (2026-07-31
        # 16:00:41) straddled the bell, never exited, and expired — which is the
        # position the Saturday reconcile then booked at the underlying's price
        # for a phantom +$223,119.
        #
        # Reusing forced_exit_time_et() rather than re-deriving the bound means
        # the two can never drift apart: entries stop exactly when exits start.
        current_et = _market_hours.get_current_et_time()
        market_open_et = current_et.replace(hour=9, minute=30, second=0, microsecond=0)

        entry_after_open_minutes = params.get('entry_after_open_minutes', 0)
        effective_start_et = market_open_et
        if entry_after_open_minutes:
            effective_start_et = market_open_et + timedelta(minutes=entry_after_open_minutes)

        if user is not None and getattr(user, 'trading_window_enabled', False):
            window_start = _parse_hhmm(getattr(user, 'trading_window_start', None))
            if window_start is not None:
                account_start_et = current_et.replace(
                    hour=window_start[0], minute=window_start[1], second=0, microsecond=0
                )
                if account_start_et > effective_start_et:
                    effective_start_et = account_start_et

        if current_et < effective_start_et:
            logger.debug(
                f"{symbol}: Trading window not yet open — current ET "
                f"{current_et.strftime('%H:%M')} < earliest entry "
                f"{effective_start_et.strftime('%H:%M')}"
            )
            return None

        entry_cutoff_et, cutoff_reason = forced_exit_time_et(params, user, current_et)
        if entry_cutoff_et is not None and current_et >= entry_cutoff_et:
            logger.debug(
                f"{symbol}: No new entries — current ET {current_et.strftime('%H:%M')} "
                f">= forced-exit time {entry_cutoff_et.strftime('%H:%M')} ({cutoff_reason})"
            )
            return None

        # 1. Check EMA condition
        ema_period = params.get('ema_period', 9)
        if ema_period:
            ema_value = self._calculate_ema(symbol, ema_period)
            if ema_value is not None:
                indicators['ema'] = ema_value

                # `entry_signal` decides whether EMA gates the entry at all;
                # `direction` decides which side of it we need.
                entry_signal = params.get('entry_signal', 'price_above_9ema_and_vwap')

                if _names_a_bound(entry_signal, 'ema'):
                    if wants_upside and current_price <= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above EMA ${ema_value:.2f}")
                        return None
                    if not wants_upside and current_price >= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not below EMA ${ema_value:.2f}")
                        return None

        # 2. Check VWAP condition
        use_vwap = params.get('use_vwap', False)
        if use_vwap:
            vwap_value = self._calculate_vwap(symbol)
            if vwap_value is not None:
                indicators['vwap'] = vwap_value

                # Default '' on purpose: with no entry_signal named, VWAP does
                # not gate the entry even when use_vwap is on. Unchanged.
                entry_signal = params.get('entry_signal', '')

                if _names_a_bound(entry_signal, 'vwap'):
                    if wants_upside and current_price <= vwap_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above VWAP ${vwap_value:.2f}")
                        return None
                    if not wants_upside and current_price >= vwap_value:
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

        # An ENTRY is always a buy.
        #
        # This used to read `action = 'sell'` when the entry_signal named
        # 'below', meaning to express bearishness. That was wrong at the level
        # of the mental model: `action` becomes the Tradier side, and
        # trading_client_manager maps 'sell' to sell_to_close. A bearish entry
        # therefore tried to CLOSE a call we did not own, and it slipped the
        # RBAC gate in execute_signal, which only checks side == 'buy'.
        #
        # Bearish intent is a PUT, bought to open. Direction picks the contract
        # (resolve_direction, used by the worker's chain scan); the order side
        # stays buy-to-open on entry and sell-to-close on exit for both.
        action = 'buy'
        indicators['direction'] = direction

        signal = Signal(
            signal_type='entry',
            action=action,
            symbol=symbol,
            confidence=confidence,
            reason=(
                f"Entry conditions met ({direction}): "
                f"{', '.join(k for k in indicators if k != 'direction')}"
            ),
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
        current_low: Optional[float] = None,
        user: Optional[User] = None
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

        # 5. Time-of-day exit — see forced_exit_time_et() for how the floor,
        # the strategy param and the account window compose (earliest wins).
        current_et = _market_hours.get_current_et_time()
        exit_time_et, exit_reason = forced_exit_time_et(params, user, current_et)

        if exit_time_et is not None and current_et >= exit_time_et:
            return Signal(
                signal_type='exit',
                action='sell' if position_side == 'long' else 'buy',
                symbol=symbol,
                confidence=1.0,
                reason=exit_reason or "Forced exit: trading window closed",
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

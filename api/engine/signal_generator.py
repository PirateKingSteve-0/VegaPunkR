"""
Signal Generator - Technical indicators and entry/exit signal detection
Aligned with Strategy.params_json structure from strategy_templates.py
"""
import logging
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
import numpy as np
from collections import deque

from models import Strategy, User
from utils.market_hours import HALT_MODE_FLATTEN, MarketHours, trading_halt_state

logger = logging.getLogger(__name__)

_market_hours = MarketHours()

# ---------------------------------------------------------------------------
# THE TIME CONSTANTS AND WHAT EACH ONE BOUNDS
#
# Seven settings in this engine are measured in minutes or clock time, and they
# do NOT all bound the same thing. Confusing which is which is how an entry rule
# becomes an exit trigger, so:
#
#   LOWER bound on ENTRY (earliest we may open)
#     params_json.entry_after_open_minutes   relative to 09:30 ET
#     User.trading_window_start              absolute ET, account-wide
#
#   UPPER bound on ENTRY (latest we may open) — see entry_cutoff_time_et
#     params_json.entry_before_et            absolute ET, the midday/theta wall
#     ...plus the forced-exit time below, because we must never open a position
#        we are already obliged to close
#
#   Bound on the EXIT (when an OPEN position must be closed) — forced_exit_time_et
#     params_json.exit_before_close_minutes  relative to the close, backwards
#     User.trading_window_end                absolute ET, account-wide
#     FORCED_EOD_EXIT_FLOOR_MINUTES          the unconditional floor
#
#   NOT A CLOCK BOUND AT ALL
#     _VWAP_WARMUP_MINUTES                   data sufficiency: how much session
#       the VWAP accumulator must have behind it before its dispersion means
#       anything. Measured in minutes, but it gates a NUMBER's trustworthiness,
#       not a time of day. It is the one most likely to be mistaken for a clock
#       rule, and it is also coupled to entry_after_open_minutes — see its own
#       comment for why 30-vs-30 is closer than it looks.
#
# The asymmetry that matters: every ENTRY bound composes most-restrictive-wins
# and may only narrow the window. An entry bound must NEVER be routed through
# forced_exit_time_et, because everything there flattens open positions.
# `User.trading_window_end` is the cautionary case — it is an account "window"
# whose end genuinely does force closes, which is why `entry_before_et` is a
# separate bound in a separate function rather than another branch beside it.
# ---------------------------------------------------------------------------

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
    """Parse "HH:MM" into (hour, minute), or return None if invalid/empty.

    The isinstance guard is load-bearing, not defensive noise. `":" not in value`
    raises TypeError on a non-string, and the try/except below starts one line too
    late to catch it — so this function used to violate its own "return None if
    invalid" contract for any non-string input. That was unreachable while the
    only callers were `User.trading_window_start`/`_end`, which are String
    columns, but `entry_before_et` arrives from `params_json`, which is JSON and
    can hold `1130` as an int. A raise there propagates out of
    check_entry_signal into the executor's error counter, and 20 of those stop
    the strategy outright — a typo'd config value would have taken the strategy
    down rather than being ignored.

    None means "no bound", which for every caller is the same as the field being
    unset. It cannot widen anything.
    """
    if not isinstance(value, str) or not value or ":" not in value:
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

    # "Done for the day", flatten mode: the forced exit is due right now.
    #
    # Expressed as a bound on the exit TIME rather than as a new branch in the
    # executor so it reaches every existing consumer for free — the exit signal
    # (check_exit_signal step 5), the unpriced-contract market close
    # (strategy_executor), and the entry cutoff (check_entry_signal) — with no
    # second copy of the rule and no new order path. The close it produces is
    # the same well-worn forced-EOD close that runs every afternoon.
    #
    # Most-restrictive-bound holds: `current_et` is by definition no later than
    # any other candidate, so this can only pull the exit earlier. The guard
    # keeps a genuine EOD/window reason when we are already past that time —
    # the more specific reason is the more useful one in the trade record.
    #
    # 'ride' mode deliberately does nothing here: it stops entries (the risk
    # manager's job) and leaves exits exactly as they were.
    halted, halt_mode = trading_halt_state(user)
    if halted and halt_mode == HALT_MODE_FLATTEN and current_et < exit_time_et:
        exit_time_et = current_et
        exit_reason = "Trading stopped for the day: closing open positions at market"

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


_bad_entry_before_logged = set()


def entry_cutoff_time_et(
    params: Dict,
    user: Optional[User],
    current_et: datetime,
) -> Tuple[Optional[datetime], Optional[str]]:
    """The wall-clock ET time after which no NEW entry may be opened, and why.

    Effective time is the earliest of:
      - the forced-exit time (forced_exit_time_et) — never open a position we
        are already obliged to close; the next tick would sell it.
      - strategy: params['entry_before_et'], an absolute "HH:MM" ET wall.

    ENTRY-ONLY, and that is the whole reason this function exists separately
    from forced_exit_time_et rather than as another branch inside it. An entry
    cutoff and a forced exit are different things: the cutoff must stop us
    BUYING at 11:30 while leaving a position opened at 10:09 free to run to its
    target at 11:04-or-whenever, governed only by stop loss, take profit, the
    trail and the EOD clock. `User.trading_window_end` conflates the two — it
    feeds forced_exit_time_et, so setting it to 11:30 would FLATTEN open
    positions at 11:30, not merely stop new ones. Putting `entry_before_et`
    anywhere near the exit path would repeat that mistake. Nothing here may pull
    an exit earlier or later; exits are sacred.

    Most-restrictive-bound wins: either input can pull the cutoff earlier,
    neither can push it later, and this can only ever NARROW what
    entry_after_open_minutes / user.trading_window_start already allow.

    WHY A CLOCK WALL AT ALL. Measured over 6 recorded session log pairs / 9
    trading days / 146 replayed round trips (scripts/replay_session.py --all
    --sweep window): entries taken from 11:30 ET onward lost money on 7 of those
    9 days, -$716 across 117 trades, while the 29 entries before 11:30 made
    +$311. Two mechanisms drive it and both are independent of any indicator:
    SPY volume troughs over lunch (median 97,052/min at 09:30 against 33,950 at
    12:30), and theta over a 30-minute hold runs ~2% at 10:00 ET against ~28% at
    15:30 — so a late entry is stopped out by the clock rather than by the
    signal being wrong. On 2026-09-15 live this cost a real trade: a 12:30 ET
    entry gave back $54 of the $192 the two morning entries had made.

    The NUMBER is chosen on those mechanisms, NOT tuned on the sweep. 11:00 and
    11:30 are inside each other's confidence intervals (the 11:30 row's is
    -7.86% to +11.27%, which includes zero); what the data establishes is the
    SHAPE — later is worse — not the minute. Do not retune it against the
    sessions on disk; that is the discipline TODO.md G4b sets for
    `vwap_max_stretch` and it applies here too.

    Absolute ET rather than minutes-before-close on purpose: on a half day
    (13:00 ET close) a "270 minutes before close" wall would land at 08:30 and
    block the entire session, while 11:30 still sits correctly inside a
    09:30-13:00 session. Half days need no special case — get_market_close_time_et
    reads Tradier's clock, so the forced-exit bound compresses on its own and
    the earliest-wins rule below handles the rest.
    """
    cutoff_et, reason = forced_exit_time_et(params, user, current_et)

    raw_before = (params or {}).get('entry_before_et')
    entry_before = _parse_hhmm(raw_before)
    if raw_before not in (None, '') and entry_before is None:
        # Present but unreadable -- "11.30", 1130, "11:60". The wall then does
        # not exist, and the operator has no way to know: this is the only gate
        # in the entry chain that fails OPEN. It stays that way on purpose
        # (_parse_hhmm's "None == unset" contract is shared with
        # forced_exit_time_et, and blocking every entry on a typo would stop the
        # strategy outright), but it must not also be SILENT -- the failure mode
        # is believing an afternoon cutoff is live while entries run all day.
        # Contrast _coerce_max_stretch, which fails closed because its contract
        # is not shared. Logged once per distinct bad value, so a
        # corrected-then-re-broken config speaks again.
        key = repr(raw_before)
        if key not in _bad_entry_before_logged:
            _bad_entry_before_logged.add(key)
            logger.error(
                f"entry_before_et={raw_before!r} is not \"HH:MM\" ET — NO entry "
                f"cutoff is in effect; entries run until the forced-exit time "
                f"until this is corrected"
            )
    if entry_before is not None:
        wall_et = current_et.replace(
            hour=entry_before[0], minute=entry_before[1], second=0, microsecond=0
        )
        if cutoff_et is None or wall_et < cutoff_et:
            cutoff_et = wall_et
            reason = (
                f"No new entries after {wall_et.strftime('%H:%M')} ET "
                f"(midday volume trough and theta decay); open positions "
                f"continue to run"
            )

    return cutoff_et, reason


def entry_cutoff_reached(params: Dict, user: Optional[User]) -> Optional[str]:
    """Reason string if NEW entries are closed for the day right now, else None.

    Sibling of forced_exit_due, and the same rationale: the executor needs this
    answer to log ENTRY_BLOCKED_TIME_WINDOW without re-deriving the bound, so
    the rule is written down exactly once. check_entry_signal enforces the gate
    independently — this is for observability, never the only thing standing
    between a late signal and an order.
    """
    current_et = _market_hours.get_current_et_time()
    cutoff_et, reason = entry_cutoff_time_et(params, user, current_et)
    if cutoff_et is not None and current_et >= cutoff_et:
        return reason or "No new entries: entry window closed"
    return None


# Keys written into `indicators` purely so the value is RECORDED, which are
# not themselves entry conditions.
#
# `indicators` has three consumers beyond storage. Two would misread a bare
# observation:
#   1. the `confirmation_required` gate counts len(indicators) < 2 as "not
#      enough agreement" -- so logging an always-present value would let a
#      strategy clear the gate on ONE real indicator instead of two. That is a
#      gate WIDENING, which the engine rules forbid, and
#      `confirmation_required: true` is live on both prod strategies today.
#   2. the signal `reason` string joins these keys, so an observation would be
#      reported to the trade record as a condition that was met.
#
# The third, _calculate_signal_confidence, matches exact keys ('ema', 'vwap',
# 'volume_ratio', 'delta', 'tick', 'bid_ask_spread') and so ignores anything
# listed here -- but it is the next thing to check when a key is added.
#
# Anything added here must be a value we only observe. A key that actually
# gates an entry does NOT belong in this set.
_OBSERVED_NOT_GATED = frozenset({'vwap_stretch'})


# Minutes of session the VWAP tally must cover before the stretch gate will
# act on it. Only consulted when `vwap_max_stretch` is set, so it is inert on a
# strategy that has not opted in. See the warm-up note in check_entry_signal.
#
# COUPLED TO `entry_after_open_minutes`, WHICH IS ALSO 30 ON BOTH PROD
# STRATEGIES. The coupling is accidental and the margin is milliseconds: the
# accumulator's first in-hours print lands 22-328 ms AFTER 09:30:00 on all nine
# recorded sessions, so at 10:00:00.000 -- the first instant the entry window is
# open -- the age is 29.99 minutes and this gate blocks. It passes a second
# later, so the cost today is one evaluation a day.
#
# The trap is the direction of travel: lower `entry_after_open_minutes` below 30
# (or raise this above it) and the guard starts silently eating the beginning of
# the entry window, which would look like a strategy that mysteriously stopped
# taking early trades. If you change either number, check it against the other.
_VWAP_WARMUP_MINUTES = 30


_bad_max_stretch_logged = set()


def _coerce_max_stretch(raw, symbol):
    """Validate `vwap_max_stretch`, or block by returning a value that blocks.

    The strategy form carries a field for it ("Don't Chase Past", number input,
    submitted as a float or null), but params_json is also reachable by script,
    by the API directly and by hand -- where a JSON string ("1.0") or a stray 0
    is easy to produce. Left raw, a string raised TypeError out of the middle of
    check_entry_signal on EVERY tick; the executor catches it, and twenty
    consecutive errors auto-deactivate the strategy. The failure was real but
    unreadable.

    Most-restrictive-bound wins, so a value we cannot make sense of BLOCKS
    rather than being ignored -- ignoring it would silently widen the entry
    path back to un-gated. The error is logged once per symbol so the cause is
    visible instead of arriving as a deactivation twenty ticks later.
    """
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = None
    # bool is an int subclass: `true` would otherwise silently mean 1.0.
    if isinstance(raw, bool) or value is None or value <= 0 or value != value:
        if symbol not in _bad_max_stretch_logged:
            _bad_max_stretch_logged.add(symbol)
            logger.error(
                f"{symbol}: vwap_max_stretch={raw!r} is not a positive number — "
                f"blocking entries until it is corrected"
            )
        return float('-inf')  # every stretch is >= this, so every entry blocks
    return value


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
        # { symbol: { 'date', 'sum_pv', 'sum_v', 'sum_p2v',
        #             'first_ts', 'last_ts' } }
        # sum_p2v (price**2 * volume) exists only to derive the volume-weighted
        # standard deviation of price around VWAP -- the "wiggle". See
        # _calculate_vwap_wiggle and TODO.md G4b.
        self._vwap_accumulators: Dict[str, dict] = {}

        # The in-progress 1-minute bar, flushed into the deques above when the
        # clock crosses a minute boundary. Before 2026-09-10 there was no bar:
        # _update_history appended one entry per CALL, and the caller runs once
        # a second (stream_driven_worker._EVAL_INTERVAL), so `ema_period: 9`
        # was a 9-SECOND EMA. Measured against the tape it crossed spot ~12
        # times a minute where a real 9-minute EMA crosses 0.2 — it tracked
        # price instead of trend and gated nothing. See TODO.md G3.
        # { symbol: {'minute', 'close', 'cv_open', 'cv_last'} }
        self._current_bar: Dict[str, dict] = {}

        # Configuration — these are BARS, and one bar is one minute.
        self.max_history_length = 100  # 100 one-minute bars

        # Rate limit for the don't-chase INFO line: { (strategy_id, symbol):
        # [monotonic time of last line, blocks suppressed since] }. See the
        # stretch gate in check_entry_signal for why it is throttled.
        self._not_chasing_log: Dict[tuple, list] = {}

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
        # History is NOT updated here. It is fed unconditionally from
        # strategy_executor.execute_strategy_tick, because this function is
        # skipped entirely while a position is open or during the re-entry
        # cooldown — so folding the update in here froze every indicator for
        # the whole duration of each trade, and re-entry decisions were then
        # made against an EMA whose samples straddled the gap. See TODO.md G3.
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

        # entry_cutoff_time_et, not forced_exit_time_et: it returns the SAME
        # forced-exit bound plus the optional `entry_before_et` wall, earliest
        # wins. Going through one function keeps the two consumers of this answer
        # — here, and the executor's ENTRY_BLOCKED_TIME_WINDOW event — from
        # drifting apart. Exits still read forced_exit_time_et directly and are
        # unaffected by the wall.
        entry_cutoff_et, cutoff_reason = entry_cutoff_time_et(params, user, current_et)
        if entry_cutoff_et is not None and current_et >= entry_cutoff_et:
            logger.debug(
                f"{symbol}: No new entries — current ET {current_et.strftime('%H:%M')} "
                f">= entry cutoff {entry_cutoff_et.strftime('%H:%M')} ({cutoff_reason})"
            )
            return None

        # 1. Check EMA condition
        ema_period = params.get('ema_period', 9)
        if ema_period:
            ema_value = self._calculate_ema(symbol, ema_period)
            entry_signal = params.get('entry_signal', 'price_above_9ema_and_vwap')
            ema_gates = _names_a_bound(entry_signal, 'ema')

            # An EMA we cannot compute BLOCKS the entry when the strategy is
            # configured to gate on it. It used to fall through and trade with
            # no EMA check at all, silently: `_calculate_ema` returns None
            # whenever history is shorter than `ema_period`, so setting a period
            # above `max_history_length` DELETED the filter rather than
            # lengthening it, and nothing logged that. Now that a bar is a
            # minute rather than a second, warm-up is ~`ema_period` minutes
            # instead of seconds, which would have turned that quiet hole into a
            # real unguarded window after every restart. Most-restrictive-bound
            # wins: no indicator, no entry. Exits are untouched.
            if ema_value is None:
                if ema_gates:
                    logger.debug(
                        f"{symbol}: EMA({ema_period}) not available yet "
                        f"({len(self.price_history.get(symbol, ()))} bars) — entry blocked"
                    )
                    return None
            else:
                indicators['ema'] = ema_value

                # `entry_signal` decides whether EMA gates the entry at all;
                # `direction` decides which side of it we need.
                if ema_gates:
                    if wants_upside and current_price <= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above EMA ${ema_value:.2f}")
                        return None
                    if not wants_upside and current_price >= ema_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not below EMA ${ema_value:.2f}")
                        return None

        # 2. Check VWAP condition
        use_vwap = params.get('use_vwap', False)

        # `vwap_max_stretch` is a SEPARATE opt-in from `use_vwap`: the side
        # check and the distance check are different questions about the same
        # line, and a strategy may want either, both, or neither.
        #
        # It is read OUTSIDE `if use_vwap` on purpose. Nesting it made a
        # configured don't-chase gate SILENTLY INERT whenever use_vwap was
        # false -- price five wiggles out still fired, with nothing logged at
        # any level. That is the one direction this file must never fail in: a
        # gate the operator configured has to either work or block, never
        # quietly do nothing.
        max_stretch = _coerce_max_stretch(params.get('vwap_max_stretch'), symbol)

        if use_vwap or max_stretch is not None:
            vwap_value = self._calculate_vwap(symbol)
            # Default '' on purpose: with no entry_signal named, VWAP does
            # not gate the entry even when use_vwap is on. Unchanged.
            entry_signal = params.get('entry_signal', '')
            # The side check belongs to use_vwap. A strategy that opted into
            # the distance check alone does NOT acquire a side check it never
            # asked for.
            vwap_gates = _names_a_bound(entry_signal, 'vwap') if use_vwap else False

            # Same most-restrictive rule as the EMA above: if VWAP is supposed
            # to gate and has no value yet (no volume accumulated this session),
            # block rather than trade ungated.
            if vwap_value is None:
                if vwap_gates or max_stretch is not None:
                    logger.debug(f"{symbol}: VWAP not available yet — entry blocked")
                    return None
            else:
                # Recorded only when use_vwap asked for it. Writing it whenever
                # the STRETCH gate is on would add a key to `indicators` that
                # the confirmation count treats as a second agreeing indicator
                # -- i.e. enabling a blocking gate would make confirmation
                # EASIER to clear. Tightening a gate must never loosen another.
                if use_vwap:
                    indicators['vwap'] = vwap_value

                if vwap_gates:
                    if wants_upside and current_price <= vwap_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not above VWAP ${vwap_value:.2f}")
                        return None
                    if not wants_upside and current_price >= vwap_value:
                        logger.debug(f"{symbol}: Price ${current_price:.2f} not below VWAP ${vwap_value:.2f}")
                        return None

                # DON'T CHASE (TODO.md G4b).
                #
                # The side check above is a trend-following bet -- calls when
                # price is above the line, puts when below -- and at moderate
                # stretch the tape does the OPPOSITE. Over 20 sessions of SPY
                # 1-minute bars, price sitting 1+ wiggles out drifts ~3.0 bp
                # back TOWARD VWAP over the next 30 minutes (shuffle test
                # p = 0.001, same sign in both 10-day halves). Our own trades
                # agree: the 27 replayed entries made 1-2 wiggles past VWAP won
                # 22% and lost $534 -- more than the whole strategy's $425.
                #
                # So "above VWAP" is not strength on its own. The side check is
                # fine near the line; it goes wrong exactly when price has
                # already run, which is when this gate declines to chase it.
                #
                # Measured in WIGGLES, never dollars -- see _calculate_vwap_wiggle.
                #
                # ENTRIES ONLY. No exit path reads this, so a position already
                # open stays closeable by stop loss, take profit, trailing and
                # the forced-exit clock exactly as before.
                #
                # ON THE REPLAY NUMBER, AND WHY IT IS NOT EVIDENCE FOR 1.0:
                #
                # TODO.md G4b reports "-$425 -> -$54" for a 1.0 block. That
                # figure is reproducible only by POST-FILTERING the baseline
                # trade list -- deleting the entries made >= 1.0 wiggles out and
                # keeping the rest. Re-running the replay with the gate live
                # INSIDE the strategy gives -$405 -> -$163 (n=146 -> 116),
                # in SESSION_WIGGLE units,
                # because blocking a chase leaves the strategy flat and a later
                # signal takes the freed slot. ~3 net extra trades cost ~$71.
                # That is the replacement effect TODO.md already predicted, and
                # it roughly halves the apparent gain.
                #
                # Worse, the remaining benefit is not spread across the sample:
                # +245 of the +242 total lands on 2026-09-10 and 2026-09-11
                # alone; the other seven sessions net -$3 combined. Those two
                # are exactly the sessions where the engine RESTARTED mid-day,
                # and where this accumulator's wiggle diverges hardest from a
                # full-session one (measured: 0.69 vs 1.24, and 0.58 vs 2.44).
                # So the replay's apparent confirmation rests on a wiggle the
                # live engine would not have computed on the only two days that
                # carry the result. Whether the real engine would have done
                # better or worse there is UNKNOWN -- it would have blocked more
                # and taken a different trade set entirely.
                #
                # The independent evidence is the drift test, which does not
                # depend on the replay: across 24 sessions, price 0.5-2 wiggles
                # out drifts back toward VWAP over 30m, both halves agree in
                # sign, shuffle p = 0.000, and the sample is 6 up / 18 down.
                # That supports the IDEA. It does not calibrate the THRESHOLD.
                #
                # AND THE REPLAY FIGURE NEEDS CONVERTING BEFORE IT IS QUOTED.
                # Because engine_wiggle runs ~0.962 of session_wiggle, this gate
                # firing at 1.0 blocks at |price - vwap| >= 0.962 session_wiggle.
                # The replay measures in session_wiggle, so modelling production
                # means running it at 0.962, not at 1.0:
                #
                #     --max-stretch 1.000   116 trades   -$163   "does it work"
                #     --max-stretch 0.962   115 trades   -$193   "what prod does"
                #
                # One trade and $30, in the unflattering direction -- the extra
                # block took a winner. Small, but quote the right one: -$163
                # answers whether the idea holds, -$193 answers what this code
                # would have done. Being stricter than intended is the safe way
                # to be miscalibrated; it is not the same as being better.
                #
                # 1.0 was fixed BEFORE any result was seen. Do not tune it
                # against the sessions on disk, and do not cite -$54.
                # RECORD THE STRETCH ON EVERY ENTRY, GATE ON OR OFF.
                #
                # BRAINSTORM.md asks for exactly this: "log the stretch even
                # while the gate is off -- it costs nothing and makes every
                # future session measurable without rebuilding VWAP from the
                # tape". It was originally written inside the blocking branch,
                # which meant the only way to collect evidence about the
                # threshold was to already be enforcing one -- the measurement
                # was gated behind the decision it was supposed to inform.
                #
                # Safe to record unconditionally only because `vwap_stretch` is
                # in _OBSERVED_NOT_GATED: it cannot inflate the
                # `confirmation_required` count or appear in the reason string.
                # Anything else added here needs the same treatment.
                #
                # Note for whoever analyses these: this is engine_wiggle, the
                # tick-accumulated one, which is NOT the session_wiggle every
                # offline study uses. Measured 2026-09-15 over 72 snapshots on 9
                # sessions (scripts/measure_engine_wiggle.py, which drives the
                # real objects rather than a replica):
                #
                #     engine/session   median 0.962   mean 0.945
                #                      sd 0.102   range 0.710-1.302
                #
                # So they are the same scale to within ~4%, and the residual is
                # a day-to-day WOBBLE rather than a bias -- which is why these
                # recorded values should not be read to two decimals.
                wiggle = self._calculate_vwap_wiggle(symbol)
                stretch = None
                if wiggle is not None:
                    stretch = abs(current_price - vwap_value) / wiggle
                    indicators['vwap_stretch'] = round(stretch, 3)

                if max_stretch is not None:
                    # WARM-UP. A wiggle is only meaningful once it has seen
                    # enough of the session to be a fair measure of the day.
                    #
                    # The accumulator is in memory, so a restart at 13:00 ET
                    # leaves it measuring 13:00-onward while reporting itself as
                    # "today". A tally built from a stub of the session
                    # UNDERSTATES dispersion, which OVERSTATES the stretch, and
                    # the gate then refuses ordinary entries because it believes
                    # the day has been calm. Measured on the recorded tape: on
                    # 2026-09-10 this accumulator's wiggle was 0.69 against a
                    # full-session 1.24, and on 2026-09-11 at 15:00 ET it was
                    # 0.58 against 2.44 -- four times too small.
                    #
                    # CORRECTION, and a caution about what this guard is for.
                    # The 0.69/1.24 and 0.58/2.44 figures above compare a
                    # session_wiggle rebuilt from OUR STREAM LOG against one
                    # rebuilt from Tradier's minute bars. BOTH are minute-bar
                    # constructions; neither is this tick accumulator. They do
                    # not measure engine_wiggle, and they are not evidence about
                    # restarts. Enumerated afterwards, those nine sessions
                    # contain NO mid-session restarts at all -- the small stream
                    # files that look like them hold two prints each at 00:17 to
                    # 00:36 ET, hours before the open, and the real stream runs
                    # unbroken. Modelled against the replay, this guard blocks
                    # ZERO signals at 30 minutes on all nine.
                    #
                    # So the divergence those numbers show is real but UNDIAGNOSED,
                    # and this guard is not its fix. What the guard does defend is
                    # the mechanism above -- an in-memory tally genuinely does
                    # restart with the process -- which simply did not occur in the
                    # recorded sample. It is cheap insurance against a real hazard,
                    # not a repair of a measured one. Do not cite it as the latter.
                    #
                    # So: too young, no entry. Same most-restrictive rule as the
                    # EMA warm-up -- we do not trade on an indicator we cannot
                    # yet compute honestly, and a number built from five minutes
                    # of tape is not a measure of the day.
                    #
                    # 30 minutes matches the `entry_after_open_minutes: 30` both
                    # prod strategies already run, so on a clean session this is
                    # never the binding constraint -- it bites only after a
                    # restart. Elapsed time rather than accumulated volume on
                    # purpose: volume is what differs most between a quiet day
                    # and a busy one, so a volume threshold would make the
                    # gate's strictness track market activity, which is the very
                    # coupling this guard exists to remove.
                    #
                    # ENTRIES ONLY. An open position is unaffected: every exit
                    # path is reached before this function is ever called.
                    age = self._vwap_accumulator_age_minutes(symbol)
                    if age is None or age < _VWAP_WARMUP_MINUTES:
                        logger.debug(
                            f"{symbol}: VWAP tally covers only "
                            f"{'no' if age is None else format(age, '.1f')} minutes of "
                            f"session (need {_VWAP_WARMUP_MINUTES}) — entry blocked"
                        )
                        return None

                    if wiggle is None:
                        logger.debug(
                            f"{symbol}: VWAP dispersion not available yet — entry blocked"
                        )
                        return None
                    if stretch >= max_stretch:
                        # INFO, not DEBUG, so the gate's work is visible in the
                        # logs prod actually keeps (the engine runs at INFO; at
                        # DEBUG this line was never written, so a session showed
                        # no trace of how often the gate declined an entry).
                        #
                        # THROTTLED to one line a minute per strategy+symbol,
                        # because this branch runs on every 1s evaluation for as
                        # long as price stays stretched -- unthrottled, one
                        # stretched hour is ~3,600 lines per strategy. The count
                        # of blocks folded into each line keeps the volume
                        # measurable. Logging only; the return below is
                        # unconditional, so the throttle cannot change a decision.
                        key = (getattr(strategy, 'id', None), symbol)
                        slot = self._not_chasing_log.setdefault(key, [None, 0])
                        now = time.monotonic()
                        if slot[0] is None or now - slot[0] >= 60.0:
                            extra = (f"; {slot[1]} more blocks in the last minute"
                                     if slot[1] else "")
                            logger.info(
                                f"{symbol}: Not chasing — ${current_price:.2f} is "
                                f"{stretch:.2f} wiggles from VWAP ${vwap_value:.2f} "
                                f"(wiggle ${wiggle:.2f}, max {max_stretch}){extra}"
                            )
                            slot[0], slot[1] = now, 0
                        else:
                            slot[1] += 1
                        return None

        # 3. Check volume spike condition
        volume_spike_required = params.get('volume_spike_required', False)
        if volume_spike_required:
            min_volume_multiplier = params.get('min_volume_multiplier', 2.0)
            avg_volume = self._calculate_avg_volume(symbol, period=20)
            # The last COMPLETED minute, not this tick's trade size. Previously
            # this divided ONE trade's size by the mean of 20 recent trade
            # sizes — individual prints are wildly uneven, so 2.0x cleared
            # constantly and the gate confirmed nothing. It now compares a
            # minute against the last twenty minutes, which is what
            # `min_volume_multiplier` has always claimed to mean.
            #
            # CALIBRATION WARNING: the same NUMBER is far stricter under this
            # definition. Measured over 4 prod sessions, 2.0x fires ~4 times a
            # day where the old reading fired ~467 times. Strategies were moved
            # to 1.5x with this change; anything still carrying 2.0+ will be
            # close to silent. See TODO.md G3.
            bar_volume = self._last_bar_volume(symbol)

            if bar_volume is None or not avg_volume or avg_volume <= 0:
                # No completed bar yet, or fewer than 20 usable ones. Same
                # most-restrictive rule as the EMA and VWAP gates above.
                logger.debug(
                    f"{symbol}: volume baseline not available yet — entry blocked"
                )
                return None

            volume_ratio = bar_volume / avg_volume
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
            # Require at least 2 indicators to align. Counts GATING indicators
            # only: see _OBSERVED_NOT_GATED. Recording a new observation must
            # never make this gate easier to clear.
            gating = set(indicators) - _OBSERVED_NOT_GATED
            if len(gating) < 2:
                logger.debug(f"{symbol}: Confirmation required but only {len(gating)} indicators available")
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

        # Built outside the f-string below: a multi-line expression INSIDE an
        # f-string is PEP 701, which needs Python >= 3.12. On an older box that
        # is a SyntaxError at import, so the engine would not start at all
        # rather than degrade -- not worth risking for a line break.
        _conditions_met = ', '.join(
            k for k in indicators
            if k != 'direction' and k not in _OBSERVED_NOT_GATED
        )

        signal = Signal(
            signal_type='entry',
            action=action,
            symbol=symbol,
            confidence=confidence,
            reason=(
                f"Entry conditions met ({direction}): "
                f"{_conditions_met}"
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
            current_high: Position high-water mark since open (contract price)
            current_low: Position low-water mark since open (contract price)

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

        # The trail's ARMED state is computed before any exit branch because it
        # decides whether the flat take-profit still applies. Two rules govern
        # the upside and they are mutually exclusive above the activation
        # threshold — see the ordering note below.
        use_trailing_stop = params.get('trailing_stop', False)
        activation_pct = params.get('trailing_stop_activation', 15)
        trail_distance_pct = params.get('trailing_stop_distance', 10)

        # Armed off the HIGH-WATER MARK, not the current price. The previous
        # form tested live `pnl_pct >= activation_pct`, which meant the trail
        # switched itself back OFF during the very pullback it exists to catch:
        # with activation=15/distance=10 the stop level sits at
        # peak * 0.90, but a peak of +15% puts that level at +3.5% — below the
        # activation the branch re-checked — so nothing could fire until the
        # peak reached 1.15/0.90 = +27.8%. Arming latches on the peak instead,
        # so `trailing_stop_activation` means what its name says.
        #
        # `current_high`/`current_low` are position.peak_price/trough_price —
        # the held CONTRACT's extremes since open (strategy_executor.py:544),
        # never the underlying's daily range.
        # Tolerance so the threshold is not decided by binary representation:
        # (2.30 - 2.00) / 2.00 is 14.999999999999998, and a peak of exactly the
        # activation percentage must arm.
        _ARM_EPS = 1e-9

        trail_armed = False
        trailing_stop_price = None
        if use_trailing_stop:
            if position_side == 'long' and current_high:
                peak_pnl_pct = ((current_high - entry_price) / entry_price) * 100
                if peak_pnl_pct >= activation_pct - _ARM_EPS:
                    trail_armed = True
                    trailing_stop_price = current_high * (1 - trail_distance_pct / 100)
            elif position_side == 'short' and current_low:
                trough_pnl_pct = ((entry_price - current_low) / entry_price) * 100
                if trough_pnl_pct >= activation_pct - _ARM_EPS:
                    trail_armed = True
                    trailing_stop_price = current_low * (1 + trail_distance_pct / 100)

        if trail_armed:
            indicators['trailing_armed'] = True
            indicators['trailing_stop_price'] = trailing_stop_price

        # 1. Stop Loss check — evaluated first so the downside bound is never
        # gated behind anything else. Unchanged in behaviour; it cannot collide
        # with take profit (a position cannot be both above +TP and below -SL).
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

        # 2. Trailing Stop check
        if trail_armed:
            hit = (
                current_price <= trailing_stop_price if position_side == 'long'
                else current_price >= trailing_stop_price
            )
            if hit:
                comparator = '<=' if position_side == 'long' else '>='
                return Signal(
                    signal_type='exit',
                    action='sell' if position_side == 'long' else 'buy',
                    symbol=symbol,
                    confidence=1.0,
                    reason=(
                        f"Trailing stop hit: ${current_price:.2f} {comparator} "
                        f"${trailing_stop_price:.2f}"
                    ),
                    price=current_price,
                    indicators=indicators
                )

        # 3. Take Profit check — SUPPRESSED while the trail is armed.
        #
        # A flat target and a trail both claim the upside, and the flat target
        # always won: it fires the instant price touches +TP on the way UP,
        # when there has been no pullback for the trail to react to. Reordering
        # the branches does not change that (at the +TP tick the trail is not
        # hit, so it falls through to the target anyway) — the target has to
        # stand down for the trail to govern at all. Live 2026-09-02:
        # SPY260902C00760000 ran 3.27 -> 6.40 and the flat +25% took it at 4.09,
        # twice, for $750 of settled cash; a 10% trail exits once at ~5.76.
        # See TODO.md E1 / docs/live-test-results-2026-09-02.md F1.
        #
        # Below activation nothing changes, and unchecking `trailing_stop`
        # restores the previous behaviour exactly (picked up within ~30s by
        # db.refresh(strategy), stream_driven_worker.py:348).
        take_profit_pct = params.get('take_profit_pct') or params.get('take_profit_percentage')
        if take_profit_pct and not trail_armed and pnl_pct >= take_profit_pct:
            return Signal(
                signal_type='exit',
                action='sell' if position_side == 'long' else 'buy',
                symbol=symbol,
                confidence=1.0,
                reason=f"Take profit hit: {pnl_pct:.2f}% >= {take_profit_pct}%",
                price=current_price,
                indicators=indicators
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

    @staticmethod
    def _bar_volume(bar: dict) -> Optional[int]:
        """Volume traded during one completed bar, or None if unknowable.

        Derived from the exchange's CUMULATIVE volume counter rather than by
        summing the per-tick sizes we happen to sample. The caller sees roughly
        one trade a second out of the ~7 the stream delivers and the several
        hundred that actually print, so a summed figure would be a small random
        subsample — noisy enough that `min_volume_multiplier` would be gating on
        sampling noise, which is the very failure this change exists to remove.

        Returns None on a discontinuity: process start (no opening reading) or
        the counter resetting at the session boundary (last < open). None means
        "unknown", and the volume gate treats unknown as a block, never a pass.
        """
        cv_open, cv_last = bar.get("cv_open"), bar.get("cv_last")
        if cv_open is None or cv_last is None or cv_last < cv_open:
            return None
        return cv_last - cv_open

    def _update_history(
        self,
        symbol: str,
        price: float,
        volume: int,
        cum_volume: Optional[int] = None,
        ts: Optional[datetime] = None,
    ):
        """Fold one tick into the current 1-minute bar; flush completed bars.

        Called once per evaluation tick (~1/s). Only a COMPLETED minute reaches
        `price_history` / `volume_history`, so `ema_period: 9` is nine minutes
        and `_calculate_avg_volume(period=20)` is twenty minutes.

        `ts` is injectable so tests can drive bar boundaries without sleeping.

        NOTE: the VWAP accumulator is deliberately still fed on EVERY tick, not
        per bar. Measured 2026-09-10 against the tape, the tick-sampled VWAP sat
        within $0.117 (~1.5 bp) of a cumulative-volume-weighted VWAP and the
        `price < VWAP` gate agreed 98.6% of the time — sampling is uncorrelated
        with price, so the error averages out over thousands of samples. VWAP
        was never the broken one; only the EMA's timescale was.
        """
        now = ts or datetime.utcnow()
        minute = now.replace(second=0, microsecond=0)

        if symbol not in self.price_history:
            self.price_history[symbol] = deque(maxlen=self.max_history_length)
            self.volume_history[symbol] = deque(maxlen=self.max_history_length)

        bar = self._current_bar.get(symbol)
        if bar is None:
            self._current_bar[symbol] = {
                "minute": minute, "close": price,
                "cv_open": cum_volume, "cv_last": cum_volume,
            }
        elif minute != bar["minute"]:
            # Minute rolled over — the previous bar is final. Push it, then open
            # a new one seeded with this tick's cumulative reading so the next
            # bar measures from here rather than from the old bar's close.
            self.price_history[symbol].append(bar["close"])
            self.volume_history[symbol].append(self._bar_volume(bar))
            self._current_bar[symbol] = {
                "minute": minute, "close": price,
                "cv_open": bar.get("cv_last") if cum_volume is None else cum_volume,
                "cv_last": cum_volume,
            }
        else:
            bar["close"] = price
            if cum_volume is not None:
                if bar["cv_open"] is None:
                    bar["cv_open"] = cum_volume
                bar["cv_last"] = cum_volume

        # Intraday VWAP — cumulative from market open, resets each day
        today = date.today()
        acc = self._vwap_accumulators.get(symbol)
        if acc is None or acc["date"] != today:
            self._vwap_accumulators[symbol] = {
                "date": today, "sum_pv": 0.0, "sum_v": 0, "sum_p2v": 0.0,
                # How much of the session this tally actually covers. Taken
                # from the tick clock, not wall time, so a replay or a test
                # measures the same age the live engine would.
                "first_ts": None, "last_ts": None,
            }
            acc = self._vwap_accumulators[symbol]
        if volume > 0:
            acc["sum_pv"] += price * volume
            acc["sum_v"] += volume
            acc["sum_p2v"] += price * price * volume
            stamp = ts or datetime.utcnow()
            if acc["first_ts"] is None:
                acc["first_ts"] = stamp
            acc["last_ts"] = stamp

    def _last_bar_volume(self, symbol: str) -> Optional[int]:
        """Volume of the most recently COMPLETED minute, or None.

        The volume gate compares this against the 20-bar average rather than
        the in-progress bar, which would otherwise read near-zero early in a
        minute and near-full at its end — biasing every entry toward :59.
        """
        vols = self.volume_history.get(symbol)
        if not vols:
            return None
        return vols[-1]

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

    def _calculate_vwap_wiggle(self, symbol: str) -> Optional[float]:
        """Volume-weighted standard deviation of price around today's VWAP.

        The usual VWAP-band half-width: how far price has typically sat from
        VWAP so far today. It grows with the square root of time since the open
        (median $0.41 at 10:00 ET, $0.62 at 10:30, $0.93 at 12:00, $1.05 at
        15:00), which is the entire point -- a fixed-DOLLAR distance from VWAP
        is strict in the morning and meaningless in the afternoon. Expressing
        the distance in these units makes one threshold mean the same thing all
        day. See TODO.md G4b.

        Returns None when it cannot be computed, and the caller treats that as a
        block (most-restrictive-bound, same rule as the EMA and VWAP above).

        NOTE: like VWAP itself this accumulates in memory from the first tick
        the worker sees, so after a mid-session restart it covers only the time
        since the restart. A short window understates the wiggle, which
        OVER-states the stretch and over-blocks -- conservative, but wrong. It
        is the same gap as VWAP's and belongs with G3 warm-up seeding.
        """
        acc = self._vwap_accumulators.get(symbol)
        if acc is None or acc["sum_v"] == 0:
            return None
        # .get: an accumulator built before this field existed (hot reload
        # mid-session) has no sum_p2v. Block rather than report a wrong wiggle.
        sum_p2v = acc.get("sum_p2v")
        if sum_p2v is None:
            return None
        vwap = acc["sum_pv"] / acc["sum_v"]
        # E[p^2] - E[p]^2. Checked for float cancellation at SPY-sized prices
        # (760^2 = 577,600 against a variance near 0.9): relative error 4e-9
        # over a full 23,400-tick session, so the shortcut is safe here.
        variance = sum_p2v / acc["sum_v"] - vwap * vwap
        if variance <= 0:
            return None  # a single price so far, or float noise at the open
        return variance ** 0.5

    def _vwap_accumulator_age_minutes(self, symbol: str) -> Optional[float]:
        """How many minutes of the session this VWAP tally actually covers.

        NOT "minutes since the open" -- minutes since the FIRST TICK THIS
        PROCESS SAW. The accumulator lives in memory, so after a mid-session
        restart it covers only the time since the restart, and that is exactly
        what this has to report. Returns None when nothing has accumulated.
        """
        acc = self._vwap_accumulators.get(symbol)
        if acc is None:
            return None
        first, last = acc.get("first_ts"), acc.get("last_ts")
        if first is None or last is None:
            return None
        return (last - first).total_seconds() / 60.0

    def _calculate_avg_volume(self, symbol: str, period: int = 20) -> Optional[float]:
        """Average volume over the last `period` COMPLETED bars (minutes).

        Walks backward skipping bars whose volume is unknown (see _bar_volume)
        rather than refusing outright, so a single discontinuity — a restart, a
        session-boundary counter reset — costs one bar instead of blacking out
        the gate for the next twenty minutes. Returns None until `period` usable
        bars exist; the caller treats None as a block.
        """
        if symbol not in self.volume_history:
            return None

        usable = [v for v in reversed(self.volume_history[symbol]) if v is not None]
        if len(usable) < period:
            return None

        return sum(usable[:period]) / period

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

"""
Pydantic schemas for request/response validation.
"""
from datetime import date, datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import computed_field, BaseModel, EmailStr, Field, field_validator

from notifications.discord import is_valid_discord_webhook


# ===== Auth Schemas =====

class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Data extracted from JWT token."""
    email: Optional[str] = None


class LoginRequest(BaseModel):
    """Login request body."""
    email: EmailStr
    password: str


# ===== User Schemas =====

_HHMM_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class DiscordPrefs(BaseModel):
    """Per-user Discord notification settings, stored under
    `User.notification_preferences['discord']`."""
    enabled: bool = False
    webhook_url: Optional[str] = None
    notify_open: bool = True
    notify_close: bool = True
    # Risk alerts: a strategy that is still Active but has silently stopped
    # opening positions. Defaults on — the whole point is that this failure has
    # no other symptom, so it must not be opt-in.
    notify_risk: bool = True

    @field_validator("webhook_url")
    @classmethod
    def _check_webhook(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, ""):
            return None
        if not is_valid_discord_webhook(v):
            raise ValueError("webhook_url must be a Discord webhook URL")
        return v


class EmailReportsPrefs(BaseModel):
    """Per-user email report settings, stored under
    `User.notification_preferences['email_reports']`. Reports are sent to
    `User.email`; there's no separate destination address."""
    enabled: bool = False
    daily: bool = True
    weekly: bool = True
    monthly: bool = True
    quarterly: bool = True
    yearly: bool = True


_VALID_ROLES = {"user", "admin", "viewer", "auditor", "strategy_author"}


class UserBase(BaseModel):
    """Base user schema with common fields."""
    email: EmailStr
    name: str
    role: str = "user"
    risk_tolerance: str = "medium"
    account_size_usd: float = 0.0
    # PERCENT, not a fraction: risk_manager.py:71 divides this by 100, so 2.0
    # means 2%. The old 0.02 default gave a new user 0.02%, which sizes every
    # options trade to zero contracts.
    max_trade_percentage: float = 2.0
    daily_loss_limit_pct: float = Field(5.0, ge=0.5, le=20.0)
    timezone: str = "UTC"
    trading_window_enabled: bool = False
    trading_window_start: str = Field("09:45", pattern=_HHMM_PATTERN)
    trading_window_end: str = Field("15:45", pattern=_HHMM_PATTERN)
    notification_preferences: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class UserCreate(UserBase):
    """Schema for creating a new user."""
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    """Schema for updating user info."""
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    risk_tolerance: Optional[str] = None
    account_size_usd: Optional[float] = None
    max_trade_percentage: Optional[float] = None
    daily_loss_limit_pct: Optional[float] = Field(None, ge=0.5, le=20.0)
    timezone: Optional[str] = None
    trading_window_enabled: Optional[bool] = None
    trading_window_start: Optional[str] = Field(None, pattern=_HHMM_PATTERN)
    trading_window_end: Optional[str] = Field(None, pattern=_HHMM_PATTERN)
    notification_preferences: Optional[Dict[str, Any]] = None
    # Password change requires `current_password` to authorize the swap.
    current_password: Optional[str] = None
    new_password: Optional[str] = Field(None, min_length=8)

    @field_validator("notification_preferences")
    @classmethod
    def _validate_prefs(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if v is None:
            return v
        if "discord" in v and v["discord"] is not None:
            DiscordPrefs.model_validate(v["discord"])
        if "email_reports" in v and v["email_reports"] is not None:
            EmailReportsPrefs.model_validate(v["email_reports"])
        return v


class UserResponse(UserBase):
    """User response schema."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Read-only here on purpose: the halt is set through its own endpoints, not
    # the generic PATCH /auth/me field loop. Deliberately absent from
    # UserUpdate so a stray payload key can never stop or resume trading.
    trading_halted_on: Optional[date] = None
    trading_halt_mode: Optional[str] = None

    class Config:
        from_attributes = True


class LoginResponse(Token):
    """What POST /auth/login returns.

    The token alone is not enough for the client. Every role gate in the UI —
    the admin-only Users nav row, `adminGuard`, the "Done for the day" control —
    reads `role` off the stored user, and the only other source of it is
    GET /auth/me. Returning `Token` here meant the frontend stored the string
    "undefined" as its current user and fell back to role 'user' for the whole
    session, hiding admin surfaces from actual admins.

    No wider exposure than before: this is the same UserResponse that
    GET /auth/me already hands the same caller holding the same token.
    """
    user: UserResponse


class TradingHaltRequest(BaseModel):
    """Body for POST /auth/me/trading-halt — "done trading for today".

    `mode` decides only what happens to positions that are already open; both
    modes stop new entries for the rest of the market day.
    """
    mode: Literal["ride", "flatten"] = "ride"


class TradingHaltResponse(BaseModel):
    """Current halt state, returned by both the set and the clear endpoint so
    the caller never has to re-fetch to render the result."""
    trading_halted: bool
    trading_halt_mode: Optional[str] = None
    trading_halted_on: Optional[date] = None
    message: str


class DiscordTestRequest(BaseModel):
    """Body for the Discord test-message endpoint."""
    webhook_url: str


# ===== Strategy Schemas =====

def _validate_time_exit_params(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Reject a time-of-day exit weaker than the engine's hard floor.

    `exit_before_close_minutes` counts BACKWARDS from the bell, so a SMALLER
    number means a LATER exit. The engine clamps anything below the floor up to
    it (signal_generator.forced_exit_time_et), so accepting e.g. 5 here would
    store a value the UI displays and the engine ignores. 0 — the old form
    default — meant "never exit", which is how 0DTE contracts ended up carried
    overnight. Larger values are fine: they exit earlier, which is stricter.

    Validated here as well as enforced in the engine on purpose: the engine
    floor is the safety boundary, this is the honesty boundary — what you see
    stored is what actually runs.
    """
    if not isinstance(params, dict) or 'exit_before_close_minutes' not in params:
        return params

    from engine.signal_generator import FORCED_EOD_EXIT_FLOOR_MINUTES

    raw = params['exit_before_close_minutes']
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"exit_before_close_minutes must be a whole number of minutes, got {raw!r}"
        )

    if minutes < FORCED_EOD_EXIT_FLOOR_MINUTES:
        raise ValueError(
            f"exit_before_close_minutes must be at least "
            f"{FORCED_EOD_EXIT_FLOOR_MINUTES} (got {minutes}). This engine only "
            f"holds 0DTE contracts; anything still open at the bell expires "
            f"worthless or is auto-exercised into stock a cash account cannot "
            f"settle. Use a LARGER number to exit earlier."
        )
    return params


def _validate_vwap_max_stretch(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Reject a `vwap_max_stretch` the engine would refuse at run time.

    The value is a DISTANCE FROM VWAP measured in "wiggles" -- multiples of the
    session's own volume-weighted standard deviation of price around VWAP -- above
    which no new entry opens (engine.signal_generator, the don't-chase gate).
    Blank/absent means no distance gate, which is the shipped default.

    The engine already refuses a value it cannot read (`_coerce_max_stretch`
    blocks every entry and logs an error). This exists so the refusal happens at
    the form instead of at 09:31 tomorrow: a stored value the engine will only
    ever reject is a strategy that silently stops trading.

    Rejected, and why each is not merely unusual:
      - unparseable, or a bool -- `true` would otherwise coerce to 1.0 and look
        deliberate
      - <= 0 -- every distance is >= 0, so the gate would block every entry for
        the life of the strategy
      - > 10 -- reachable only in a market unlike any on record; ~2 wiggles is
        already the far tail (see TODO.md G4b), so this is a fat-finger guard,
        not a claim about where the useful range ends

    NOT rejected: anything in (0, 10]. 1.0 is the measured starting point, but the
    threshold is NOT calibrated -- the evidence supports the effect, not the exact
    cut -- so this deliberately does not force one value.
    """
    if not isinstance(params, dict) or params.get('vwap_max_stretch') in (None, ""):
        return params

    raw = params['vwap_max_stretch']
    if isinstance(raw, bool):
        raise ValueError("vwap_max_stretch must be a number of wiggles, not a boolean")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"vwap_max_stretch must be a number of wiggles (got {raw!r})"
        )
    if value != value or value <= 0:
        raise ValueError(
            f"vwap_max_stretch must be greater than 0 (got {value}); "
            f"0 or less would block every entry"
        )
    if value > 10:
        raise ValueError(
            f"vwap_max_stretch of {value} wiggles is implausibly far from VWAP "
            f"(about 2 is already the far tail) — leave it blank to disable the gate"
        )
    params['vwap_max_stretch'] = value
    return params


def _validate_entry_before_et(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Reject an `entry_before_et` the engine would ignore or that can never fire.

    The wall is an absolute ET "HH:MM" after which no NEW entry opens (see
    engine.signal_generator.entry_cutoff_time_et). Three ways to get it wrong,
    all of them silent without this:

    1. Unparseable — `_parse_hhmm` returns None on anything it does not like, and
       the engine then applies NO wall at all. A typo would quietly disable the
       gate the user thinks they switched on, which is the worst failure mode a
       safety gate has.
    2. Outside 09:30-16:00 — meaningless, and a value before the open would block
       every entry forever.
    3. At or before the strategy's own earliest entry
       (market_open + entry_after_open_minutes). That composes to an empty entry
       window: the strategy would never take a trade again and nothing would say
       why. Most-restrictive-bound is correct, a bound that is restrictive to the
       point of never trading is a configuration error.

    Same honesty boundary as _validate_time_exit_params: the engine is the safety
    boundary, this makes what is STORED match what actually runs.
    """
    if not isinstance(params, dict) or params.get('entry_before_et') in (None, ""):
        return params

    from engine.signal_generator import _parse_hhmm

    raw = params['entry_before_et']
    parsed = _parse_hhmm(raw)
    if parsed is None:
        raise ValueError(
            f"entry_before_et must be a 24-hour ET time as \"HH:MM\" (e.g. "
            f"\"11:30\"), got {raw!r}. The engine silently applies no cutoff at "
            f"all when it cannot parse this, so a typo would disable the gate."
        )

    minutes = parsed[0] * 60 + parsed[1]
    if not (9 * 60 + 30 <= minutes <= 16 * 60):
        raise ValueError(
            f"entry_before_et must fall inside market hours 09:30-16:00 ET, got "
            f"{raw!r}."
        )

    after_open = params.get('entry_after_open_minutes') or 0
    try:
        earliest = 9 * 60 + 30 + int(after_open)
    except (TypeError, ValueError):
        earliest = 9 * 60 + 30
    if minutes <= earliest:
        h, m = divmod(earliest, 60)
        raise ValueError(
            f"entry_before_et {raw!r} is at or before this strategy's earliest "
            f"entry of {h:02d}:{m:02d} ET (market open + "
            f"entry_after_open_minutes={after_open}), which leaves no window in "
            f"which it could ever enter. Use a LATER cutoff or a smaller "
            f"entry_after_open_minutes."
        )
    return params


def _validate_direction(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Reject a `direction` the engine would silently reinterpret.

    resolve_direction() falls back to 'call' on anything it does not recognise,
    which is the right runtime behaviour — an unreadable param must not stop a
    strategy dead. But storing 'calls' or 'bullish' and then trading calls by
    accident is exactly the see-one-thing/run-another gap the EOD-floor
    validator above exists to close. Absent is fine and means 'call'.
    """
    if not isinstance(params, dict) or 'direction' not in params:
        return params

    from engine.signal_generator import VALID_DIRECTIONS

    raw = params['direction']
    if not isinstance(raw, str) or raw.strip().lower() not in VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)} (got {raw!r}). "
            f"It selects which side of the option chain to buy. Both sides are "
            f"opened with buy_to_open and closed with sell_to_close — 'put' "
            f"means buying puts, not selling calls."
        )
    params['direction'] = raw.strip().lower()
    return params


class EntryBlockStatus(BaseModel):
    """Why the engine would refuse a new entry for this strategy right now.

    Computed per-request by `RiskManager.get_entry_block_status`; it is not a
    column. Exists so the strategies page can say "Active but blocked" instead
    of showing a healthy-looking Active chip on a strategy that has silently
    stopped trading.
    """
    blocked: bool
    code: Optional[str] = None
    reason: Optional[str] = None


class StrategyBase(BaseModel):
    """Base strategy schema."""
    name: str
    strategy_type: Optional[str] = None
    params_json: Dict[str, Any]
    instruments: List[str] = []
    timeframe: str = "1d"
    max_positions: int = 5
    stop_loss_percentage: Optional[float] = None
    take_profit_percentage: Optional[float] = None
    is_paper_trading: bool = True


class StrategyCreate(StrategyBase):
    """Schema for creating a strategy."""

    # Deliberately on Create, NOT on StrategyBase: StrategyResponse inherits
    # Base, and a strategy already stored with a sub-floor value must stay
    # READABLE (so the UI can load it and heal it on save) even though it is
    # no longer WRITABLE.
    @field_validator("params_json")
    @classmethod
    def _check_time_exit(cls, v):
        return _validate_vwap_max_stretch(
            _validate_entry_before_et(_validate_direction(_validate_time_exit_params(v))))


class StrategyUpdate(BaseModel):
    """Schema for updating a strategy."""
    name: Optional[str] = None
    strategy_type: Optional[str] = None
    params_json: Optional[Dict[str, Any]] = None
    instruments: Optional[List[str]] = None
    timeframe: Optional[str] = None
    max_positions: Optional[int] = None
    stop_loss_percentage: Optional[float] = None
    take_profit_percentage: Optional[float] = None
    is_active: Optional[bool] = None
    is_paper_trading: Optional[bool] = None

    @field_validator("params_json")
    @classmethod
    def _check_time_exit(cls, v):
        return _validate_vwap_max_stretch(
            _validate_entry_before_et(_validate_direction(_validate_time_exit_params(v))))


class StrategyResponse(StrategyBase):
    """Strategy response schema."""
    id: int
    user_id: int
    is_active: bool
    backtest_results: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Attached by the router, absent on writes. `None` means "not evaluated"
    # (e.g. the create/update responses), which the UI renders the same as
    # "not blocked" — a badge that is merely unknown must never look alarming.
    entry_block: Optional[EntryBlockStatus] = None

    class Config:
        from_attributes = True


# ===== Position Schemas =====

class PositionBase(BaseModel):
    """Base position schema."""
    symbol: str
    qty: int
    avg_entry_price: float


class PositionCreate(PositionBase):
    """Schema for creating a position."""
    strategy_id: Optional[int] = None


class PositionUpdate(BaseModel):
    """Schema for updating a position."""
    qty: Optional[int] = None
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None


class PositionResponse(PositionBase):
    """Position response schema."""
    id: int
    user_id: int
    strategy_id: Optional[int] = None
    option_symbol: Optional[str] = None
    current_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    opened_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ===== Trade Schemas =====

class TradeBase(BaseModel):
    """Base trade schema."""
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: str = "market"
    qty: int
    price: float


class TradeCreate(TradeBase):
    """Schema for creating a trade."""
    filled_qty: Optional[int] = None
    commission: float = 0.0
    fees: float = 0.0
    strategy_id: Optional[int] = None
    position_id: Optional[int] = None
    notes: Optional[Dict[str, Any]] = None


class TradeResponse(TradeBase):
    """Trade response schema."""
    id: int
    user_id: int
    filled_qty: Optional[int] = None
    exit_price: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    commission: float
    fees: float = 0.0
    pnl: Optional[float] = None
    timestamp: datetime
    strategy_id: Optional[int] = None
    position_id: Optional[int] = None
    status: str
    notes: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ===== Performance Metrics Schemas =====

class PerformanceMetricsResponse(BaseModel):
    """Performance metrics response.

    The gross/avg/largest/consecutive fields below were already being COMPUTED and
    STORED by `calculate_performance_metrics` — they were simply never exposed, so
    the UI could not show them. Adding them here needs no migration; the columns
    exist on `PerformanceMetrics`. (2026-09-02)
    """
    id: int
    strategy_id: int
    period: str
    date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_commission: float = 0.0
    total_fees: float = 0.0
    win_rate: Optional[float] = None
    profit_factor: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    largest_win: Optional[float] = None
    largest_loss: Optional[float] = None
    consecutive_wins: Optional[int] = None
    consecutive_losses: Optional[int] = None

    @computed_field
    @property
    def expectancy(self) -> Optional[float]:
        """Expected P&L per trade: (win% x avgWin) + (loss% x avgLoss).

        `avg_loss` is stored NEGATIVE, so this is a sum, not a difference. Derived
        rather than stored so it needs no column and cannot drift from its inputs.

        The single most useful one-line read on whether an edge exists: positive
        means the average trade makes money, regardless of win rate. A 30%-win
        strategy with large winners can beat a 70%-win strategy with large losers.
        """
        if self.win_rate is None or self.avg_win is None or self.avg_loss is None:
            return None
        loss_rate = 1.0 - self.win_rate
        return round(self.win_rate * self.avg_win + loss_rate * self.avg_loss, 2)

    @computed_field
    @property
    def payoff_ratio(self) -> Optional[float]:
        """avgWin / |avgLoss| — how much bigger the average winner is.

        Read WITH win_rate, never alone: 0.5 is fine at a 70% win rate and ruinous
        at 30%. Expectancy above folds both into one number.
        """
        if not self.avg_win or not self.avg_loss:
            return None
        return round(self.avg_win / abs(self.avg_loss), 4)

    class Config:
        from_attributes = True


# ===== Risk Event Schemas =====

class RiskEventCreate(BaseModel):
    """Schema for creating a risk event."""
    event_type: str
    severity: str
    action_taken: Optional[str] = None
    strategy_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None


class RiskEventResponse(BaseModel):
    """Risk event response."""
    id: int
    user_id: int
    event_type: str
    severity: str
    action_taken: Optional[str] = None
    strategy_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime

    class Config:
        from_attributes = True

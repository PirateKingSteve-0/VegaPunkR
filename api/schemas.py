"""
Pydantic schemas for request/response validation.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_validator

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
    max_trade_percentage: float = 0.02
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

    class Config:
        from_attributes = True


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
        return _validate_direction(_validate_time_exit_params(v))


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
        return _validate_direction(_validate_time_exit_params(v))


class StrategyResponse(StrategyBase):
    """Strategy response schema."""
    id: int
    user_id: int
    is_active: bool
    backtest_results: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

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
    """Performance metrics response."""
    id: int
    strategy_id: int
    period: str
    date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    total_commission: float = 0.0
    total_fees: float = 0.0
    win_rate: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None

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

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
    pass


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

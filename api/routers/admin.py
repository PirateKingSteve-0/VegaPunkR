"""Admin / auditor endpoints.

Read-only-across-users endpoints for operational oversight (admin and
auditor roles) plus admin-only user-management endpoints.

Per TODO #8 the project decided on **observe-only** admin scope —
admins can see and manage user accounts but cannot act on someone
else's behalf (no order placement, no strategy CRUD as another user).
That keeps the liability surface bounded and matches what the existing
`/strategies`, `/positions`, etc. routes already enforce by filtering
on `current_user.id`. This router does NOT mirror writeable endpoints
with `?user_id=` overrides — adding those would be the act-as path
the project explicitly rejected.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import (
    VALID_ROLES,
    get_current_active_admin,
    get_current_active_admin_or_auditor,
)
from database import get_db
from models import Position, Strategy, Trade, User
from schemas import (
    PerformanceMetricsResponse,  # noqa: F401 - kept for future per-user metrics endpoint
    PositionResponse,
    StrategyResponse,
    TradeResponse,
    UserResponse,
)


router = APIRouter(prefix="/admin", tags=["Admin"])


# ===== Request/response models specific to admin views =====


class AdminUserSummary(BaseModel):
    """Compact row shown on the admin Users page. Pulls cheap aggregates
    so the table can render N users without N round trips per row."""
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    active_strategies: int
    open_positions: int
    today_pnl: float
    last_trade_at: Optional[datetime] = None


class AdminRoleUpdate(BaseModel):
    role: str = Field(..., description="One of: " + ", ".join(sorted(VALID_ROLES)))


# ===== Helpers =====


def _get_user_or_404(user_id: int, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _today_pnl_for(user_id: int, db: Session) -> float:
    """Realized PnL today (UTC midnight) plus unrealized on open positions.

    Mirrors `RiskManager.get_account_risk_status` so the admin Users page
    shows the same number an admin would see on the user's own session
    tile."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    realized = db.query(func.sum(Trade.pnl)).filter(
        Trade.user_id == user_id,
        Trade.timestamp >= today_start,
        Trade.status == 'executed',
        Trade.pnl.isnot(None),
    ).scalar() or 0.0
    unrealized = db.query(func.sum(Position.unrealized_pnl)).filter(
        Position.user_id == user_id,
        Position.qty > 0,
    ).scalar() or 0.0
    return float(realized) + float(unrealized)


# ===== Endpoints =====


@router.get("/users", response_model=List[AdminUserSummary])
def list_users(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    """Compact list of every user with cheap per-row aggregates for the
    admin Users page."""
    users = db.query(User).order_by(User.id.asc()).all()

    summaries: List[AdminUserSummary] = []
    for u in users:
        active_strategies = db.query(func.count(Strategy.id)).filter(
            Strategy.user_id == u.id,
            Strategy.is_active == True,  # noqa: E712 - SQLAlchemy idiom
        ).scalar() or 0
        open_positions = db.query(func.count(Position.id)).filter(
            Position.user_id == u.id,
            Position.qty > 0,
        ).scalar() or 0
        last_trade_at = db.query(func.max(Trade.timestamp)).filter(
            Trade.user_id == u.id,
        ).scalar()
        summaries.append(AdminUserSummary(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role or "user",
            is_active=bool(u.is_active),
            last_login=u.last_login,
            active_strategies=int(active_strategies),
            open_positions=int(open_positions),
            today_pnl=_today_pnl_for(u.id, db),
            last_trade_at=last_trade_at,
        ))
    return summaries


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    """Full profile for one user."""
    return _get_user_or_404(user_id, db)


@router.get("/users/{user_id}/strategies", response_model=List[StrategyResponse])
def get_user_strategies(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    _get_user_or_404(user_id, db)
    return db.query(Strategy).filter(Strategy.user_id == user_id).all()


@router.get("/users/{user_id}/positions", response_model=List[PositionResponse])
def get_user_positions(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    _get_user_or_404(user_id, db)
    return db.query(Position).filter(Position.user_id == user_id).all()


@router.get("/users/{user_id}/trades", response_model=List[TradeResponse])
def get_user_trades(
    user_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    _get_user_or_404(user_id, db)
    limit = max(1, min(int(limit), 1000))
    return (
        db.query(Trade)
        .filter(Trade.user_id == user_id)
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )


@router.get("/users/{user_id}/dashboard")
def get_user_dashboard(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_active_admin_or_auditor),
):
    """Read-only dashboard payload for one user. Combines the same
    figures the user would see on their own overview page so the admin
    can spot-check without leaving the admin UI."""
    user = _get_user_or_404(user_id, db)

    today_pnl = _today_pnl_for(user.id, db)
    account_size = float(user.account_size_usd or 10000)
    daily_loss_limit_pct = float(user.daily_loss_limit_pct or 5.0)
    daily_loss_limit = account_size * (daily_loss_limit_pct / 100.0)
    loss_consumed = max(0.0, -today_pnl)
    pct_consumed = (loss_consumed / daily_loss_limit * 100.0) if daily_loss_limit > 0 else 0.0
    if pct_consumed >= 100.0:
        risk_status = "HALTED"
    elif pct_consumed >= 80.0:
        risk_status = "WARNING"
    else:
        risk_status = "OK"

    open_positions = db.query(Position).filter(
        Position.user_id == user.id,
        Position.qty > 0,
    ).count()
    active_strategies = db.query(Strategy).filter(
        Strategy.user_id == user.id,
        Strategy.is_active == True,  # noqa: E712
    ).count()

    last_trade = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.timestamp.desc())
        .first()
    )

    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "last_login": user.last_login,
            "selected_environment": user.selected_environment,
            "selected_trading_mode": user.selected_trading_mode,
        },
        "account": {
            "account_size_usd": account_size,
            "daily_loss_limit_pct": daily_loss_limit_pct,
        },
        "session_status": {
            "today_pnl": today_pnl,
            "daily_loss_limit": daily_loss_limit,
            "daily_loss_remaining": max(0.0, daily_loss_limit - loss_consumed),
            "pct_consumed": pct_consumed,
            "risk_status": risk_status,
            "entries_halted": risk_status == "HALTED",
        },
        "counts": {
            "active_strategies": active_strategies,
            "open_positions": open_positions,
        },
        "last_trade_at": last_trade.timestamp if last_trade else None,
    }


@router.patch("/users/{user_id}/role", response_model=UserResponse)
def set_user_role(
    user_id: int,
    body: AdminRoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_active_admin),
):
    """Assign a role to a user. Admin-only — auditors cannot change
    roles. Admins cannot demote themselves to a non-admin role to avoid
    accidentally locking out the only admin."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {sorted(VALID_ROLES)}",
        )

    target = _get_user_or_404(user_id, db)

    if target.id == admin.id and body.role != "admin":
        # Self-demotion guard. If you really want to demote yourself,
        # have another admin do it. Prevents lockout when there's only
        # one admin in the system.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot demote themselves; ask another admin.",
        )

    target.role = body.role
    db.commit()
    db.refresh(target)
    return target

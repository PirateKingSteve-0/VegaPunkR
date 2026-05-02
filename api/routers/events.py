"""
System event log endpoint.
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import SystemEvent, User

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("")
def get_events(
    page: int = Query(1, ge=1),
    limit: int = Query(50, le=200),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    strategy_id: Optional[int] = Query(None),
    start: Optional[str] = Query(None, description="yyyy-mm-dd"),
    end: Optional[str] = Query(None, description="yyyy-mm-dd"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Paginated system event log for the current user.
    Returns all event types by default; narrow with query params.
    """
    q = db.query(SystemEvent).filter(SystemEvent.user_id == current_user.id)

    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if severity:
        q = q.filter(SystemEvent.severity == severity)
    if symbol:
        q = q.filter(SystemEvent.symbol.ilike(f"%{symbol}%"))
    if strategy_id:
        q = q.filter(SystemEvent.strategy_id == strategy_id)
    if start:
        q = q.filter(SystemEvent.created_at >= datetime.fromisoformat(start))
    if end:
        q = q.filter(SystemEvent.created_at <= datetime.fromisoformat(f"{end}T23:59:59"))

    total = q.count()
    events = (
        q.order_by(SystemEvent.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "severity": e.severity,
                "title": e.title,
                "detail": e.detail,
                "symbol": e.symbol,
                "strategy_id": e.strategy_id,
                "event_data": e.event_data,
                "created_at": (
                    e.created_at.replace(tzinfo=timezone.utc).isoformat()
                    if e.created_at else None
                ),
            }
            for e in events
        ],
    }

"""
Thin helper for writing SystemEvent rows.

Call log_event() after a successful db.commit() so the session is clean.
All exceptions are swallowed — logging must never crash the caller.
"""
import logging
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from models import SystemEvent

logger = logging.getLogger(__name__)


def log_event(
    db: Session,
    user_id: int,
    event_type: str,
    title: str,
    detail: Optional[str] = None,
    symbol: Optional[str] = None,
    strategy_id: Optional[int] = None,
    severity: str = "info",
    event_data: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        event = SystemEvent(
            user_id=user_id,
            event_type=event_type,
            severity=severity,
            title=title,
            detail=detail,
            symbol=symbol,
            strategy_id=strategy_id,
            event_data=event_data or {},
        )
        db.add(event)
        db.commit()
    except Exception as e:
        logger.warning(f"event_logger: failed to write {event_type!r}: {e}")
        try:
            db.rollback()
        except Exception:
            pass

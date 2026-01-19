"""
Risk event management endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from models import RiskEvent, User, Strategy
from schemas import RiskEventCreate, RiskEventResponse
from auth import get_current_user

router = APIRouter(prefix="/risk-events", tags=["Risk Events"])


@router.get("", response_model=List[RiskEventResponse])
def get_risk_events(
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    severity: Optional[str] = Query(None, description="Filter by severity (info/warning/critical)"),
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    start_date: Optional[datetime] = Query(None, description="Filter events after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter events before this date"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of events to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get risk events for the current user.

    Optional filters:
    - event_type: Type of risk event (e.g., 'max_drawdown', 'position_limit', 'daily_loss_limit')
    - severity: Severity level ('info', 'warning', 'critical')
    - strategy_id: Filter by specific strategy
    - start_date: Only events after this date
    - end_date: Only events before this date
    - limit: Maximum number of events (default 100, max 1000)
    """
    query = db.query(RiskEvent).filter(RiskEvent.user_id == current_user.id)

    if event_type:
        query = query.filter(RiskEvent.event_type == event_type.lower())

    if severity:
        valid_severities = ['info', 'warning', 'critical']
        if severity.lower() not in valid_severities:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Severity must be one of: {', '.join(valid_severities)}"
            )
        query = query.filter(RiskEvent.severity == severity.lower())

    if strategy_id:
        # Verify the strategy belongs to the user
        strategy = db.query(Strategy).filter(
            Strategy.id == strategy_id,
            Strategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )

        query = query.filter(RiskEvent.strategy_id == strategy_id)

    if start_date:
        query = query.filter(RiskEvent.timestamp >= start_date)

    if end_date:
        query = query.filter(RiskEvent.timestamp <= end_date)

    # Order by most recent first and limit results
    events = query.order_by(RiskEvent.timestamp.desc()).limit(limit).all()
    return events


@router.get("/{event_id}", response_model=RiskEventResponse)
def get_risk_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific risk event by ID.
    """
    event = db.query(RiskEvent).filter(
        RiskEvent.id == event_id,
        RiskEvent.user_id == current_user.id
    ).first()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk event not found"
        )

    return event


@router.post("", response_model=RiskEventResponse, status_code=status.HTTP_201_CREATED)
def create_risk_event(
    event_data: RiskEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Log a new risk event.

    This is typically called automatically by the risk management system when:
    - Position limits are breached
    - Daily loss limits are exceeded
    - Max drawdown is reached
    - Other risk thresholds are crossed
    """
    # Validate severity
    valid_severities = ['info', 'warning', 'critical']
    if event_data.severity.lower() not in valid_severities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Severity must be one of: {', '.join(valid_severities)}"
        )

    # Validate strategy exists if provided
    if event_data.strategy_id:
        strategy = db.query(Strategy).filter(
            Strategy.id == event_data.strategy_id,
            Strategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )

    db_event = RiskEvent(
        user_id=current_user.id,
        event_type=event_data.event_type.lower(),
        severity=event_data.severity.lower(),
        action_taken=event_data.action_taken,
        strategy_id=event_data.strategy_id,
        details=event_data.details
    )

    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    return db_event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_risk_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a risk event.

    This should only be used to remove erroneous events.
    Risk events are generally kept for audit trail purposes.
    """
    event = db.query(RiskEvent).filter(
        RiskEvent.id == event_id,
        RiskEvent.user_id == current_user.id
    ).first()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Risk event not found"
        )

    db.delete(event)
    db.commit()

    return None


@router.get("/summary/stats")
def get_risk_event_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get risk event statistics for a given time period.

    Returns:
    - Total events by severity
    - Events by type
    - Recent critical events
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    events = db.query(RiskEvent).filter(
        RiskEvent.user_id == current_user.id,
        RiskEvent.timestamp >= start_date
    ).all()

    if not events:
        return {
            "total_events": 0,
            "by_severity": {"info": 0, "warning": 0, "critical": 0},
            "by_type": {},
            "days_analyzed": days
        }

    # Count by severity
    by_severity = {
        "info": len([e for e in events if e.severity == 'info']),
        "warning": len([e for e in events if e.severity == 'warning']),
        "critical": len([e for e in events if e.severity == 'critical'])
    }

    # Count by type
    by_type = {}
    for event in events:
        event_type = event.event_type
        by_type[event_type] = by_type.get(event_type, 0) + 1

    # Get recent critical events
    critical_events = [
        {
            "id": e.id,
            "event_type": e.event_type,
            "action_taken": e.action_taken,
            "timestamp": e.timestamp,
            "details": e.details
        }
        for e in sorted(events, key=lambda x: x.timestamp, reverse=True)
        if e.severity == 'critical'
    ][:5]  # Last 5 critical events

    return {
        "total_events": len(events),
        "by_severity": by_severity,
        "by_type": by_type,
        "recent_critical_events": critical_events,
        "days_analyzed": days
    }


@router.get("/summary/alerts")
def get_active_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get active risk alerts (critical and warning events from the last 24 hours).

    This is used for dashboard notifications and alerts.
    """
    start_date = datetime.utcnow() - timedelta(hours=24)

    events = db.query(RiskEvent).filter(
        RiskEvent.user_id == current_user.id,
        RiskEvent.timestamp >= start_date,
        RiskEvent.severity.in_(['warning', 'critical'])
    ).order_by(RiskEvent.timestamp.desc()).all()

    alerts = []
    for event in events:
        alerts.append({
            "id": event.id,
            "severity": event.severity,
            "event_type": event.event_type,
            "action_taken": event.action_taken,
            "strategy_id": event.strategy_id,
            "timestamp": event.timestamp,
            "details": event.details
        })

    return {
        "total_alerts": len(alerts),
        "critical_count": len([a for a in alerts if a['severity'] == 'critical']),
        "warning_count": len([a for a in alerts if a['severity'] == 'warning']),
        "alerts": alerts
    }

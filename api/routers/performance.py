"""
Performance metrics endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import math

from database import get_db
from models import PerformanceMetrics, User, Strategy, Trade
from schemas import PerformanceMetricsResponse
from auth import get_current_user, require_can_write_own

router = APIRouter(prefix="/performance", tags=["Performance Metrics"])


@router.get("", response_model=List[PerformanceMetricsResponse])
def get_performance_metrics(
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    period: Optional[str] = Query(None, description="Filter by period (daily/weekly/monthly/all_time)"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get performance metrics.

    Optional filters:
    - strategy_id: Filter by specific strategy
    - period: Filter by time period ('daily', 'weekly', 'monthly', 'all_time')
    - limit: Maximum number of records (default 50, max 500)
    """
    # We need to join through Strategy to filter by user
    query = db.query(PerformanceMetrics).join(Strategy).filter(
        Strategy.user_id == current_user.id
    )

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

        query = query.filter(PerformanceMetrics.strategy_id == strategy_id)

    if period:
        valid_periods = ['daily', 'weekly', 'monthly', 'all_time']
        if period.lower() not in valid_periods:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Period must be one of: {', '.join(valid_periods)}"
            )
        query = query.filter(PerformanceMetrics.period == period.lower())

    # Order by most recent first and limit results
    metrics = query.order_by(PerformanceMetrics.date.desc()).limit(limit).all()
    return metrics


@router.get("/{metrics_id}", response_model=PerformanceMetricsResponse)
def get_performance_metric(
    metrics_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific performance metrics record by ID.
    """
    metric = db.query(PerformanceMetrics).join(Strategy).filter(
        PerformanceMetrics.id == metrics_id,
        Strategy.user_id == current_user.id
    ).first()

    if not metric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance metric not found"
        )

    return metric


@router.post("/calculate/{strategy_id}", response_model=PerformanceMetricsResponse, status_code=status.HTTP_201_CREATED)
def calculate_performance_metrics(
    strategy_id: int,
    period: str = Query(..., description="Period to calculate (daily/weekly/monthly/all_time)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Calculate and store performance metrics for a strategy.

    This endpoint:
    1. Fetches all closed trades for the strategy in the given period
    2. Calculates various performance metrics
    3. Stores the results in the database

    Period options: 'daily', 'weekly', 'monthly', 'all_time'
    """
    # Validate strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    # Validate period
    valid_periods = ['daily', 'weekly', 'monthly', 'all_time']
    if period.lower() not in valid_periods:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Period must be one of: {', '.join(valid_periods)}"
        )

    # Calculate date range based on period
    end_date = datetime.utcnow()
    if period == 'daily':
        start_date = end_date - timedelta(days=1)
    elif period == 'weekly':
        start_date = end_date - timedelta(weeks=1)
    elif period == 'monthly':
        start_date = end_date - timedelta(days=30)
    else:  # all_time
        start_date = datetime(2000, 1, 1)  # Arbitrarily old date

    # Fetch closed trades for this strategy in the period
    trades = db.query(Trade).filter(
        Trade.strategy_id == strategy_id,
        Trade.user_id == current_user.id,
        Trade.timestamp >= start_date,
        Trade.timestamp <= end_date,
        Trade.pnl.isnot(None)  # Only closed trades
    ).all()

    if not trades:
        # Create empty metrics if no trades
        metrics = PerformanceMetrics(
            strategy_id=strategy_id,
            period=period.lower(),
            date=end_date,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            total_pnl=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            total_commission=0.0,
            total_fees=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            sharpe_ratio=None,
            max_drawdown=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            largest_win=0.0,
            largest_loss=0.0,
            consecutive_wins=0,
            consecutive_losses=0
        )
        db.add(metrics)
        db.commit()
        db.refresh(metrics)
        return metrics

    # Calculate basic statistics
    total_trades = len(trades)
    winning_trades_list = [t for t in trades if t.pnl > 0]
    losing_trades_list = [t for t in trades if t.pnl < 0]

    winning_trades = len(winning_trades_list)
    losing_trades = len(losing_trades_list)

    total_pnl = sum(t.pnl for t in trades)
    gross_profit = sum(t.pnl for t in winning_trades_list)
    gross_loss = sum(t.pnl for t in losing_trades_list)
    total_commission = sum(t.commission or 0.0 for t in trades)
    total_fees = sum(t.fees or 0.0 for t in trades)

    # Calculate derived metrics
    win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss != 0 else 0.0

    avg_win = (gross_profit / winning_trades) if winning_trades > 0 else 0.0
    avg_loss = (gross_loss / losing_trades) if losing_trades > 0 else 0.0

    largest_win = max((t.pnl for t in winning_trades_list), default=0.0)
    largest_loss = min((t.pnl for t in losing_trades_list), default=0.0)

    # Calculate consecutive wins/losses
    consecutive_wins = 0
    consecutive_losses = 0
    current_streak_wins = 0
    current_streak_losses = 0

    sorted_trades = sorted(trades, key=lambda t: t.timestamp)
    for trade in sorted_trades:
        if trade.pnl > 0:
            current_streak_wins += 1
            current_streak_losses = 0
            consecutive_wins = max(consecutive_wins, current_streak_wins)
        else:
            current_streak_losses += 1
            current_streak_wins = 0
            consecutive_losses = max(consecutive_losses, current_streak_losses)

    # Calculate Sharpe Ratio (simplified)
    pnl_values = [t.pnl for t in trades]
    if len(pnl_values) > 1:
        mean_pnl = sum(pnl_values) / len(pnl_values)
        variance = sum((x - mean_pnl) ** 2 for x in pnl_values) / len(pnl_values)
        std_dev = math.sqrt(variance)
        sharpe_ratio = (mean_pnl / std_dev) if std_dev > 0 else 0.0
    else:
        sharpe_ratio = 0.0

    # Calculate Max Drawdown
    cumulative_pnl = 0
    peak = 0
    max_drawdown = 0

    for trade in sorted_trades:
        cumulative_pnl += trade.pnl
        if cumulative_pnl > peak:
            peak = cumulative_pnl
        drawdown = peak - cumulative_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # Create performance metrics record
    metrics = PerformanceMetrics(
        strategy_id=strategy_id,
        period=period.lower(),
        date=end_date,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        total_pnl=round(total_pnl, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        total_commission=round(total_commission, 2),
        total_fees=round(total_fees, 2),
        win_rate=round(win_rate, 4),
        profit_factor=round(profit_factor, 4),
        sharpe_ratio=round(sharpe_ratio, 4) if sharpe_ratio else None,
        max_drawdown=round(max_drawdown, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        largest_win=round(largest_win, 2),
        largest_loss=round(largest_loss, 2),
        consecutive_wins=consecutive_wins,
        consecutive_losses=consecutive_losses
    )

    db.add(metrics)
    db.commit()
    db.refresh(metrics)

    return metrics


@router.delete("/{metrics_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_performance_metric(
    metrics_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Delete a performance metrics record.
    """
    metric = db.query(PerformanceMetrics).join(Strategy).filter(
        PerformanceMetrics.id == metrics_id,
        Strategy.user_id == current_user.id
    ).first()

    if not metric:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Performance metric not found"
        )

    db.delete(metric)
    db.commit()

    return None


@router.get("/summary/{strategy_id}")
def get_strategy_performance_summary(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a comprehensive performance summary for a strategy.

    Returns the most recent metrics for all periods (daily, weekly, monthly, all_time).
    """
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

    # Get the most recent metrics for each period
    periods = ['daily', 'weekly', 'monthly', 'all_time']
    summary = {}

    for period in periods:
        metric = db.query(PerformanceMetrics).filter(
            PerformanceMetrics.strategy_id == strategy_id,
            PerformanceMetrics.period == period
        ).order_by(PerformanceMetrics.date.desc()).first()

        if metric:
            summary[period] = {
                "total_trades": metric.total_trades,
                "total_pnl": metric.total_pnl,
                "win_rate": metric.win_rate,
                "profit_factor": metric.profit_factor,
                "sharpe_ratio": metric.sharpe_ratio,
                "max_drawdown": metric.max_drawdown,
                "last_calculated": metric.date
            }
        else:
            summary[period] = None

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        "metrics": summary
    }

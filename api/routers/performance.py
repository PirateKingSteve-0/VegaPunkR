"""
Performance metrics endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta, timezone
import math

from database import get_db
from models import PerformanceMetrics, User, Strategy, Trade, Position
from utils.market_hours import market_day_start_utc
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


@router.get("/equity-curves")
def get_equity_curves(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Per-strategy lifetime realized-PnL equity curves for the current user.

    Each curve is the running sum of `Trade.pnl` over the strategy's closing
    trades, ordered by `exit_timestamp` ascending, starting from zero. Only
    closed trades (those with both `exit_timestamp` and `pnl` populated) are
    included; open positions don't contribute because their PnL is unrealized.

    Shape:
        [{strategy_id, name, points: [{t, cum_pnl, trade_pnl}, ...]}, ...]
    """
    strategies = db.query(Strategy).filter(
        Strategy.user_id == current_user.id
    ).order_by(Strategy.id.asc()).all()

    result = []
    for s in strategies:
        trades = db.query(Trade).filter(
            Trade.strategy_id == s.id,
            Trade.user_id == current_user.id,
            Trade.exit_timestamp.isnot(None),
            Trade.pnl.isnot(None),
        ).order_by(Trade.exit_timestamp.asc()).all()

        cum = 0.0
        points = []
        for t in trades:
            cum += t.pnl or 0.0
            points.append({
                "t": t.exit_timestamp.isoformat(),
                "cum_pnl": round(cum, 2),
                "trade_pnl": round(t.pnl or 0.0, 2),
            })

        result.append({
            "strategy_id": s.id,
            "name": s.name,
            "points": points,
        })

    return result


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """ISO-8601 with an explicit +00:00.

    `Trade.exit_timestamp` is stored naive-UTC, and a bare `.isoformat()` emits
    no offset. JavaScript parses an offset-less date-time as *local* time, so
    every timestamp reached the UI shifted by the viewer's UTC offset — seven
    hours in America/Los_Angeles. Invisible while the UI only used the date part;
    badly wrong the moment anything plots the time of day.
    """
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _parse_bound(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 bound from the UI into naive UTC for comparison.

    The column is naive-UTC, so an aware value must be converted and stripped
    rather than compared directly (Postgres and SQLAlchemy both refuse to
    compare aware and naive datetimes).
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ISO-8601 datetime: {value!r}",
        )
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _period_cutoff(period: str) -> Optional[datetime]:
    """Naive-UTC lower bound for a UI period. Returns None for ALL (no bound).

    DAY anchors to the Eastern trading day, not UTC midnight — UTC midnight lands at
    ~8 PM ET, which would roll "today" over mid-evening and drop the session's trades.
    """
    p = (period or "").upper()
    if p == "DAY":
        return market_day_start_utc()
    now = datetime.utcnow()
    days = {"WEEK": 7, "MONTH": 30, "YEAR": 365, "YEAR_3": 365 * 3, "YEAR_5": 365 * 5}
    if p in days:
        return now - timedelta(days=days[p])
    if p == "YTD":
        return datetime(now.year, 1, 1)
    return None  # ALL


@router.get("/closed-trades")
def get_closed_trades(
    period: str = Query("MONTH", description="DAY|WEEK|MONTH|YTD|YEAR|YEAR_3|YEAR_5|ALL"),
    start: Optional[str] = Query(None, description="ISO-8601 inclusive lower bound. Overrides `period`."),
    end: Optional[str] = Query(None, description="ISO-8601 exclusive upper bound."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Closed trades for the current user, computed from the engine's OWN fill records.

    Deliberately NOT sourced from Tradier's /gainloss, which is wrong in two ways:

    1. Its cost basis is corrupt when a contract is round-tripped repeatedly in one
       session — the lot matcher keeps pairing new sells against early buy lots that
       were already closed. On 2026-07-13 it reported -21,057 for a day that actually
       lost -1,851 (150 TSLA contracts: real cost 14,244, reported cost 34,908).
    2. It is paginated and the UI asked for limit=100 against 125 closed trades, so a
       busy day was silently truncated on top of being wrong.

    A Trade row pairs each exit with the entry that opened it, recorded at the moment it
    happened — so the pairing is correct by construction and needs no lot matching.
    """
    # Explicit bounds win. `period` stays for older callers and is resolved the
    # same way it always was; the UI now sends real dates so any range works,
    # not just the seven the enum happened to name.
    lower = _parse_bound(start) if start else _period_cutoff(period)
    upper = _parse_bound(end)
    if lower is not None and upper is not None and upper <= lower:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`end` must be after `start`.",
        )

    q = (
        db.query(Trade, Position)
        .outerjoin(Position, Trade.position_id == Position.id)
        .filter(
            Trade.user_id == current_user.id,
            Trade.side == 'sell',              # closing legs carry the round-trip P&L
            Trade.pnl.isnot(None),
            Trade.exit_timestamp.isnot(None),
        )
    )
    if lower is not None:
        q = q.filter(Trade.exit_timestamp >= lower)
    if upper is not None:
        q = q.filter(Trade.exit_timestamp < upper)

    rows: List[dict] = []
    for trade, position in q.order_by(Trade.exit_timestamp.desc()).all():
        occ = (position.option_symbol if position else None) or (trade.notes or {}).get('option_symbol')
        multiplier = 100 if occ else 1        # options are quoted per share, trade per 100
        qty = trade.filled_qty or trade.qty or 0
        cost = abs((trade.price or 0.0) * qty * multiplier)
        proceeds = abs((trade.exit_price or 0.0) * qty * multiplier)
        commission = trade.commission or 0.0
        fees = trade.fees or 0.0
        pnl = trade.pnl or 0.0
        opened_at = (position.opened_at if position and position.opened_at else trade.timestamp)

        rows.append({
            "close_date": _iso_utc(trade.exit_timestamp),
            "open_date": _iso_utc(opened_at or trade.exit_timestamp),
            "cost": round(cost, 2),
            "proceeds": round(proceeds, 2),
            "gain_loss": round(pnl, 2),
            "gain_loss_percent": round(pnl / cost * 100, 2) if cost > 0.01 else 0.0,
            "quantity": qty,
            "symbol": occ or trade.symbol,
            "term": 0,
            "commission": round(commission, 2),
            "fees": round(fees, 2),
            "net_pnl": round(pnl - commission - fees, 2),
        })

    return rows


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

    # Calculate Sharpe Ratio (per-trade percentage returns): return% = pnl / cost * 100.
    #
    # Trade has NO `entry_price` and NO `asset_class` columns. The entry price lives in
    # `price` (carried on the closing row alongside `exit_price`), and whether a trade is
    # an option has to come from the OCC symbol — `Trade.symbol` holds the UNDERLYING
    # ("TSLA"), so it can't tell us. Options are quoted per share but trade in 100-share
    # contracts, so the cost basis needs that multiplier or every return is 100x too big.
    position_ids = {t.position_id for t in trades if t.position_id}
    positions = (
        {p.id: p for p in db.query(Position).filter(Position.id.in_(position_ids)).all()}
        if position_ids else {}
    )

    def _contract_multiplier(t: Trade) -> int:
        pos = positions.get(t.position_id)
        occ = (pos.option_symbol if pos else None) or (t.notes or {}).get('option_symbol')
        return 100 if occ else 1

    returns = []
    for t in trades:
        entry = t.price or 0.0
        qty = t.filled_qty or t.qty or 0
        if entry <= 0 or qty <= 0:
            continue
        cost = abs(entry * qty * _contract_multiplier(t))
        if cost > 0.01:  # skip near-zero cost basis (data quality)
            returns.append((t.pnl / cost) * 100)

    if len(returns) > 1:
        mean_return = sum(returns) / len(returns)
        variance = sum((x - mean_return) ** 2 for x in returns) / len(returns)
        std_dev = math.sqrt(variance)
        sharpe_ratio = (mean_return / std_dev) if std_dev > 0 else 0.0
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

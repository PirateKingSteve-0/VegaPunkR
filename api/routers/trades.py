"""
Trade management endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from database import get_db
from models import Trade, User, Strategy, Position
from schemas import TradeCreate, TradeResponse
from auth import get_current_user, require_can_write_own

router = APIRouter(prefix="/trades", tags=["Trades"])


@router.get("", response_model=List[TradeResponse])
def get_trades(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    side: Optional[str] = Query(None, description="Filter by side (buy/sell)"),
    start_date: Optional[datetime] = Query(None, description="Filter trades after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter trades before this date"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of trades to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get trade history for the current user.

    Optional filters:
    - symbol: Filter by specific symbol (e.g., 'AAPL')
    - strategy_id: Filter by strategy ID
    - side: Filter by trade side ('buy' or 'sell')
    - start_date: Only trades after this date
    - end_date: Only trades before this date
    - limit: Maximum number of trades (default 100, max 1000)
    """
    query = db.query(Trade).filter(Trade.user_id == current_user.id)

    if symbol:
        query = query.filter(Trade.symbol == symbol.upper())

    if strategy_id:
        query = query.filter(Trade.strategy_id == strategy_id)

    if side:
        if side.lower() not in ['buy', 'sell']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Side must be 'buy' or 'sell'"
            )
        query = query.filter(Trade.side == side.lower())

    if start_date:
        query = query.filter(Trade.timestamp >= start_date)

    if end_date:
        query = query.filter(Trade.timestamp <= end_date)

    # Order by most recent first and limit results
    trades = query.order_by(Trade.timestamp.desc()).limit(limit).all()
    return trades


@router.get("/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific trade by ID.
    """
    trade = db.query(Trade).filter(
        Trade.id == trade_id,
        Trade.user_id == current_user.id
    ).first()

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found"
        )

    return trade


@router.post("", response_model=TradeResponse, status_code=status.HTTP_201_CREATED)
def create_trade(
    trade_data: TradeCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Record a new trade.

    This is called when a trade is executed (either manually or by a strategy).
    """
    # Validate strategy exists if provided
    if trade_data.strategy_id:
        strategy = db.query(Strategy).filter(
            Strategy.id == trade_data.strategy_id,
            Strategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )

    # Validate position exists if provided
    if trade_data.position_id:
        position = db.query(Position).filter(
            Position.id == trade_data.position_id,
            Position.user_id == current_user.id
        ).first()

        if not position:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Position not found"
            )

    # Validate side
    if trade_data.side.lower() not in ['buy', 'sell']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Side must be 'buy' or 'sell'"
        )

    db_trade = Trade(
        user_id=current_user.id,
        symbol=trade_data.symbol.upper(),
        side=trade_data.side.lower(),
        order_type=trade_data.order_type.lower(),
        qty=trade_data.qty,
        filled_qty=trade_data.filled_qty or trade_data.qty,
        price=trade_data.price,
        commission=trade_data.commission,
        timestamp=datetime.utcnow(),
        strategy_id=trade_data.strategy_id,
        position_id=trade_data.position_id,
        status='executed',
        notes=trade_data.notes
    )

    db.add(db_trade)
    db.commit()
    db.refresh(db_trade)

    return db_trade


@router.put("/{trade_id}/close", response_model=TradeResponse)
def close_trade(
    trade_id: int,
    exit_price: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Close a trade by recording the exit price and calculating P&L.

    This is used for tracking when positions are exited.
    """
    trade = db.query(Trade).filter(
        Trade.id == trade_id,
        Trade.user_id == current_user.id
    ).first()

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found"
        )

    if trade.exit_price is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Trade already closed"
        )

    trade.exit_price = exit_price
    trade.exit_timestamp = datetime.utcnow()

    # Calculate P&L
    if trade.side == 'buy':
        # Long position: P&L = (exit_price - entry_price) * qty
        trade.pnl = (exit_price - trade.price) * trade.filled_qty
    else:
        # Short position: P&L = (entry_price - exit_price) * qty
        trade.pnl = (trade.price - exit_price) * trade.filled_qty

    # Subtract commission from P&L
    trade.pnl -= trade.commission

    db.commit()
    db.refresh(trade)

    return trade


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trade(
    trade_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Delete a trade record.

    This should only be used to remove erroneous trades.
    For normal operations, use the close endpoint instead.
    """
    trade = db.query(Trade).filter(
        Trade.id == trade_id,
        Trade.user_id == current_user.id
    ).first()

    if not trade:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trade not found"
        )

    db.delete(trade)
    db.commit()

    return None


@router.get("/summary/stats")
def get_trade_statistics(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get trade statistics for a given time period.

    Returns:
    - Total trades
    - Total volume (shares traded)
    - Total P&L
    - Win rate
    - Average profit/loss per trade
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    query = db.query(Trade).filter(
        Trade.user_id == current_user.id,
        Trade.timestamp >= start_date
    )

    if strategy_id:
        query = query.filter(Trade.strategy_id == strategy_id)

    trades = query.all()

    if not trades:
        return {
            "total_trades": 0,
            "total_volume": 0,
            "total_pnl": 0.0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
            "total_commission": 0.0
        }

    total_trades = len(trades)
    total_volume = sum(t.filled_qty for t in trades)
    closed_trades = [t for t in trades if t.pnl is not None]

    total_pnl = sum(t.pnl for t in closed_trades)
    winning_trades = len([t for t in closed_trades if t.pnl > 0])
    losing_trades = len([t for t in closed_trades if t.pnl < 0])
    total_commission = sum(t.commission for t in trades)

    win_rate = (winning_trades / len(closed_trades) * 100) if closed_trades else 0.0
    avg_pnl = (total_pnl / len(closed_trades)) if closed_trades else 0.0

    return {
        "total_trades": total_trades,
        "total_volume": total_volume,
        "total_pnl": round(total_pnl, 2),
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 2),
        "avg_pnl": round(avg_pnl, 2),
        "total_commission": round(total_commission, 2),
        "days_analyzed": days
    }

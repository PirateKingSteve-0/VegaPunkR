"""
Position management endpoints.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Position, User, Strategy
from schemas import PositionCreate, PositionUpdate, PositionResponse
from auth import get_current_user, require_can_write_own
from utils.symbol_helpers import is_option_symbol

router = APIRouter(prefix="/positions", tags=["Positions"])


@router.get("", response_model=List[PositionResponse])
def get_positions(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    strategy_id: Optional[int] = Query(None, description="Filter by strategy ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all positions for the current user.

    Optional filters:
    - symbol: Filter positions by specific symbol (e.g., 'AAPL')
    - strategy_id: Filter positions by strategy ID
    """
    # Open rows only. Position rows are per-contract now, so closed ones
    # accumulate — one per contract ever traded — and "positions" means what is
    # held, not what was ever held (that is what `trades` is for). The Angular
    # page already filtered `qty > 0` client-side; this makes the API agree.
    query = db.query(Position).filter(
        Position.user_id == current_user.id,
        Position.qty > 0,
    )

    if symbol:
        query = query.filter(Position.symbol == symbol.upper())

    if strategy_id:
        query = query.filter(Position.strategy_id == strategy_id)

    positions = query.all()
    return positions


@router.get("/{position_id}", response_model=PositionResponse)
def get_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific position by ID.
    """
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == current_user.id
    ).first()

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found"
        )

    return position


@router.post("", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
def create_position(
    position_data: PositionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Create a new position.

    This is typically called when opening a new trade.
    """
    # Validate strategy exists if provided
    if position_data.strategy_id:
        strategy = db.query(Strategy).filter(
            Strategy.id == position_data.strategy_id,
            Strategy.user_id == current_user.id
        ).first()

        if not strategy:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found"
            )

    # Check if position already exists for this symbol
    existing_position = db.query(Position).filter(
        Position.user_id == current_user.id,
        Position.symbol == position_data.symbol.upper(),
        Position.strategy_id == position_data.strategy_id
    ).first()

    if existing_position:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Position for {position_data.symbol} already exists. Use update endpoint to modify quantity."
        )

    db_position = Position(
        user_id=current_user.id,
        symbol=position_data.symbol.upper(),
        qty=position_data.qty,
        avg_entry_price=position_data.avg_entry_price,
        strategy_id=position_data.strategy_id,
        current_price=position_data.avg_entry_price,  # Initialize with entry price
        unrealized_pnl=0.0  # Initialize at zero
    )

    db.add(db_position)
    db.commit()
    db.refresh(db_position)

    return db_position


@router.put("/{position_id}", response_model=PositionResponse)
def update_position(
    position_id: int,
    position_data: PositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Update an existing position.

    This is used to update:
    - Quantity (when adding to or reducing a position)
    - Current price (for real-time P&L tracking)
    - Unrealized P&L
    """
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == current_user.id
    ).first()

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found"
        )

    # Update fields if provided
    update_data = position_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(position, field, value)

    # Recalculate unrealized P&L if current price is updated
    if position_data.current_price is not None:
        # Options contracts have a 100x multiplier (each contract = 100 shares)
        multiplier = 100 if is_option_symbol(position.option_symbol or position.symbol) else 1
        position.unrealized_pnl = (position.current_price - position.avg_entry_price) * position.qty * multiplier

    db.commit()
    db.refresh(position)

    return position


@router.delete("/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
def close_position(
    position_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
):
    """
    Close (delete) a position.

    This should be called when a position is fully closed/exited.
    The corresponding closing trade should be recorded in the trades table first.
    """
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.user_id == current_user.id
    ).first()

    if not position:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Position not found"
        )

    db.delete(position)
    db.commit()

    return None


@router.get("/summary/overview")
def get_positions_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a summary of all open positions.

    Returns:
    - Total number of open positions
    - Total unrealized P&L
    - Total market value
    """
    # `qty > 0` matters here specifically: total_positions is a COUNT of rows, so
    # without it a per-contract schema reports every contract ever traded as an
    # open position. The P&L sums were always safe (closed rows are zeroed).
    positions = db.query(Position).filter(
        Position.user_id == current_user.id,
        Position.qty > 0,
    ).all()

    total_positions = len(positions)
    total_unrealized_pnl = sum(p.unrealized_pnl or 0 for p in positions)
    total_market_value = sum((p.current_price or p.avg_entry_price) * p.qty for p in positions)
    total_cost_basis = sum(p.avg_entry_price * p.qty for p in positions)

    return {
        "total_positions": total_positions,
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_market_value": round(total_market_value, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "pnl_percentage": round((total_unrealized_pnl / total_cost_basis * 100), 2) if total_cost_basis > 0 else 0.0
    }

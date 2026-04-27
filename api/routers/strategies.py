"""
Strategy management endpoints.
"""
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Strategy, User
from schemas import StrategyCreate, StrategyUpdate, StrategyResponse
from auth import get_current_user
from strategy_templates import StrategyTemplates
from engine.event_logger import log_event

router = APIRouter(prefix="/strategies", tags=["Strategies"])


@router.get("", response_model=List[StrategyResponse])
def get_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all strategies for the current user.
    """
    strategies = db.query(Strategy).filter(Strategy.user_id == current_user.id).all()
    return strategies


@router.get("/templates", response_model=List[Dict[str, Any]])
def get_strategy_templates():
    """
    Get all available strategy templates (read-only).

    These are predefined scalping strategies optimized for small accounts.
    Users can clone these templates to create their own editable strategies.
    """
    return StrategyTemplates.get_all_templates()


@router.get("/templates/{template_id}", response_model=Dict[str, Any])
def get_strategy_template(template_id: str):
    """
    Get a specific strategy template by ID.
    """
    template = StrategyTemplates.get_template_by_id(template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )

    return template


@router.post("/templates/{template_id}/clone", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
def clone_strategy_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Clone a strategy template to create a new user strategy.

    This creates an editable copy of the template that the user owns.
    """
    template = StrategyTemplates.get_template_by_id(template_id)

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_id}' not found"
        )

    # Create a new strategy from the template
    db_strategy = Strategy(
        user_id=current_user.id,
        name=f"{template['name']} (Copy)",  # Add "(Copy)" to distinguish from template
        strategy_type=template["strategy_type"],
        params_json=template["params_json"],
        instruments=template["instruments"],
        timeframe=template["timeframe"],
        max_positions=template["max_positions"],
        stop_loss_percentage=template["stop_loss_percentage"],
        take_profit_percentage=template["take_profit_percentage"],
        is_active=False,  # Cloned strategies start inactive for safety
        is_paper_trading=True  # Always start in paper trading mode
    )

    db.add(db_strategy)
    db.commit()
    db.refresh(db_strategy)

    return db_strategy


@router.get("/{strategy_id}", response_model=StrategyResponse)
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific strategy by ID.
    """
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    return strategy


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
def create_strategy(
    strategy_data: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new strategy.
    """
    db_strategy = Strategy(
        user_id=current_user.id,
        name=strategy_data.name,
        strategy_type=strategy_data.strategy_type,
        params_json=strategy_data.params_json,
        instruments=strategy_data.instruments,
        timeframe=strategy_data.timeframe,
        max_positions=strategy_data.max_positions,
        stop_loss_percentage=strategy_data.stop_loss_percentage,
        take_profit_percentage=strategy_data.take_profit_percentage,
        is_active=True,  # New strategies start active by default
        is_paper_trading=strategy_data.is_paper_trading
    )

    db.add(db_strategy)
    db.commit()
    db.refresh(db_strategy)

    return db_strategy


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: int,
    strategy_data: StrategyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update an existing strategy.
    """
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    # Update fields if provided
    update_data = strategy_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'params_json' and isinstance(value, dict) and isinstance(strategy.params_json, dict):
            # Merge params so that keys not sent by the UI (e.g. delta_min, exit_before_close_minutes)
            # are not silently wiped — UI edits only touch the keys they know about
            merged = {**strategy.params_json, **value}
            from sqlalchemy.orm.attributes import flag_modified
            strategy.params_json = merged
            flag_modified(strategy, 'params_json')
        else:
            setattr(strategy, field, value)

    db.commit()
    db.refresh(strategy)

    return strategy


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a strategy.
    """
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    db.delete(strategy)
    db.commit()

    return None


@router.post("/{strategy_id}/toggle", response_model=StrategyResponse)
async def toggle_strategy_status(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Toggle strategy active status (activate/deactivate).
    Also starts or stops the execution task in the StreamDrivenWorker.
    """
    from engine.stream_driven_worker import get_stream_driven_worker

    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found"
        )

    strategy.is_active = not strategy.is_active
    db.commit()
    db.refresh(strategy)

    worker = get_stream_driven_worker()
    if strategy.is_active:
        await worker.start_strategy(strategy_id)
    else:
        await worker.stop_strategy(strategy_id)

    log_event(
        db=db,
        user_id=current_user.id,
        event_type="STRATEGY_STARTED" if strategy.is_active else "STRATEGY_STOPPED",
        title=f"{'Started' if strategy.is_active else 'Stopped'} \"{strategy.name}\"",
        strategy_id=strategy.id,
        severity="info",
        event_data={"strategy_type": strategy.strategy_type, "is_paper": strategy.is_paper_trading},
    )

    return strategy

"""
Strategy management endpoints.
"""
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Strategy, User
from schemas import StrategyCreate, StrategyUpdate, StrategyResponse
from auth import get_current_user, require_can_write_own
from strategy_templates import StrategyTemplates
from engine.event_logger import log_event
from engine.risk_manager import RiskManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategies", tags=["Strategies"])


# The same two settings live in three places on a strategy: the
# `stop_loss_percentage` / `take_profit_percentage` COLUMNS, and the
# `stop_loss_pct` / `stop_loss_percentage` keys INSIDE `params_json`. Only
# params_json is ever read by the engine (`signal_generator.py:581`), so a write
# that touched the column alone returned 200 and changed nothing about trading —
# the API reporting success for an edit that never took effect.
#
# On prod the two genuinely disagreed once (column 15, params 50); the UI form
# carries a comment about it. This closes the same hole for callers that do not
# go through the form.
_RISK_FIELD_PAIRS = (
    ("stop_loss_percentage", "stop_loss_pct"),
    ("take_profit_percentage", "take_profit_pct"),
)


def _engine_value(params: Dict[str, Any], key: str, column_name: str):
    """What the ENGINE would read for this setting, resolution order included.

    Mirrors `signal_generator.py:581` exactly — `params['<x>_pct'] or
    params['<x>_percentage']` — falsy-zero quirk and all. Deliberately not
    "fixed" here: if this resolved 0 differently from the engine, the column
    would go back to disagreeing with what actually trades, which is the whole
    bug. Change both or neither.
    """
    return params.get(key) or params.get(column_name)


def _reconcile_risk_fields(strategy: Strategy, sent: set) -> None:
    """Keep the columns and params_json from ever disagreeing.

    `sent` is the set of field names the caller actually supplied, so an
    untouched field is never rewritten from a stale value.

      1. Both sent and contradicting  -> 422. They are one setting.
      2. Column sent alone            -> push it INTO params_json, so the
                                         caller's intent actually takes effect
                                         instead of being silently dropped.
      3. Otherwise                    -> mirror the column FROM params_json, so
                                         what is displayed is what the engine
                                         will apply.
    """
    params = dict(strategy.params_json or {})
    touched = False

    for column_name, key in _RISK_FIELD_PAIRS:
        column_sent = column_name in sent
        params_sent = "params_json" in sent and (
            key in params or column_name in params
        )
        column_value = getattr(strategy, column_name, None)

        if column_sent and params_sent:
            engine_value = _engine_value(params, key, column_name)
            if engine_value is not None and column_value is not None and (
                float(engine_value) != float(column_value)
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"'{column_name}' ({column_value}) and "
                        f"params_json['{key}'] ({engine_value}) are the same "
                        "setting. Send one of them, not both with different "
                        "values."
                    ),
                )

        if column_sent and not params_sent:
            # Rule 2 — honour the edit. Write BOTH spellings: the engine prefers
            # `_pct`, so writing only `_percentage` would leave a stale `_pct` in
            # charge and the edit would still do nothing.
            params[key] = column_value
            params[column_name] = column_value
            touched = True
        else:
            # Rule 3 — the column is a mirror of what the engine will use.
            engine_value = _engine_value(params, key, column_name)
            if engine_value is not None:
                setattr(strategy, column_name, float(engine_value))

    if touched:
        from sqlalchemy.orm.attributes import flag_modified
        strategy.params_json = params
        flag_modified(strategy, "params_json")


def _attach_entry_block(db: Session, user: User, strategy: Strategy) -> Strategy:
    """Stamp the live entry-block status onto a strategy for serialisation.

    Read-only: `get_entry_block_status` writes nothing and commits nothing, so
    this is safe on a GET. Set as a plain instance attribute — `entry_block` is
    not a column, and pydantic's `from_attributes` picks it up either way.

    Never allowed to fail the request. If the risk evaluation raises, the page
    still renders; it simply shows no badge. A broken badge must not be able to
    take down the strategies list.
    """
    try:
        strategy.entry_block = RiskManager(db).get_entry_block_status(user, strategy)
    except Exception:
        logger.exception(f"Entry-block status failed for strategy {strategy.id}")
        strategy.entry_block = None
    return strategy


@router.get("", response_model=List[StrategyResponse])
def get_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all strategies for the current user.
    """
    strategies = db.query(Strategy).filter(Strategy.user_id == current_user.id).all()
    return [_attach_entry_block(db, current_user, s) for s in strategies]


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
    current_user: User = Depends(require_can_write_own)
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

    # Templates currently ship the column and params_json in agreement; this
    # makes that a guarantee rather than a coincidence a future edit could break.
    _reconcile_risk_fields(db_strategy, set())

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

    return _attach_entry_block(db, current_user, strategy)


@router.post("", response_model=StrategyResponse, status_code=status.HTTP_201_CREATED)
def create_strategy(
    strategy_data: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
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

    _reconcile_risk_fields(db_strategy, set(strategy_data.model_dump(exclude_unset=True)))

    db.add(db_strategy)
    db.commit()
    db.refresh(db_strategy)

    return db_strategy


@router.put("/{strategy_id}", response_model=StrategyResponse)
def update_strategy(
    strategy_id: int,
    strategy_data: StrategyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
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

    # Runs AFTER the field loop so it sees the final state of both the columns
    # and the merged params_json, and can reject or reconcile on the real values.
    _reconcile_risk_fields(strategy, set(update_data))

    db.commit()
    db.refresh(strategy)

    return strategy


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own)
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
    current_user: User = Depends(require_can_write_own)
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

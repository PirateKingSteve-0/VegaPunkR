"""
Execution Control Endpoints - Start/Stop/Status for strategy execution
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict

from database import get_db
from auth import get_current_user, require_can_write_own, require_can_place_orders
from models import User, Strategy
from engine.stream_driven_worker import get_stream_driven_worker
from engine.tradier_stream_manager import get_stream_manager

router = APIRouter(prefix="/execution", tags=["execution"])


def _get_strategy_for_user(strategy_id: int, user: User, db: Session) -> Strategy:
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == user.id
    ).first()
    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )
    return strategy


@router.post("/strategies/{strategy_id}/start")
async def start_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own),
):
    """
    Start the stream-driven execution task for a strategy.
    The strategy must already be marked active (is_active=True).
    """
    strategy = _get_strategy_for_user(strategy_id, current_user, db)

    if not strategy.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strategy must be active before starting execution. Toggle it active first."
        )

    if current_user.selected_trading_mode == "live" and strategy.is_paper_trading:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot run a paper strategy in live trading mode."
        )

    worker = get_stream_driven_worker()
    await worker.start_strategy(strategy_id)

    return {
        "success": True,
        "message": f"Strategy '{strategy.name}' execution started",
        "strategy_id": strategy_id,
        "task_running": strategy_id in worker._tasks,
        "trading_mode": current_user.selected_trading_mode,
    }


@router.post("/strategies/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_write_own),
):
    """
    Stop the execution task for a strategy. Does not close open positions.
    """
    strategy = _get_strategy_for_user(strategy_id, current_user, db)

    worker = get_stream_driven_worker()
    await worker.stop_strategy(strategy_id)

    return {
        "success": True,
        "message": f"Strategy '{strategy.name}' execution stopped",
        "strategy_id": strategy_id,
        "task_running": strategy_id in worker._tasks,
    }


@router.get("/strategies/{strategy_id}/status")
async def get_strategy_status(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether the stream-driven execution task for this strategy is alive.
    """
    strategy = _get_strategy_for_user(strategy_id, current_user, db)

    worker = get_stream_driven_worker()
    task = worker._tasks.get(strategy_id)

    task_info = None
    if task:
        task_info = {
            "name": task.get_name(),
            "done": task.done(),
            "cancelled": task.cancelled(),
            "exception": str(task.exception()) if task.done() and not task.cancelled() and task.exception() else None,
        }

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        "is_active": strategy.is_active,
        "is_paper_trading": strategy.is_paper_trading,
        "task_running": task is not None and not task.done(),
        "task": task_info,
    }


@router.get("/worker/status")
async def get_worker_status(
    current_user: User = Depends(get_current_user),
):
    """
    Full status of the StreamDrivenWorker and Tradier stream connection.
    Shows all running strategy tasks and which symbols are subscribed.
    """
    worker = get_stream_driven_worker()
    stream_mgr = get_stream_manager()

    tasks_info = []
    for sid, task in worker._tasks.items():
        tasks_info.append({
            "strategy_id": sid,
            "task_name": task.get_name(),
            "running": not task.done(),
            "done": task.done(),
            "cancelled": task.cancelled(),
        })

    return {
        "worker_running": worker._running,
        "active_tasks": len([t for t in worker._tasks.values() if not t.done()]),
        "tasks": tasks_info,
        "stream": {
            "connected": stream_mgr._ws is not None,
            "session_id": stream_mgr._session_id,
            "subscribed_symbols": stream_mgr.active_symbols(),
        },
    }


@router.get("/active-strategies")
async def get_active_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    All active strategies for the current user with their live execution task status.
    """
    worker = get_stream_driven_worker()

    strategies = db.query(Strategy).filter(
        Strategy.user_id == current_user.id,
        Strategy.is_active == True
    ).all()

    results = []
    for strategy in strategies:
        task = worker._tasks.get(strategy.id)
        results.append({
            "id": strategy.id,
            "name": strategy.name,
            "type": strategy.strategy_type,
            "instruments": strategy.instruments,
            "is_paper_trading": strategy.is_paper_trading,
            "task_running": task is not None and not task.done(),
        })

    return {
        "count": len(results),
        "strategies": results,
        "user_trading_mode": current_user.selected_trading_mode,
    }


@router.post("/strategies/{strategy_id}/execute-tick")
async def execute_strategy_tick_manual(
    strategy_id: int,
    market_data: Dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_can_place_orders),
):
    """
    Manually inject one market_data tick into a strategy (testing/debugging only).
    """
    from engine.strategy_executor import StrategyExecutor

    strategy = _get_strategy_for_user(strategy_id, current_user, db)
    executor = StrategyExecutor(db)
    results = await executor.execute_strategy_tick(
        user=current_user,
        strategy=strategy,
        market_data=market_data,
    )
    return results


@router.get("/strategies/{strategy_id}/risk-summary")
async def get_strategy_risk_summary(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Risk metrics summary for a strategy."""
    from engine.strategy_executor import StrategyExecutor

    strategy = _get_strategy_for_user(strategy_id, current_user, db)
    executor = StrategyExecutor(db)
    risk_summary = executor.get_risk_summary(current_user, strategy)

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        **risk_summary,
    }

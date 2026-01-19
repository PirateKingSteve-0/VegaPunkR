"""
Execution Control Endpoints - Start/Stop/Status for strategy execution
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Dict

from database import get_db
from auth import get_current_user
from models import User, Strategy
from engine.strategy_executor import StrategyExecutor

router = APIRouter(prefix="/execution", tags=["execution"])

# Global strategy executor instance (singleton pattern)
# In production, this would be managed by the background worker
_executor_instance = None


def get_executor(db: Session = Depends(get_db)) -> StrategyExecutor:
    """Get or create strategy executor instance"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = StrategyExecutor(db)
    return _executor_instance


@router.post("/strategies/{strategy_id}/start")
async def start_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Start executing a strategy

    This enables the strategy for automated execution by the background worker.
    The strategy must be active and belong to the current user.

    Returns:
        - success: Whether the operation succeeded
        - message: Status message
        - started_at: Timestamp when strategy execution started
    """
    # Verify strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )

    # Verify strategy is active
    if not strategy.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strategy must be active to start execution. Enable it first."
        )

    # Check paper vs live mode consistency
    if current_user.selected_trading_mode == "live" and strategy.is_paper_trading:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot run paper strategy in live trading mode. Switch to paper mode first."
        )

    # Start the strategy
    result = executor.start_strategy(strategy_id)

    if not result['success']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result['message']
        )

    return {
        "success": True,
        "message": result['message'],
        "started_at": result.get('started_at'),
        "strategy": {
            "id": strategy.id,
            "name": strategy.name,
            "type": strategy.strategy_type,
            "is_paper_trading": strategy.is_paper_trading
        },
        "trading_mode": current_user.selected_trading_mode
    }


@router.post("/strategies/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Stop executing a strategy

    This stops automated execution but does not close open positions.
    Use close_all_positions endpoint to close positions.

    Returns:
        - success: Whether the operation succeeded
        - message: Status message
    """
    # Verify strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )

    # Stop the strategy
    result = executor.stop_strategy(strategy_id)

    if not result['success']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result['message']
        )

    return {
        "success": True,
        "message": result['message'],
        "strategy": {
            "id": strategy.id,
            "name": strategy.name
        }
    }


@router.get("/strategies/{strategy_id}/status")
async def get_strategy_execution_status(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Get current execution status of a strategy

    Returns:
        - strategy_id: Strategy ID
        - is_running: Whether strategy is currently executing
        - started_at: When execution started
        - last_check_at: Last time strategy was evaluated
        - error_count: Number of consecutive errors
        - last_error: Last error message if any
    """
    # Verify strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )

    # Get execution status
    status_info = executor.get_strategy_status(strategy_id)

    return {
        **status_info,
        "strategy": {
            "id": strategy.id,
            "name": strategy.name,
            "type": strategy.strategy_type,
            "is_active": strategy.is_active,
            "is_paper_trading": strategy.is_paper_trading
        }
    }


@router.get("/strategies/{strategy_id}/risk-summary")
async def get_strategy_risk_summary(
    strategy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Get risk metrics summary for a strategy

    Returns current risk metrics including:
    - Today's P&L
    - Daily loss limits
    - Open positions count
    - Unrealized P&L
    - Risk status (OK/WARNING)
    """
    # Verify strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )

    # Get risk summary
    risk_summary = executor.get_risk_summary(current_user, strategy)

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy.name,
        **risk_summary
    }


@router.post("/strategies/{strategy_id}/execute-tick")
async def execute_strategy_tick_manual(
    strategy_id: int,
    market_data: Dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Manually execute one tick of strategy logic (for testing)

    This endpoint is primarily for testing and debugging.
    In production, the background worker calls execute_strategy_tick automatically.

    Body:
        market_data: Dict with current market data
            {
                "symbol": "SPY",
                "price": 450.25,
                "volume": 1000000,
                "bid": 450.24,
                "ask": 450.26,
                "delta": 0.65 (optional, for options),
                "open_interest": 5000 (optional, for options),
                "tick_value": 850 (optional, $TICK indicator)
            }

    Returns:
        - strategy_id: Strategy ID
        - timestamp: Execution timestamp
        - signals_generated: List of signals generated
        - orders_placed: List of orders executed
        - positions_closed: List of positions closed
        - errors: List of errors if any
    """
    # Verify strategy exists and belongs to user
    strategy = db.query(Strategy).filter(
        Strategy.id == strategy_id,
        Strategy.user_id == current_user.id
    ).first()

    if not strategy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strategy {strategy_id} not found"
        )

    # Execute strategy tick
    results = await executor.execute_strategy_tick(
        user=current_user,
        strategy=strategy,
        market_data=market_data
    )

    return results


@router.get("/active-strategies")
async def get_active_strategies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    executor: StrategyExecutor = Depends(get_executor)
):
    """
    Get all active strategies for the current user with their execution status

    Returns:
        List of strategies with their execution status
    """
    # Get all active strategies for user
    strategies = db.query(Strategy).filter(
        Strategy.user_id == current_user.id,
        Strategy.is_active == True
    ).all()

    results = []
    for strategy in strategies:
        status_info = executor.get_strategy_status(strategy.id)
        results.append({
            "id": strategy.id,
            "name": strategy.name,
            "type": strategy.strategy_type,
            "is_paper_trading": strategy.is_paper_trading,
            "max_positions": strategy.max_positions,
            "execution_status": status_info
        })

    return {
        "count": len(results),
        "strategies": results,
        "user_trading_mode": current_user.selected_trading_mode
    }

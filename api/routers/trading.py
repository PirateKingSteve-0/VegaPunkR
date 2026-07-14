"""
Unified Trading API endpoints.

Routes account and position requests to Tradier — SANDBOX for paper mode, LIVE for live
mode — based on the user's selected trading mode. Tradier is the only broker.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import get_current_user
from engine.trading_client_manager import trading_manager

router = APIRouter(prefix="/trading", tags=["Trading"])


@router.get("/account")
async def get_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get account information from the appropriate trading API.

    - Paper mode: Returns Tradier sandbox account data
    - Live mode: Returns Tradier LIVE account data

    Syncs portfolio_value → user.account_size_usd so the risk manager
    always uses the real account balance for position sizing.
    """
    try:
        account = await trading_manager.get_account(current_user)

        # Keep account_size_usd in sync with real balance
        portfolio_value = account.get("portfolio_value") or account.get("equity")
        if portfolio_value and float(portfolio_value) > 0:
            current_user.account_size_usd = float(portfolio_value)
            db.commit()

        return account
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch account data: {str(e)}"
        )


@router.get("/history")
async def get_history(
    page: int = Query(1),
    limit: int = Query(25),
    symbol: Optional[str] = Query(None),
    start: Optional[str] = Query(None, description="yyyy-mm-dd"),
    end: Optional[str] = Query(None, description="yyyy-mm-dd"),
    current_user: User = Depends(get_current_user),
):
    """
    Get trade history from the appropriate trading API.

    - Paper mode: Proxies to Tradier sandbox (note: detailed history not available in sandbox)
    - Live mode: Not yet implemented, returns empty list

    Returns list of trade events with date, symbol, side, quantity, price, amount, commission.
    """
    try:
        history = await trading_manager.get_history(
            current_user,
            page=page,
            limit=limit,
            symbol=symbol,
            start=start,
            end=end,
        )
        return history
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch trade history: {str(e)}"
        )


@router.get("/positions")
async def get_positions(current_user: User = Depends(get_current_user)):
    """
    Get current positions from the appropriate trading API.

    - Paper mode: Returns Tradier SANDBOX positions
    - Live mode: Returns Tradier LIVE positions

    Returns:
        List of positions with symbol, qty, prices, and P&L
    """
    try:
        positions = await trading_manager.get_positions(current_user)
        return positions
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch positions: {str(e)}"
        )

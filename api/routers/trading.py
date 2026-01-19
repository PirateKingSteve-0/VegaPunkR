"""
Unified Trading API endpoints.

Routes account and position requests to the appropriate API (Alpaca Paper or Schwab Live)
based on the user's selected trading mode.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User
from auth import get_current_user
from engine.trading_client_manager import trading_manager

router = APIRouter(prefix="/trading", tags=["Trading"])


@router.get("/account")
async def get_account(current_user: User = Depends(get_current_user)):
    """
    Get account information from the appropriate trading API.

    - Paper mode: Returns Alpaca paper trading account data
    - Live mode: Returns Schwab live account data

    Returns:
        Account information including cash, buying_power, equity, portfolio_value
    """
    try:
        account = await trading_manager.get_account(current_user)
        return account
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch account data: {str(e)}"
        )


@router.get("/positions")
async def get_positions(current_user: User = Depends(get_current_user)):
    """
    Get current positions from the appropriate trading API.

    - Paper mode: Returns Alpaca paper trading positions
    - Live mode: Returns Schwab live positions

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

"""
Schwab brokerage integration endpoints.

Handles account info, positions, and order execution through Schwab API.
Market data is retrieved from Alpaca (separate integration).
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import get_current_user
from models import User
from schwab_integration.client import get_schwab_client, SCHWAB_AVAILABLE

router = APIRouter(prefix="/schwab", tags=["Schwab Brokerage"])


# Pydantic models for requests/responses
class OrderRequest(BaseModel):
    """Request body for placing an order."""
    symbol: str
    quantity: int
    side: str  # 'BUY' or 'SELL'
    order_type: str = 'MARKET'  # 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None


@router.get("/account/info")
def get_account_info(current_user: User = Depends(get_current_user)):
    """
    Get Schwab account information including balances and positions.

    Returns full account details from Schwab API.
    """
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available. Install schwab-py: pip install schwab-py"
        )

    client = get_schwab_client()

    # Try to authenticate if not already
    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed. Run authentication flow first."
            )

    account_info = client.get_account_info()

    if not account_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unable to fetch Schwab account information"
        )

    return account_info


@router.get("/account/balances")
def get_account_balances(current_user: User = Depends(get_current_user)):
    """
    Get simplified account balances.

    Returns:
        {
            'cash': float,
            'buying_power': float,
            'equity': float,
            'market_value': float,
            'cash_available_for_trading': float,
            'day_trading_buying_power': float
        }
    """
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available"
        )

    client = get_schwab_client()

    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed"
            )

    balances = client.get_account_balances()

    if not balances:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unable to fetch account balances"
        )

    return balances


@router.get("/account/positions")
def get_account_positions(current_user: User = Depends(get_current_user)):
    """
    Get current positions from Schwab account.

    Returns list of positions with symbol, quantity, P&L, etc.
    """
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available"
        )

    client = get_schwab_client()

    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed"
            )

    positions = client.get_positions()

    if positions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unable to fetch positions"
        )

    return positions


@router.post("/orders/place", status_code=status.HTTP_201_CREATED)
def place_order(
    order: OrderRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Place an order on Schwab.

    Request body:
        {
            "symbol": "SPY",
            "quantity": 1,
            "side": "BUY",
            "order_type": "MARKET"
        }

    For LIMIT orders, include "limit_price".
    For STOP orders, include "stop_price".
    """
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available"
        )

    client = get_schwab_client()

    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed"
            )

    # Validate order parameters
    if order.side.upper() not in ['BUY', 'SELL']:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Side must be 'BUY' or 'SELL'"
        )

    if order.order_type == 'LIMIT' and not order.limit_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit price required for LIMIT orders"
        )

    if order.order_type in ['STOP', 'STOP_LIMIT'] and not order.stop_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stop price required for STOP orders"
        )

    # Place order
    result = client.place_order(
        symbol=order.symbol,
        quantity=order.quantity,
        side=order.side.upper(),
        order_type=order.order_type.upper(),
        limit_price=order.limit_price,
        stop_price=order.stop_price
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to place order on Schwab"
        )

    return result


@router.get("/orders/{order_id}")
def get_order_status(
    order_id: str,
    current_user: User = Depends(get_current_user)
):
    """Get status of a specific order by ID."""
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available"
        )

    client = get_schwab_client()

    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed"
            )

    order_status = client.get_order_status(order_id)

    if not order_status:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} not found"
        )

    return order_status


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(
    order_id: str,
    current_user: User = Depends(get_current_user)
):
    """Cancel a pending order."""
    if not SCHWAB_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Schwab API not available"
        )

    client = get_schwab_client()

    if not client._client:
        if not client.authenticate():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Schwab authentication failed"
            )

    success = client.cancel_order(order_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel order {order_id}"
        )

    return None


@router.get("/auth/status")
def get_auth_status(current_user: User = Depends(get_current_user)):
    """
    Check if Schwab API is authenticated.

    Returns:
        {
            'authenticated': bool,
            'token_exists': bool
        }
    """
    if not SCHWAB_AVAILABLE:
        return {
            'authenticated': False,
            'token_exists': False,
            'error': 'Schwab library not installed'
        }

    client = get_schwab_client()

    import os
    token_exists = os.path.exists(client.token_path)

    return {
        'authenticated': client._client is not None,
        'token_exists': token_exists
    }

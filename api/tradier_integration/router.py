"""
Tradier brokerage integration endpoints.

Exposes account balances, positions, orders, transaction history,
and realized gain/loss from the Tradier Brokerage Account API.
"""
import asyncio
import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from auth import get_current_user, decode_access_token
from database import SessionLocals
from config import Environment
from models import User
from tradier_integration.client import get_tradier_client

router = APIRouter(prefix="/tradier", tags=["Tradier Brokerage"])


def _client():
    return get_tradier_client()


@router.get("/stream/events")
async def stream_events(
    request: Request,
    symbols: str = Query(..., description="Comma-separated list of symbols to stream"),
    token: str = Query(..., description="JWT access token (required because EventSource cannot set headers)"),
):
    """
    SSE endpoint — browser EventSource connects here to receive filtered market events.

    The backend owns the single Tradier WebSocket. This endpoint taps the shared
    StreamRouter so no second Tradier session is created per client.
    """
    # Validate token manually — EventSource cannot send Authorization headers
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    db = SessionLocals[Environment.DEV]()
    try:
        user = db.query(User).filter(User.email == payload["sub"]).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    finally:
        db.close()

    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No symbols provided")

    conn_id = str(uuid.uuid4())

    from engine.stream_router import get_stream_router
    from engine.tradier_stream_manager import get_stream_manager

    router = get_stream_router()
    stream_mgr = get_stream_manager()

    # Subscribe the symbols on the shared WS (ref-counted — safe to call multiple times)
    await stream_mgr.subscribe(symbol_list)
    q = await router.register_ui(conn_id, symbol_list)

    async def generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat keeps the connection alive through proxies
                    yield 'data: {"type":"heartbeat"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            router.unregister_ui(conn_id, symbol_list)
            await stream_mgr.unsubscribe(symbol_list)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@router.get("/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    """GET /v1/user/profile — Tradier user info and account numbers."""
    try:
        return _client().get_profile()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/balances")
def get_balances(
    account_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/balances

    Returns total_equity, total_cash, open_pl, stock_buying_power,
    option_buying_power, and the full margin or cash sub-object.
    """
    try:
        return _client().get_balances(account_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/positions")
def get_positions(
    account_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/positions

    Returns open positions with symbol, quantity, cost_basis, date_acquired.
    """
    try:
        return _client().get_positions(account_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/orders")
def get_orders(
    account_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/orders

    Returns today's orders (id, symbol, side, qty, price, type, status).
    """
    try:
        return _client().get_orders(account_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/history")
def get_history(
    account_id: Optional[str] = Query(None),
    period: Optional[str] = Query(None, description="WEEK|MONTH|YEAR|YEAR_5|YEAR_10|YTD|ALL — returns balance snapshots for charting"),
    page: int = Query(1),
    limit: int = Query(25),
    type: Optional[str] = Query(None, description="trade|option|ach|dividend|fee|interest"),
    start: Optional[str] = Query(None, description="yyyy-mm-dd"),
    end: Optional[str] = Query(None, description="yyyy-mm-dd"),
    symbol: Optional[str] = Query(None),
    exact_match: bool = Query(False),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/history

    Without `period`: detailed transaction history (trades, dividends, ACH…).
    With `period`: historical balance snapshots for portfolio performance charts.
    Note: detailed history is not available for sandbox accounts.
    """
    try:
        return _client().get_history(
            account_id=account_id,
            period=period,
            page=page,
            limit=limit,
            type=type,
            start=start,
            end=end,
            symbol=symbol,
            exact_match=exact_match,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/historical-balances")
def get_historical_balances(
    account_id: Optional[str] = Query(None),
    period: str = Query("MONTH", description="WEEK|MONTH|YTD|YEAR|YEAR_3|YEAR_5|ALL"),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/historical-balances

    Daily account value snapshots for charting the equity curve over the
    chosen period. Returns {balances:[{date,value}...], delta, deltaPercent}.
    """
    try:
        return _client().get_historical_balances(account_id, period=period)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/market/history")
def get_market_history(
    symbol: str = Query(..., description="Equity ticker or OCC option symbol"),
    interval: str = Query("daily", description="daily|weekly|monthly"),
    start: Optional[str] = Query(None, description="yyyy-mm-dd"),
    end: Optional[str] = Query(None, description="yyyy-mm-dd"),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/markets/history — historical OHLCV bars for charting a position.
    """
    try:
        return _client().get_history_pricing(symbol=symbol, interval=interval, start=start, end=end)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/market/timesales")
def get_market_timesales(
    symbol: str = Query(..., description="Equity ticker or OCC option symbol"),
    interval: str = Query("5min", description="tick|1min|5min|15min"),
    start: Optional[str] = Query(None, description="YYYY-MM-DD HH:MM"),
    end: Optional[str] = Query(None, description="YYYY-MM-DD HH:MM"),
    session_filter: str = Query("all", description="open|all"),
    current_user: User = Depends(get_current_user),
):
    """GET /v1/markets/timesales — intraday OHLCV bars."""
    try:
        return _client().get_timesales(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            session_filter=session_filter,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


class WatchlistCreatePayload(BaseModel):
    name: str = Field(..., min_length=1)
    symbols: List[str] = Field(default_factory=list)


class WatchlistUpdatePayload(BaseModel):
    name: str = Field(..., min_length=1)
    symbols: Optional[List[str]] = None


class WatchlistSymbolsPayload(BaseModel):
    symbols: List[str] = Field(..., min_length=1)


@router.get("/market/quotes")
def get_market_quotes(
    symbols: str = Query(..., description="Comma-separated list of symbols"),
    current_user: User = Depends(get_current_user),
):
    """GET /v1/markets/quotes — last/change quotes for one or more symbols."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    try:
        return _client().get_quotes(symbol_list)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/watchlists")
def list_watchlists(current_user: User = Depends(get_current_user)):
    """GET /v1/watchlists — list all of the user's watchlists."""
    try:
        return _client().get_watchlists()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: str, current_user: User = Depends(get_current_user)):
    """GET /v1/watchlists/{watchlist_id} — fetch a specific watchlist with its symbols."""
    try:
        return _client().get_watchlist(watchlist_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.post("/watchlists")
def create_watchlist(
    payload: WatchlistCreatePayload,
    current_user: User = Depends(get_current_user),
):
    """POST /v1/watchlists — create a new watchlist."""
    try:
        return _client().create_watchlist(payload.name, payload.symbols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.put("/watchlists/{watchlist_id}")
def update_watchlist(
    watchlist_id: str,
    payload: WatchlistUpdatePayload,
    current_user: User = Depends(get_current_user),
):
    """PUT /v1/watchlists/{watchlist_id} — rename a watchlist or replace its symbols."""
    try:
        return _client().update_watchlist(watchlist_id, payload.name, payload.symbols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.delete("/watchlists/{watchlist_id}")
def delete_watchlist(watchlist_id: str, current_user: User = Depends(get_current_user)):
    """DELETE /v1/watchlists/{watchlist_id}"""
    try:
        return _client().delete_watchlist(watchlist_id)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.post("/watchlists/{watchlist_id}/symbols")
def add_watchlist_symbols(
    watchlist_id: str,
    payload: WatchlistSymbolsPayload,
    current_user: User = Depends(get_current_user),
):
    """POST /v1/watchlists/{watchlist_id}/symbols — add symbols to a watchlist."""
    try:
        return _client().add_watchlist_symbols(watchlist_id, payload.symbols)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.delete("/watchlists/{watchlist_id}/symbols/{symbol}")
def remove_watchlist_symbol(
    watchlist_id: str,
    symbol: str,
    current_user: User = Depends(get_current_user),
):
    """DELETE /v1/watchlists/{watchlist_id}/symbols/{symbol}"""
    try:
        return _client().remove_watchlist_symbol(watchlist_id, symbol)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/account/gainloss")
def get_gainloss(
    account_id: Optional[str] = Query(None),
    page: int = Query(1),
    limit: int = Query(25),
    current_user: User = Depends(get_current_user),
):
    """
    GET /v1/accounts/{account_id}/gainloss

    Realized gain/loss for all closed positions (updated nightly).
    Returns cost_basis, proceeds, and realized P&L per closed position.
    """
    try:
        return _client().get_gainloss(account_id, page=page, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

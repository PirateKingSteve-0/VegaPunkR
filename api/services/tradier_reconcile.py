"""
Reconcile Tradier account history with local Trade rows.

Tradier's order/preview responses don't include final commission/fees, but the
account history endpoint does. This service pulls history events and writes
commission and fee values back onto the matching Trade rows.

Matching rules:
  - type=trade  -> match Trade by user_id + symbol + side + qty within ±1 day
                   of the event timestamp; write `commission`.
  - type=fee    -> attach to the closest same-day Trade for the user; add the
                   absolute event amount to that Trade's `fees` column. Standalone
                   fees with no same-day trade are skipped (logged) — they belong
                   to the broader account, not to a specific strategy trade.
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import Trade, User
from tradier_integration.client import get_tradier_client

logger = logging.getLogger(__name__)

_MATCH_WINDOW = timedelta(days=1)
_PAGE_LIMIT = 500


def _parse_event_date(event: Dict[str, Any]) -> Optional[datetime]:
    raw = event.get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None


def _event_side(event: Dict[str, Any]) -> Optional[str]:
    """Tradier history events nest the side under `trade` or in description."""
    trade_block = event.get("trade") or {}
    side = trade_block.get("trade_type") or event.get("side")
    if side:
        side = side.lower()
        if side in ("buy", "buy_to_open", "buy_to_close"):
            return "buy"
        if side in ("sell", "sell_short", "sell_to_open", "sell_to_close"):
            return "sell"
    desc = (event.get("description") or "").lower()
    if desc.startswith("bought"):
        return "buy"
    if desc.startswith("sold"):
        return "sell"
    return None


def _find_matching_trade(
    db: Session,
    user_id: int,
    event: Dict[str, Any],
    event_date: datetime,
) -> Optional[Trade]:
    symbol = event.get("symbol")
    qty = event.get("quantity")
    side = _event_side(event)
    if not symbol or qty is None:
        return None

    window_start = event_date - _MATCH_WINDOW
    window_end = event_date + _MATCH_WINDOW

    q = db.query(Trade).filter(
        Trade.user_id == user_id,
        Trade.symbol == symbol,
        Trade.timestamp >= window_start,
        Trade.timestamp <= window_end,
        Trade.qty == int(qty),
    )
    if side:
        q = q.filter(Trade.side == side)

    candidates = q.all()
    if not candidates:
        return None
    return min(candidates, key=lambda t: abs((t.timestamp - event_date).total_seconds()))


def _find_same_day_trade(db: Session, user_id: int, event_date: datetime) -> Optional[Trade]:
    day_start = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    candidates = (
        db.query(Trade)
        .filter(
            Trade.user_id == user_id,
            Trade.timestamp >= day_start,
            Trade.timestamp < day_end,
        )
        .all()
    )
    if not candidates:
        return None
    return min(candidates, key=lambda t: abs((t.timestamp - event_date).total_seconds()))


def reconcile_user_history(
    db: Session,
    user: User,
    start: Optional[str] = None,
    end: Optional[str] = None,
    account_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Pull Tradier account history for the date range and update local Trade rows
    with commission/fees. Returns a summary of what was written.
    """
    client = get_tradier_client()

    trade_events: List[Dict[str, Any]] = []
    fee_events: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch = client.get_history(
            account_id=account_id,
            page=page,
            limit=_PAGE_LIMIT,
            start=start,
            end=end,
        )
        if not batch:
            break
        for ev in batch:
            etype = ev.get("type")
            if etype in ("trade", "option"):
                trade_events.append(ev)
            elif etype == "fee":
                fee_events.append(ev)
        if len(batch) < _PAGE_LIMIT:
            break
        page += 1

    matched_trades = 0
    commission_written = 0.0
    matched_fees = 0
    fees_written = 0.0
    unmatched_trades = 0
    unmatched_fees = 0

    for ev in trade_events:
        event_date = _parse_event_date(ev)
        if not event_date:
            unmatched_trades += 1
            continue
        trade = _find_matching_trade(db, user.id, ev, event_date)
        if trade is None:
            unmatched_trades += 1
            logger.debug("No Trade match for history event %s", ev)
            continue
        commission = float(ev.get("commission") or 0.0)
        if commission and trade.commission != commission:
            trade.commission = commission
            commission_written += commission
            matched_trades += 1

    for ev in fee_events:
        event_date = _parse_event_date(ev)
        if not event_date:
            unmatched_fees += 1
            continue
        trade = _find_same_day_trade(db, user.id, event_date)
        if trade is None:
            unmatched_fees += 1
            logger.debug("No same-day Trade for fee event %s", ev)
            continue
        amount = abs(float(ev.get("amount") or 0.0))
        trade.fees = (trade.fees or 0.0) + amount
        fees_written += amount
        matched_fees += 1

    db.commit()

    return {
        "trade_events": len(trade_events),
        "fee_events": len(fee_events),
        "matched_trades": matched_trades,
        "commission_written": round(commission_written, 2),
        "matched_fees": matched_fees,
        "fees_written": round(fees_written, 2),
        "unmatched_trades": unmatched_trades,
        "unmatched_fees": unmatched_fees,
    }

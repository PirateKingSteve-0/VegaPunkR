"""Per-account cash left and start-of-day equity, shared by every strategy worker.

Design: docs/sizing-basis-design-2026-09-29.md (owner-approved, sizing mode B).

WHY
---
Sizing and the daily-loss / drawdown caps used to read `user.account_size_usd`, which
nothing in the engine updates: the dashboard writes it when its account page loads
(routers/trading.py). On 2026-09-28 it read $1,757.84, saved at 10:49 ET while a put
was open, and each strategy worker held its own copy, so two "account-wide" caps in
the same second could differ (2026-09-25: $73.76 vs $77.53).

WHAT THIS HOLDS, per (user, trading mode), for one ET market day
-----------------------------------------------------------------
Keyed by MODE as well as user: paper and live are different accounts at the broker,
and the mode can be switched mid-day (routers/system.py). One shared entry would carry
sandbox figures (~$100k) into live trading for the rest of the day (engine-guard H1).

  cash_left         settled cash at the day's first refresh, minus every buy fill the
                    engine records afterwards. Sells never add back: that money settles
                    T+1. It only goes DOWN within a day.
  day_start_equity  broker total equity at refresh time minus today's realized P&L minus
                    open positions' unrealized P&L = the account value at the start of the
                    ET day. Rejected as implausible (-> None, old source) when it is below
                    the settled cash just read, or more than PLAUSIBLE_EQUITY_BAND away from
                    total equity: stale Position rows must not poison a whole day.

HOW CASH LEFT IS LOWERED (owner's choice, 2026-09-29: "careful update")
------------------------------------------------------------------------
  * A buy fill takes its cost off at once (record_buy_fill).
  * A few seconds later the broker is re-read. Its figure is adopted only if it is
    LOWER than our count, and only while NO other buy is in flight (a working order's
    hold would otherwise be counted twice once it fills). A drop beyond
    FEE_TOLERANCE must be seen on a second read CONFIRM_SECONDS later before it is
    adopted, so one glitchy reading can't block entries for the rest of the day.
  * Exception, the day's FIRST read: if it can't fund one contract it is "suspect" and
    not trusted (qty left to the broker gate). A clean second read then REPLACES the
    count in either direction, because the broker figure already includes any fill we
    subtracted meanwhile (review F1). Clean = no buy in flight, no fill recorded during
    the read, last fill >= FILL_SETTLE_SECONDS old; else retry, MAX_CONFIRM_ATTEMPTS.

Refreshed with ONE get_balances call per (user, mode) per ET day (plus one after a
restart). A failed refresh is not retried for REFRESH_RETRY_SECONDS.

Readers treat None as "unknown" and fall back to the old behaviour. This module never
blocks an entry by itself and is never consulted on a sell.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

from sqlalchemy import func

from models import Position, Trade
from utils.market_hours import market_day_start_utc

logger = logging.getLogger(__name__)

REFRESH_RETRY_SECONDS = 60.0     # after a failed refresh, wait this long before trying again
POST_FILL_CHECK_SECONDS = 5.0    # delay before re-reading the broker after a buy fill
CONFIRM_SECONDS = 30.0           # second read before adopting a large drop
FEE_TOLERANCE = 5.0              # a drop this small is fees/rounding: adopt on one read
PLAUSIBLE_EQUITY_BAND = 0.5      # start-of-day equity must be within ±50% of total equity
FILL_SETTLE_SECONDS = 5.0        # don't trust a broker read taken this soon after our last fill
MAX_CONFIRM_ATTEMPTS = 5         # first-read re-checks before leaving it to the broker gate

Key = Tuple[int, str]            # (user_id, trading mode)


@dataclass
class AccountDay:
    day_key: str                       # market_day_start_utc() of the ET day, ISO
    cash_left: float
    day_start_equity: Optional[float]  # None if unknown or implausible
    refreshed_at: datetime = field(default_factory=datetime.utcnow)
    fills_recorded: int = 0            # buy fills subtracted since the refresh
    last_fill_at: Optional[datetime] = None
    first_read_confirmed: bool = False # a second read has vouched for the first (N1)
    confirming: bool = False           # a first-read confirmation is scheduled
    suspect: bool = False              # the first read looked too low; untrusted until confirmed


_LOCK = threading.Lock()
_STATE: Dict[Key, AccountDay] = {}
_FAILED_AT: Dict[Key, datetime] = {}   # last failed refresh (UTC)


def mode_of(user) -> str:
    """The trading mode the broker client is chosen by (trading_client_manager)."""
    return (getattr(user, "selected_trading_mode", None) or "paper").lower()


def _day_key(now_utc: Optional[datetime] = None) -> str:
    return market_day_start_utc(now_utc).isoformat()


def get(user_id: int, mode: str) -> Optional[AccountDay]:
    """Today's entry for this account, or None."""
    with _LOCK:
        st = _STATE.get((user_id, mode))
        return st if st and st.day_key == _day_key() else None


def cash_left(user_id: int, mode: str) -> Optional[float]:
    st = get(user_id, mode)
    return st.cash_left if st else None


def day_start_equity(user_id: int, mode: str) -> Optional[float]:
    st = get(user_id, mode)
    return st.day_start_equity if st else None


def _cash_from_balances(balances: dict) -> Optional[float]:
    # Same precedence as order_manager's cash gate: settled cash on a real cash
    # account, total_cash where the account type has no cash block (sandbox).
    raw = (balances.get("cash") or {}).get("cash_available")
    if raw is None:
        raw = balances.get("total_cash")
    return float(raw) if raw is not None else None


def _today_pnl(db, user_id: int) -> float:
    """Realized today (ET day) + unrealized on open positions. Same queries as the
    account daily-loss cap, so both see the same P&L."""
    realized = db.query(func.sum(Trade.pnl)).filter(
        Trade.user_id == user_id,
        Trade.timestamp >= market_day_start_utc(),
        Trade.status == 'executed',
        Trade.pnl.isnot(None),
    ).scalar() or 0.0
    unrealized = db.query(func.sum(Position.unrealized_pnl)).filter(
        Position.user_id == user_id,
        Position.qty > 0,
    ).scalar() or 0.0
    return float(realized) + float(unrealized)


def _plausible_day_start(value: float, total_equity: float, cash: float) -> bool:
    if value <= 0 or total_equity <= 0:
        return False
    if abs(value - total_equity) > PLAUSIBLE_EQUITY_BAND * total_equity:
        return False
    # Settled cash only falls intraday, and start-of-day equity includes the
    # start-of-day cash, so the start value can't be below the cash just read.
    return value >= cash - FEE_TOLERANCE


async def ensure_fresh(user_id: int, mode: str, get_client: Callable[[], object], db) -> Optional[AccountDay]:
    """Today's entry, refreshing from the broker (one call) if there isn't one yet.

    Returns None when the broker can't be read; callers fall back to the old behaviour.
    Never raises.
    """
    key = (user_id, mode)
    st = get(user_id, mode)
    if st:
        return st
    failed = _FAILED_AT.get(key)
    if failed and (datetime.utcnow() - failed).total_seconds() < REFRESH_RETRY_SECONDS:
        return None
    try:
        client = get_client()
        balances = await asyncio.to_thread(client.get_balances) or {}
        cash = _cash_from_balances(balances)
        if cash is None:
            raise ValueError("balances carried no cash figure")
        equity = None
        equity_raw = balances.get("total_equity")
        if equity_raw is not None:
            total = float(equity_raw)
            candidate = total - _today_pnl(db, user_id)
            if _plausible_day_start(candidate, total, cash):
                equity = candidate
            else:
                logger.warning(
                    f"Start-of-day equity for user {user_id} ({mode}) rejected as implausible: "
                    f"${candidate:,.2f} from total equity ${total:,.2f}, settled cash ${cash:,.2f}. "
                    f"Sizing and loss caps use user.account_size_usd today."
                )
        st = AccountDay(day_key=_day_key(), cash_left=cash, day_start_equity=equity)
        with _LOCK:
            # Two workers may refresh at once; a fill recorded in between must not be
            # undone, so keep the lower cash.
            prev = _STATE.get(key)
            if prev and prev.day_key == st.day_key:
                st.cash_left = min(st.cash_left, prev.cash_left)
            _STATE[key] = st
        _FAILED_AT.pop(key, None)
        eq = f"${st.day_start_equity:,.2f}" if st.day_start_equity is not None else "unknown"
        logger.info(
            f"Account state refreshed for user {user_id} ({mode}): cash left "
            f"${st.cash_left:,.2f}, start-of-day equity {eq}"
        )
        return st
    except Exception as e:
        _FAILED_AT[key] = datetime.utcnow()
        logger.warning(
            f"Account state refresh failed for user {user_id} ({mode}): {e}. Falling back "
            f"to user.account_size_usd; next attempt in {REFRESH_RETRY_SECONDS:.0f}s."
        )
        return None


def record_buy_fill(user_id: int, mode: str, cost: float) -> None:
    """A buy filled: its cost comes off cash left at once. No-op without today's entry
    (the next refresh reads the broker, which already includes this fill)."""
    if cost <= 0:
        return
    with _LOCK:
        st = _STATE.get((user_id, mode))
        if st and st.day_key == _day_key():
            st.cash_left = max(0.0, st.cash_left - cost)
            st.fills_recorded += 1
            st.last_fill_at = datetime.utcnow()
            logger.info(f"Cash left for user {user_id} ({mode}): ${st.cash_left:,.2f} after a ${cost:,.2f} buy")


def first_read_unconfirmed(user_id: int, mode: str) -> bool:
    """True while today's figure is still the single first read of the day, with no
    fill of ours subtracted since and no second read vouching for it. A LOW value in
    that state is not trusted yet (owner, 2026-09-29: "double-check it"): a glitchy
    first read must not block entries all day."""
    st = get(user_id, mode)
    # Once suspected, it stays untrusted until a clean second read confirms it, even
    # after fills of ours: the broker's own gate may have let one through meanwhile.
    return bool(st and not st.first_read_confirmed and (st.fills_recorded == 0 or st.suspect))


def _fills_snapshot(user_id: int, mode: str) -> Optional[int]:
    st = get(user_id, mode)
    return st.fills_recorded if st else None


def _read_is_clean(st: AccountDay, fills_before: Optional[int], in_flight: Callable[[], bool]) -> bool:
    """A broker read may be applied only if nothing moved under it: no fill of ours
    recorded while it was taken (it would be counted twice), no buy in flight (its
    hold would be), and the last fill old enough for the broker to reflect it."""
    if fills_before is None or st.fills_recorded != fills_before or in_flight():
        return False
    if st.last_fill_at and (datetime.utcnow() - st.last_fill_at).total_seconds() < FILL_SETTLE_SECONDS:
        return False
    return True


async def _confirm_first_read(user_id: int, mode: str, client, in_flight: Callable[[], bool]) -> None:
    """Second read for a low first read (owner, 2026-09-29). When it's clean, the broker
    figure REPLACES our count in either direction: it already includes any fill we
    subtracted in the meantime, which is what makes a glitchy $0 first read recoverable
    even after the broker's own gate let a buy through (review F1). Not clean → wait and
    retry, up to MAX_CONFIRM_ATTEMPTS."""
    try:
        for _ in range(MAX_CONFIRM_ATTEMPTS):
            await asyncio.sleep(CONFIRM_SECONDS)
            before = _fills_snapshot(user_id, mode)
            read = _cash_from_balances(await asyncio.to_thread(client.get_balances) or {})
            with _LOCK:
                st = _STATE.get((user_id, mode))
                if not st or st.day_key != _day_key():
                    return
                if read is None or not _read_is_clean(st, before, in_flight):
                    continue
                if read != st.cash_left:
                    logger.warning(
                        f"First cash reading for user {user_id} ({mode}) re-checked: "
                        f"count ${st.cash_left:,.2f} -> broker ${read:,.2f}"
                    )
                st.cash_left = read
                st.first_read_confirmed = True
                return
        logger.warning(f"First cash reading for user {user_id} ({mode}) could not be re-checked; "
                       f"the broker's own gate keeps deciding until a later attempt")
    except Exception as e:
        logger.warning(f"First-read confirmation failed for user {user_id} ({mode}): {e}")
    finally:
        with _LOCK:
            st = _STATE.get((user_id, mode))
            if st:
                st.confirming = False


def request_first_read_confirmation(user_id: int, mode: str, client,
                                    in_flight: Callable[[], bool]) -> bool:
    """Schedule the second read unless one is pending. True if this call scheduled it."""
    with _LOCK:
        st = _STATE.get((user_id, mode))
        if not st or st.first_read_confirmed:
            return False
        st.suspect = True
        if st.confirming:
            return False
        st.confirming = True
    try:
        task = asyncio.get_running_loop().create_task(
            _confirm_first_read(user_id, mode, client, in_flight))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        return True
    except RuntimeError:
        with _LOCK:
            st.confirming = False
        return False


def refreshed_before(user_id: int, mode: str, when: datetime) -> bool:
    """True if today's cash figure was read from the broker before `when`, i.e. it
    cannot already include a fill of an order placed at `when`."""
    st = get(user_id, mode)
    return bool(st and st.refreshed_at < when)


def _adopt(user_id: int, mode: str, broker_cash: float, why: str) -> None:
    with _LOCK:
        st = _STATE.get((user_id, mode))
        if st and st.day_key == _day_key() and broker_cash < st.cash_left:
            logger.info(
                f"Cash left for user {user_id} ({mode}) lowered to broker figure "
                f"${broker_cash:,.2f} (count was ${st.cash_left:,.2f}; {why})"
            )
            st.cash_left = broker_cash


async def _careful_check(user_id: int, mode: str, client, in_flight: Callable[[], bool],
                         first_delay: float) -> None:
    """The owner's 'careful update'. Never raises."""
    try:
        await asyncio.sleep(first_delay)
        count = cash_left(user_id, mode)
        if count is None:
            return
        before = _fills_snapshot(user_id, mode)
        read = _cash_from_balances(await asyncio.to_thread(client.get_balances) or {})
        if read is None or read >= count:
            return                                    # equal, or broker lagging: keep ours
        if in_flight() or _fills_snapshot(user_id, mode) != before:
            logger.info(f"Post-fill cash check for user {user_id} ({mode}) skipped: a buy moved under it")
            return
        if count - read <= FEE_TOLERANCE:
            _adopt(user_id, mode, read, "fees/rounding")
            return
        await asyncio.sleep(CONFIRM_SECONDS)          # large drop: must repeat to count
        count = cash_left(user_id, mode)
        before = _fills_snapshot(user_id, mode)
        read2 = _cash_from_balances(await asyncio.to_thread(client.get_balances) or {})
        if (count is None or read2 is None or read2 >= count or in_flight()
                or _fills_snapshot(user_id, mode) != before):
            return
        _adopt(user_id, mode, read2, "confirmed on a second read")
    except Exception as e:
        logger.warning(f"Post-fill cash check failed for user {user_id} ({mode}): {e}")


def schedule_post_fill_check(user_id: int, mode: str, client, in_flight: Callable[[], bool],
                             first_delay: float = POST_FILL_CHECK_SECONDS) -> None:
    """Fire-and-forget careful check. `client` is captured by the caller BEFORE the
    order is placed, so a mode switch in the meantime can't point the check at the
    other account.
    Does nothing without a running event loop."""
    try:
        task = asyncio.get_running_loop().create_task(
            _careful_check(user_id, mode, client, in_flight, first_delay)
        )
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    except RuntimeError:
        pass


_TASKS: set = set()   # strong refs so a pending check isn't garbage-collected


def _reset_for_tests() -> None:
    with _LOCK:
        _STATE.clear()
    _FAILED_AT.clear()

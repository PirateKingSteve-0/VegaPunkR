"""
Tradier Account Stream Manager — one persistent WebSocket to the ACCOUNT event stream
(order lifecycle), separate from the market-data stream in tradier_stream_manager.

WHY THIS EXISTS
On 2026-07-13 two orders filled at the broker while the engine's 30-second
`get_order` poll window expired. The engine wrote no Position row, so it believed it
was flat while holding 6 TSLA contracts — no stop-loss, no take-profit, and free to
open a second position on top. Polling is the root cause: we ask, on a timer, a
question the broker is willing to just tell us.

This manager subscribes to order events and records the latest one per order id, so
OrderManager._await_terminal_order can wake the instant a fill lands instead of
grinding 1.5s REST polls until a timeout.

IT IS AN ACCELERATOR, NOT A REPLACEMENT. REST polling stays as the fallback path: if
this stream is down, unsubscribed, or Tradier's Beta flakes, the engine behaves
exactly as it did before. Nothing here is load-bearing for correctness.

TWO STREAMS AT ONCE
Tradier's "not permitted to open more than one session at a time" appears separately
in the market-data and account-data docs, and each stream has its own session endpoint
(/v1/markets/events/session vs /v1/accounts/events/session) and its own socket. The
limit is per stream-type, so this coexists with the market stream. Verified working
against sandbox. Tradier does NOT state the cross-type case explicitly, so if account
events ever stop arriving while market data flows, suspect this assumption first.

EVENT SHAPE (docs/tradier/streaming/ws_account_data.md)
    {"id":1107075,"event":"order","status":"filled","type":"limit","price":10.0,
     "avg_fill_price":10.0,"executed_quantity":2.0,"last_fill_quantity":2.0,
     "remaining_quantity":0.0,"transaction_date":"...","create_date":"...","account":"6YA"}

Note there is NO `symbol` and NO `side` on the event, and the quantity field is
`executed_quantity` (not the REST shape's `exec_quantity`). We therefore treat the
stream purely as a NOTIFICATION keyed on order id, and still fetch the canonical order
over REST to read fill price/qty. Push tells us *when*; REST tells us *what*.
"""
import asyncio
import json
import logging
from typing import Dict, Optional

import websockets

logger = logging.getLogger(__name__)

_RECONNECT_DELAY = 5  # seconds between reconnect attempts

# Order states that will never change again. Mirrors order_manager._TERMINAL_ORDER_STATUSES.
_TERMINAL = {"filled", "rejected", "canceled", "expired"}


class TradierAccountStreamManager:
    """Single WebSocket to Tradier's account event stream, keyed by order id."""

    def __init__(self):
        self._latest: Dict[str, dict] = {}            # order_id -> most recent event
        self._waiters: Dict[str, asyncio.Event] = {}  # order_id -> fires on terminal
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None
        self._session_id: Optional[str] = None

    # ---------------------------------------------------------------- lifecycle

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="tradier-account-stream")
        logger.info("TradierAccountStreamManager started")

    async def stop(self):
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("TradierAccountStreamManager stopped")

    def is_connected(self) -> bool:
        return self._ws is not None

    # ---------------------------------------------------------------- queries

    def latest(self, order_id) -> Optional[dict]:
        return self._latest.get(str(order_id))

    def terminal_status(self, order_id) -> Optional[str]:
        """The terminal status the stream has seen for this order, or None if it has
        not seen one (which includes 'the stream never saw this order at all')."""
        event = self.latest(order_id)
        if not event:
            return None
        status = (event.get("status") or "").lower()
        return status if status in _TERMINAL else None

    async def wait_for_terminal(self, order_id, timeout: float) -> bool:
        """Block until the stream reports this order terminal, or `timeout` elapses.

        Returns True only if a terminal status was actually observed. A False return
        means 'don't know' — never 'the order died' — so callers must fall back to
        REST rather than treating it as a failure.
        """
        if self.terminal_status(order_id):
            return True
        waiter = self._waiters.setdefault(str(order_id), asyncio.Event())
        try:
            await asyncio.wait_for(waiter.wait(), timeout=timeout)
            return self.terminal_status(order_id) is not None
        except asyncio.TimeoutError:
            return False

    def forget(self, order_id) -> None:
        """Drop bookkeeping for a settled order so the maps don't grow without bound."""
        key = str(order_id)
        self._latest.pop(key, None)
        self._waiters.pop(key, None)

    # ---------------------------------------------------------------- internals

    def _create_session_sync(self) -> Dict[str, str]:
        # Account events are per-account, so this MUST use the trading env's client
        # (sandbox when paper) — unlike market data, which is forced to live.
        from tradier_integration.client import get_tradier_client

        return get_tradier_client().create_account_stream_session()

    def _handle(self, event: dict) -> None:
        order_id = event.get("id")
        if order_id is None:
            return
        key = str(order_id)
        self._latest[key] = event

        status = (event.get("status") or "").lower()
        if status in _TERMINAL:
            logger.info(
                f"Account stream: order {key} -> {status} "
                f"(filled {event.get('executed_quantity')} @ {event.get('avg_fill_price')})"
            )
            waiter = self._waiters.get(key)
            if waiter:
                waiter.set()

    async def _run(self):
        while self._running:
            try:
                session = await asyncio.to_thread(self._create_session_sync)
                self._session_id = session["sessionid"]
                url = session["url"]
                if not self._session_id:
                    raise RuntimeError("account stream session returned no sessionid")

                async with websockets.connect(url) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "events": ["order"],
                        "sessionid": self._session_id,
                        "excludeAccounts": [],
                    }))
                    logger.info(f"Account event stream connected: {url}")

                    async for message in ws:
                        # `linebreak` is not documented for the account stream, but
                        # splitting is harmless and guards against it behaving like
                        # the market stream.
                        for line in str(message).split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                self._handle(json.loads(line))
                            except json.JSONDecodeError:
                                logger.debug(f"Account stream: undecodable frame: {line[:120]}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(
                    f"Account stream error: {e} — reconnecting in {_RECONNECT_DELAY}s. "
                    "Fill confirmation falls back to REST polling meanwhile."
                )
            finally:
                self._ws = None
                self._session_id = None

            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY)


_account_stream: Optional[TradierAccountStreamManager] = None


def get_account_stream_manager() -> TradierAccountStreamManager:
    global _account_stream
    if _account_stream is None:
        _account_stream = TradierAccountStreamManager()
    return _account_stream

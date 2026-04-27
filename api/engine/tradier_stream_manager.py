"""
Tradier Stream Manager — single persistent WebSocket connection to Tradier market events.
All strategies and UI connections share this one connection via the StreamRouter.
"""
import asyncio
import json
import logging
from collections import Counter

import websockets

from engine.stream_router import StreamRouter, get_stream_router

logger = logging.getLogger(__name__)

_WS_URL = "wss://ws.tradier.com/v1/markets/events"
_RECONNECT_DELAY = 5  # seconds between reconnect attempts


class TradierStreamManager:
    """
    Manages the single Tradier WebSocket connection.

    Symbol subscriptions are ref-counted: a symbol stays subscribed as long as
    at least one strategy or UI connection needs it. Safe to call subscribe/unsubscribe
    from multiple concurrent tasks.
    """

    def __init__(self, router: StreamRouter):
        self._router = router
        self._refcount: Counter = Counter()
        self._session_id: str | None = None
        self._ws = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run(), name="tradier-stream")
        logger.info("TradierStreamManager started")

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
        logger.info("TradierStreamManager stopped")

    async def subscribe(self, symbols: list[str]):
        async with self._lock:
            for s in symbols:
                self._refcount[s] += 1
        await self._resend_subscription()

    async def unsubscribe(self, symbols: list[str]):
        async with self._lock:
            for s in symbols:
                self._refcount[s] -= 1
                if self._refcount[s] <= 0:
                    del self._refcount[s]
        await self._resend_subscription()

    def active_symbols(self) -> list[str]:
        return list(self._refcount.keys())

    def _create_session_sync(self) -> str:
        from tradier_integration.client import get_tradier_client
        session = get_tradier_client().create_stream_session()
        return session["sessionid"]

    async def _run(self):
        while self._running:
            try:
                self._session_id = await asyncio.to_thread(self._create_session_sync)
                logger.info(f"Tradier stream session acquired: {self._session_id}")

                async with websockets.connect(_WS_URL) as ws:
                    self._ws = ws
                    # Send initial subscription if symbols already queued
                    await self._send_subscription(ws)

                    async for message in ws:
                        for line in message.split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                event = json.loads(line)
                                await self._router.dispatch(event)
                            except json.JSONDecodeError:
                                pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tradier stream error: {e} — reconnecting in {_RECONNECT_DELAY}s")
            finally:
                self._ws = None
                self._session_id = None

            if self._running:
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _resend_subscription(self):
        if self._ws and self._session_id:
            await self._send_subscription(self._ws)

    async def _send_subscription(self, ws):
        symbols = self.active_symbols()
        if not symbols or not self._session_id:
            return
        payload = json.dumps({
            "symbols": symbols,
            "filter": ["trade", "quote"],
            "sessionid": self._session_id,
            "linebreak": True,
        })
        try:
            await ws.send(payload)
            logger.info(f"Stream subscription sent: {symbols}")
        except Exception as e:
            logger.error(f"Failed to send stream subscription: {e}")


_manager: "TradierStreamManager | None" = None


def get_stream_manager() -> "TradierStreamManager":
    global _manager
    if _manager is None:
        _manager = TradierStreamManager(get_stream_router())
    return _manager

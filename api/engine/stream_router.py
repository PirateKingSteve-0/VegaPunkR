"""
Stream Router — fan-out market events by symbol to strategy tasks and UI connections.
"""
import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# Payload types that are allowed to reach strategy/UI queues.
#
# The websocket subscribes to more than this (summary/timesale, TODO.md C2) so
# the session recorder captures them, but those are research data — they must
# never consume a queue slot. Both queues drop on overflow, and the message
# displaced could be the underlying `trade` tick an entry fires on, or the
# option `quote` that refreshes state.option_bid, which the exit path prices
# against (the 2026-08-27 stale-bid take-profits). timesale alone roughly
# doubles trade-side traffic.
#
# This set is exactly what was routed before C2, so filtering here is a no-op
# for the trading path. Adding a type here is a behaviour change: it puts real
# pressure on a 100-slot queue.
_ROUTED_TYPES = frozenset({"trade", "tradex", "quote"})


class StreamRouter:
    """
    Routes incoming stream events (trade/quote) by symbol to all registered consumers.
    Consumers are either persistent strategy tasks (bounded queue, maxsize=100)
    or UI SSE connections (bounded queue, maxsize=200).
    Events are dropped on full queues — stale ticks are worthless for 0DTE.
    """

    def __init__(self):
        # symbol → list of queues that want events for that symbol
        self._routes: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._strategy_queues: dict[int, asyncio.Queue] = {}
        self._ui_queues: dict[str, asyncio.Queue] = {}

    def register_strategy(self, strategy_id: int, symbols: list[str]) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._strategy_queues[strategy_id] = q
        for symbol in symbols:
            self._routes[symbol].append(q)
        logger.info(f"Strategy {strategy_id} registered for symbols: {symbols}")
        return q

    def add_symbol_to_strategy(self, strategy_id: int, symbol: str):
        q = self._strategy_queues.get(strategy_id)
        if q and q not in self._routes[symbol]:
            self._routes[symbol].append(q)
            logger.info(f"Strategy {strategy_id} added symbol {symbol} to routes")

    def remove_symbol_from_strategy(self, strategy_id: int, symbol: str):
        q = self._strategy_queues.get(strategy_id)
        if not q:
            return
        lst = self._routes.get(symbol, [])
        if q in lst:
            lst.remove(q)
            logger.info(f"Strategy {strategy_id} removed symbol {symbol} from routes")
        if not lst:
            self._routes.pop(symbol, None)

    def unregister_strategy(self, strategy_id: int, symbols: list[str]):
        q = self._strategy_queues.pop(strategy_id, None)
        if q:
            for symbol in symbols:
                lst = self._routes.get(symbol, [])
                if q in lst:
                    lst.remove(q)
        logger.info(f"Strategy {strategy_id} unregistered from router")

    async def register_ui(self, conn_id: str, symbols: list[str]) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._ui_queues[conn_id] = q
        for symbol in symbols:
            self._routes[symbol].append(q)
        logger.debug(f"UI connection {conn_id} registered for: {symbols}")
        return q

    def unregister_ui(self, conn_id: str, symbols: list[str]):
        q = self._ui_queues.pop(conn_id, None)
        if q:
            for symbol in symbols:
                lst = self._routes.get(symbol, [])
                if q in lst:
                    lst.remove(q)
        logger.debug(f"UI connection {conn_id} unregistered")

    async def dispatch(self, event: dict):
        symbol = event.get("symbol")
        if not symbol:
            return
        if (event.get("type") or "") not in _ROUTED_TYPES:
            return  # captured by the recorder upstream; never queued
        for q in list(self._routes.get(symbol, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop stale tick rather than block


_router: "StreamRouter | None" = None


def get_stream_router() -> "StreamRouter":
    global _router
    if _router is None:
        _router = StreamRouter()
    return _router

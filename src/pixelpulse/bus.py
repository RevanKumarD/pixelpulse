"""Async event bus for PixelPulse.

Provides a singleton bus that accepts events from any thread/context
and broadcasts them to all async subscribers (primarily the WebSocket
handler that pushes events to the browser dashboard).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

SubscriberCallback = Callable[[dict], Awaitable[None]]


class EventBus:
    """In-process async event bus.

    Events emitted via :meth:`emit` are broadcast to all subscribers
    concurrently. An error in one subscriber does not block others.
    """

    def __init__(self) -> None:
        self._subscribers: list[SubscriberCallback] = []
        self._lock = asyncio.Lock()
        self._history: list[dict] = []
        self._max_history = 200

    async def subscribe(self, callback: SubscriberCallback) -> None:
        async with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    async def unsubscribe(self, callback: SubscriberCallback) -> None:
        async with self._lock:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

    async def emit(self, event: dict) -> None:
        if "timestamp" not in event:
            event = {**event, "timestamp": _utc_now()}

        # Keep history for late-joining clients
        self._history = [*self._history[-(self._max_history - 1):], event]

        async with self._lock:
            targets = list(self._subscribers)

        if not targets:
            return

        results = await asyncio.gather(
            *(cb(event) for cb in targets),
            return_exceptions=True,
        )

        for cb, result in zip(targets, results, strict=False):
            if isinstance(result, Exception):
                logger.error("EventBus subscriber %r raised: %s", cb, result)

    def get_history(self) -> list[dict]:
        return list(self._history)


# ---- Module-level singleton ----

_bus: EventBus | None = None
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop | None = None) -> None:
    global _main_loop
    _main_loop = loop or asyncio.get_running_loop()


def get_event_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def emit_sync(event: dict) -> None:
    """Fire-and-forget event from synchronous code.

    Safe to call from sync functions invoked within an async context,
    or from background threads if :func:`set_main_loop` was called.
    """
    bus = get_event_bus()
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(bus.emit(event))
    except RuntimeError:
        if _main_loop is not None and _main_loop.is_running():
            _main_loop.call_soon_threadsafe(_main_loop.create_task, bus.emit(event))
        else:
            logger.debug("emit_sync: no running loop, event dropped")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()

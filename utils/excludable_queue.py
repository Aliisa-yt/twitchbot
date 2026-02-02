from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

__all__: list[str] = ["ExcludableQueue"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class ExcludableQueue[T](asyncio.Queue[Any]):
    """Queue with exclusive lock for put() and clear() operations."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lock = asyncio.Lock()

    async def put(self, item: T) -> None:
        """Add item to queue with exclusive lock."""
        async with self._lock:
            await super().put(item)

    async def clear(self, callback: Callable[[T], None] | Callable[[T], Awaitable[None]] | None = None) -> None:
        """Clear queue with exclusive lock, optionally applying callback to each item."""
        logger.info("Clearing queue")
        async with self._lock:
            while not self.empty():
                try:
                    item: T = self.get_nowait()
                    if callback is not None:
                        try:
                            result: Awaitable[None] | None = callback(item)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception as err:  # noqa: BLE001 - Catch all to prevent queue clear from failing
                            logger.error("Callback error for item %r: %r", item, err)
                except asyncio.QueueEmpty:
                    break
            logger.info("Queue cleared")

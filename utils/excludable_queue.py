from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

__all__: list[str] = ["ExcludableQueue"]

T = TypeVar("T")

logger: logging.Logger = LoggerUtils.get_logger(__name__)
# logger.addHandler(logging.NullHandler())


class ExcludableQueue(asyncio.Queue[Any], Generic[T]):
    """A queue that allows exclusive access during certain operations.

    This queue is a subclass of asyncio.Queue and provides an additional mechanism to ensure
    that certain operations (such as `put' and `clear') are mutually exclusive.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._lock = asyncio.Lock()

    async def put(self, item: T) -> None:
        """Add an item to the queue.

        If the queue is full, wait until a free slot becomes available before adding an item.
        If clear() is running, wait for clear() to finish for exclusivity control.

        Args:
            item (T): The item to add to the queue.
        """
        async with self._lock:
            await super().put(item)

    async def clear(self, callback: Callable[[T], None] | Callable[[T], Awaitable[None]] | None = None) -> None:
        """Clear the queue.

        This method removes all items from the queue and optionally applies a callback to each item.
        If a callback is provided, it will be called on each item in the queue before it is removed.
        This method is mutually exclusive with put() to ensure that no items are added while clearing.

        Args:
            callback (Callable[[T], None] | Callable[[T], Awaitable[None]] | None):
                A callback function to apply to each item.
                The callback can be a synchronous or asynchronous function. If None, no callback is applied.
        """
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
                        except Exception as err:  # noqa: BLE001
                            logger.error("Callback error for item %r: %r", item, err)
                except asyncio.QueueEmpty:
                    break
            logger.info("Queue cleared")

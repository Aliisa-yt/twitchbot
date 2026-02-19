from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from core.trans.interface import Result


__all__: list[str] = ["InFlightManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class InFlightManager:
    """Manages in-flight translation requests to prevent duplicate processing.

    This class allows marking the start and completion of in-flight translation requests,
    and storing results for requests that are currently being processed.

    Attributes:
        INFLIGHT_TIMEOUT_SEC (float): Timeout duration in seconds for waiting on in-flight translations.
    """

    INFLIGHT_TIMEOUT_SEC: ClassVar[float] = 2.0

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[Result]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()
        self._is_initialized: bool = False

    async def component_load(self) -> None:
        """Initialize the in-flight manager component."""
        self._is_initialized = True
        logger.info("InFlightManager initialized successfully")

    async def component_teardown(self) -> None:
        """Teardown the in-flight manager component and clear in-flight state."""
        self._is_initialized = False
        # Cancel any pending in-flight requests and clear the state.
        async with self._lock:
            for fut in self._inflight.values():
                if not fut.done():
                    fut.cancel()
            self._inflight.clear()
        logger.info("InFlightManager torn down and in-flight state cleared")

    async def mark_inflight_start(self, cache_key: str | None) -> Result | None:
        """Mark the start of an in-flight translation request.

        Args:
            cache_key (str | None): Cache key for the translation request.

        Returns:
            Result | None: The translation result if an in-flight request is already in progress,
            or None if the request was just registered.

        Raises:
            TimeoutError: If waiting for an in-flight translation result times out or is cancelled.
        """
        if not self._is_initialized:
            return None

        if not cache_key:
            logger.warning("Attempted to mark in-flight start with empty cache key")
            return None

        async with self._lock:
            if cache_key not in self._inflight:
                # Not registered: create a Future that the producer will complete.
                loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
                fut: asyncio.Future[Result] = loop.create_future()
                self._inflight[cache_key] = fut
                logger.debug("Marked in-flight start for key: %s", cache_key[:16])
                return None
            fut = self._inflight[cache_key]
            logger.debug("In-flight translation detected for key: %s", cache_key[:16])

        try:
            result: Result = await asyncio.wait_for(asyncio.shield(fut), timeout=self.INFLIGHT_TIMEOUT_SEC)

            logger.debug("Received in-flight translation result for key: %s", cache_key[:16])
        except TimeoutError:
            logger.warning("In-flight translation timeout for key: %s", cache_key[:16])
            async with self._lock:
                current: asyncio.Future[Result] | None = self._inflight.get(cache_key)
                if current is fut:
                    self._inflight.pop(cache_key, None)
            msg: str = f"In-flight translation timed out for key: {cache_key[:16]}"
            raise TimeoutError(msg) from None
        except asyncio.CancelledError:
            logger.warning("In-flight translation cancelled for key: %s", cache_key[:16])
            async with self._lock:
                current = self._inflight.get(cache_key)
                if current is fut:
                    self._inflight.pop(cache_key, None)
            msg = f"In-flight translation cancelled for key: {cache_key[:16]}"
            raise TimeoutError(msg) from None
        else:
            return result

    async def store_inflight_result(self, cache_key: str | None, result: Result) -> None:
        """Store the result of an in-flight translation request.

        Args:
            cache_key (str | None): Cache key for the translation request.
            result (Result): The translation result to store.
        """
        # if not self._is_initialized:
        #     return

        if not cache_key:
            logger.warning("Attempted to store in-flight result with empty cache key")
            return

        async with self._lock:
            fut: asyncio.Future[Result] | None = self._inflight.pop(cache_key, None)
            if fut and not fut.done():
                fut.set_result(result)
                logger.debug("Set in-flight translation result for key: %s", cache_key[:16])
            else:
                logger.warning(
                    "No in-flight future found or already done for key: %s when storing result", cache_key[:16]
                )

    async def store_inflight_exception(self, cache_key: str | None, exc: Exception) -> None:
        """Store an exception for an in-flight translation request.

        Args:
            cache_key (str | None): Cache key for the translation request.
            exc (Exception): The exception to store.
        """
        # if not self._is_initialized:
        #     return

        if not cache_key:
            logger.warning("Attempted to store in-flight exception with empty cache key")
            return

        async with self._lock:
            fut: asyncio.Future[Result] | None = self._inflight.pop(cache_key, None)
            if fut and not fut.done():
                fut.set_exception(exc)
                logger.debug("Set in-flight translation exception for key: %s", cache_key[:16])
            else:
                logger.warning(
                    "No in-flight future found or already done for key: %s when storing exception", cache_key[:16]
                )

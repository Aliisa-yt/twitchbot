"""Tests for InFlightManager."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from core.cache.inflight_manager import InFlightManager

if TYPE_CHECKING:
    from core.trans.interface import Result


@pytest.fixture
async def inflight_manager() -> InFlightManager:
    """Create and initialize InFlightManager."""
    manager = InFlightManager()
    await manager.component_load()
    return manager


@pytest.mark.asyncio
async def test_mark_inflight_start_returns_none_when_not_initialized() -> None:
    """mark_inflight_start should no-op before component initialization."""
    manager = InFlightManager()

    result: Result | None = await manager.mark_inflight_start("key")

    assert result is None


@pytest.mark.asyncio
async def test_mark_inflight_start_timeout_does_not_cancel_shared_future(inflight_manager: InFlightManager) -> None:
    """Wait timeout should not cancel the producer-owned shared future."""
    key = "timeout-key"
    original_timeout: float = InFlightManager.INFLIGHT_TIMEOUT_SEC
    InFlightManager.INFLIGHT_TIMEOUT_SEC = 0.01

    try:
        first: Result | None = await inflight_manager.mark_inflight_start(key)
        assert first is None

        shared_future: asyncio.Future[Result] = inflight_manager._inflight[key]  # noqa: SLF001

        with pytest.raises(TimeoutError):
            await inflight_manager.mark_inflight_start(key)

        assert shared_future.cancelled() is False
    finally:
        InFlightManager.INFLIGHT_TIMEOUT_SEC = original_timeout


@pytest.mark.asyncio
async def test_mark_inflight_start_converts_cancelled_future_to_timeout(inflight_manager: InFlightManager) -> None:
    """Cancelled shared future should be converted to TimeoutError for callers."""
    key = "cancel-key"

    first: Result | None = await inflight_manager.mark_inflight_start(key)
    assert first is None

    waiter: asyncio.Task[Result | None] = asyncio.create_task(inflight_manager.mark_inflight_start(key))
    await asyncio.sleep(0)

    shared_future: asyncio.Future[Result] = inflight_manager._inflight[key]  # noqa: SLF001
    shared_future.cancel()

    with pytest.raises(TimeoutError, match="cancelled"):
        await waiter


@pytest.mark.asyncio
async def test_store_inflight_exception_propagates_to_waiter(inflight_manager: InFlightManager) -> None:
    """Stored inflight exception should propagate to waiting callers."""
    key = "exception-key"

    first: Result | None = await inflight_manager.mark_inflight_start(key)
    assert first is None

    waiter: asyncio.Task[Result | None] = asyncio.create_task(inflight_manager.mark_inflight_start(key))
    await asyncio.sleep(0)

    err = RuntimeError("translation failed")
    await inflight_manager.store_inflight_exception(key, err)

    with pytest.raises(RuntimeError, match="translation failed"):
        await waiter

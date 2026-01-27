import pytest

from utils.excludable_queue import ExcludableQueue


@pytest.mark.asyncio
async def test_clear_with_sync_callback() -> None:
    q = ExcludableQueue[str]()
    await q.put("item1")
    called = []

    def sync_callback(item) -> None:
        called.append(item)

    await q.clear(callback=sync_callback)
    assert called == ["item1"]
    assert q.empty()


@pytest.mark.asyncio
async def test_clear_with_async_callback() -> None:
    q = ExcludableQueue[str]()
    await q.put("item2")
    called = []

    async def async_callback(item) -> None:
        called.append(item)

    await q.clear(callback=async_callback)
    assert called == ["item2"]
    assert q.empty()

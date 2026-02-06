import asyncio

import pytest

from handlers.async_comm import AsyncCommError, AsyncSocket


@pytest.mark.asyncio
async def test_context_manager_does_not_auto_connect() -> None:
    async with AsyncSocket() as s:
        # context entry should not auto-connect
        assert s._reader is None
        assert s._writer is None


@pytest.mark.asyncio
async def test_close_resets_reader_writer() -> None:
    s = AsyncSocket()

    # simulate a connected state with dummy reader/writer
    s._reader = object()  # type: ignore  # noqa: PGH003

    class DummyWriter:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            await asyncio.sleep(0)

    s._writer = DummyWriter()  # type: ignore  # noqa: PGH003

    await s.close()

    assert s._reader is None
    assert s._writer is None


@pytest.mark.asyncio
async def test_send_without_connect_raises() -> None:
    s = AsyncSocket()
    with pytest.raises(AsyncCommError):
        await s.send(b"x")

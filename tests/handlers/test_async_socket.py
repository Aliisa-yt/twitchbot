import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from handlers.async_comm import AsyncCommError, AsyncCommTimeoutError, AsyncSocket


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


# ── AsyncSocket.connect() exception re-raise tests ───────────────────────────


async def test_connect_empty_address_raises_comm_error() -> None:
    # IndexError from address[0] access propagates as AsyncCommError
    s = AsyncSocket()
    with pytest.raises(AsyncCommError, match="Server address is incorrectly specified"):
        await s.connect(())  # type: ignore[arg-type]


async def test_connect_timeout_raises_comm_timeout_error() -> None:
    s = AsyncSocket()
    with patch("asyncio.open_connection", new_callable=AsyncMock, side_effect=TimeoutError), pytest.raises(
        AsyncCommTimeoutError, match="Timeout due to a lack of response"
    ):
        await s.connect(("127.0.0.1", 9999))


async def test_connect_refused_raises_comm_error() -> None:
    s = AsyncSocket()
    with patch("asyncio.open_connection", new_callable=AsyncMock, side_effect=ConnectionRefusedError), pytest.raises(
        AsyncCommError, match="The server is not running"
    ):
        await s.connect(("127.0.0.1", 9999))


async def test_connect_blocking_io_raises_comm_error() -> None:
    s = AsyncSocket()
    with patch("asyncio.open_connection", new_callable=AsyncMock, side_effect=BlockingIOError), pytest.raises(
        AsyncCommError, match="Timeout too short"
    ):
        await s.connect(("127.0.0.1", 9999))


async def test_connect_oserror_raises_comm_error() -> None:
    s = AsyncSocket()
    with patch("asyncio.open_connection", new_callable=AsyncMock, side_effect=OSError("os error")), pytest.raises(
        AsyncCommError, match="OS error during connection"
    ):
        await s.connect(("127.0.0.1", 9999))


# ── AsyncSocket.received() exception re-raise tests ──────────────────────────


async def test_received_without_connect_raises_comm_error() -> None:
    s = AsyncSocket()
    with pytest.raises(AsyncCommError, match="Socket is not connected"):
        await s.received()


async def test_received_timeout_raises_comm_timeout_error() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=TimeoutError), pytest.raises(
        AsyncCommTimeoutError, match="Timed out while waiting for data"
    ):
        await s.received()


async def test_received_connection_reset_raises_comm_error() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=ConnectionResetError), pytest.raises(
        AsyncCommError, match="Connection reset during receive"
    ):
        await s.received()


async def test_received_broken_pipe_raises_comm_error() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=BrokenPipeError), pytest.raises(
        AsyncCommError, match="Connection reset during receive"
    ):
        await s.received()


async def test_received_oserror_raises_comm_error() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=OSError("os error")), pytest.raises(
        AsyncCommError, match="OS error during receive"
    ):
        await s.received()


async def test_received_empty_data_raises_comm_error() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, return_value=b""), pytest.raises(
        AsyncCommError, match="Connection closed by remote host"
    ):
        await s.received()


async def test_received_returns_data() -> None:
    s = AsyncSocket()
    s._reader = AsyncMock()
    with patch("asyncio.wait_for", new_callable=AsyncMock, return_value=b"hello"):
        result = await s.received()
    assert result == b"hello"

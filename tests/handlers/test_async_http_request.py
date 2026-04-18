from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from handlers.async_comm import AsyncCommError, AsyncCommInvalidContentTypeError, AsyncCommTimeoutError, AsyncHttp

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def http() -> AsyncGenerator[AsyncHttp]:
    instance = AsyncHttp()
    yield instance
    await instance.close()


def _inject_mock_session(http: AsyncHttp) -> MagicMock:
    """Replace the internal aiohttp session with a mock and return it."""
    mock_session = MagicMock(closed=False)
    mock_session.close = AsyncMock()
    http._AsyncHttp__session = mock_session  # type: ignore[attr-defined]
    return mock_session


def _make_request_cm_raises(exc: BaseException) -> MagicMock:
    """Return an async context manager mock whose __aenter__ raises exc."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=exc)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _make_request_cm_returns(resp: MagicMock) -> MagicMock:
    """Return an async context manager mock whose __aenter__ returns resp."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ── AsyncHttp._request() exception re-raise tests ────────────────────────────


async def test_request_timeout_raises_comm_timeout_error(http: AsyncHttp) -> None:
    mock_session = _inject_mock_session(http)
    mock_session.request.return_value = _make_request_cm_raises(TimeoutError())

    with pytest.raises(AsyncCommTimeoutError, match="Timeout due to a lack of response"):
        await http.get(url="http://example.com")


async def test_request_connection_reset_raises_comm_error(http: AsyncHttp) -> None:
    mock_session = _inject_mock_session(http)
    mock_session.request.return_value = _make_request_cm_raises(ConnectionResetError())

    with pytest.raises(AsyncCommError, match="The connection to the server has been disconnected"):
        await http.get(url="http://example.com")


async def test_request_connector_error_raises_comm_error(http: AsyncHttp) -> None:
    conn_key = MagicMock()
    connector_err = aiohttp.ClientConnectorError(conn_key, OSError("connect failed"))
    mock_session = _inject_mock_session(http)
    mock_session.request.return_value = _make_request_cm_raises(connector_err)

    with pytest.raises(AsyncCommError, match="The server is not running"):
        await http.get(url="http://example.com")


async def test_request_response_error_raises_comm_error_with_status(http: AsyncHttp) -> None:
    # ClientResponseError raised by resp.raise_for_status() inside _request()
    response_err = aiohttp.ClientResponseError(MagicMock(), (), status=503)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = response_err
    mock_session = _inject_mock_session(http)
    mock_session.request.return_value = _make_request_cm_returns(mock_resp)

    with pytest.raises(AsyncCommError, match="status='503'"):
        await http.get(url="http://example.com")


# ── AsyncHttp.decode_response() tests ────────────────────────────────────────


async def test_decode_response_empty_returns_none(http: AsyncHttp) -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/plain"}
    mock_resp.read = AsyncMock(return_value=b"")

    result = await http.decode_response(mock_resp)

    assert result is None


async def test_decode_response_unknown_content_type_raises(http: AsyncHttp) -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "application/octet-stream"}
    mock_resp.read = AsyncMock(return_value=b"\x00\x01\x02")

    with pytest.raises(AsyncCommInvalidContentTypeError, match="Unknown Content-Type 'application/octet-stream'"):
        await http.decode_response(mock_resp)


async def test_decode_response_text_plain_returns_string(http: AsyncHttp) -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "text/plain"}
    mock_resp.read = AsyncMock(return_value=b"hello world")

    result = await http.decode_response(mock_resp)

    assert result == "hello world"


async def test_decode_response_application_json_returns_dict(http: AsyncHttp) -> None:
    mock_resp = MagicMock()
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.read = AsyncMock(return_value=b'{"key": "value"}')

    result = await http.decode_response(mock_resp)

    assert result == {"key": "value"}


# ── AsyncCommError constructor tests ─────────────────────────────────────────


def test_comm_error_with_response_includes_status() -> None:
    response_err = aiohttp.ClientResponseError(MagicMock(), (), status=500)
    err = AsyncCommError("server error", response=response_err)

    assert "status='500'" in str(err)


def test_comm_error_plain_message() -> None:
    err = AsyncCommError("plain error")

    assert str(err) == "plain error"

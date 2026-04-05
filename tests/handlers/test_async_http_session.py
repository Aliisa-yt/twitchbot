import logging

import pytest

from handlers.async_comm import AsyncHttp


@pytest.mark.asyncio
async def test_init_logs_session_initialized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    # When constructing, __init__ initializes the session and should log it
    AsyncHttp()

    assert any("AsyncHttp session initialized" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_context_enter_does_not_log_already_initialized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    http = AsyncHttp()

    # clear prior logs from __init__
    caplog.clear()

    async with http:
        # nothing to do
        pass

    # Ensure no "session already initialized" message was logged during __aenter__
    assert not any("session already initialized" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_reenter_after_close_logs_session_initialized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    http = AsyncHttp()

    # first context closes the session
    async with http:
        pass

    # After __aexit__, session should be closed. Re-enter should reinitialize and log.
    caplog.clear()

    async with http:
        pass

    assert any("AsyncHttp session initialized" in rec.message for rec in caplog.records)

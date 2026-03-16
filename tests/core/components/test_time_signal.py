"""Unit tests for core.components.removable.time_signal module."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.removable.time_signal import TimeSignalManager
from models.config_models import TimeSignal


def _make_component(time_signal: TimeSignal, *, native_language: str = "ja") -> TimeSignalManager:
    config = SimpleNamespace(
        TIME_SIGNAL=time_signal,
        TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE=native_language),
    )
    shared = MagicMock()
    shared.config = config
    shared.trans_manager = MagicMock()
    shared.tts_manager = MagicMock()
    shared.stt_manager = MagicMock()

    bot = MagicMock()
    bot.shared_data = shared

    return TimeSignalManager(bot)


def _make_time_signal(*, language: str = "ja", text: bool = True, voice: bool = False) -> TimeSignal:
    return TimeSignal(
        ENABLED=True,
        LANGUAGE=language,
        TEXT=text,
        VOICE=voice,
        CLOCK12=True,
        LATE_NIGHT="Late night {hour}",
        EARLY_MORNING="Early morning {hour}",
        MORNING="Morning {hour}",
        LATE_MORNING="Late morning {hour}",
        AFTERNOON="Afternoon {hour}",
        LATE_AFTERNOON="Late afternoon {hour}",
        EVENING="Evening {hour}",
        NIGHT="Night {hour}",
    )


def test_configure_time_signal_builds_slots_from_loaded_messages() -> None:
    time_signal: TimeSignal = _make_time_signal()
    component: TimeSignalManager = _make_component(time_signal)

    assert component._configure_time_signal() is True
    assert [slot[2] for slot in component._time_slots] == [
        time_signal.LATE_NIGHT,
        time_signal.EARLY_MORNING,
        time_signal.MORNING,
        time_signal.LATE_MORNING,
        time_signal.AFTERNOON,
        time_signal.LATE_AFTERNOON,
        time_signal.EVENING,
        time_signal.NIGHT,
    ]


@pytest.mark.asyncio
async def test_event_time_signal_prints_expected_message_at_noon_for_english() -> None:
    component: TimeSignalManager = _make_component(_make_time_signal(language="en", text=True, voice=False))
    assert component._configure_time_signal() is True

    fixed_now = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    with (
        patch.object(component, "print_console_message") as mocked_print,
        patch.object(component, "store_tts_queue", new_callable=AsyncMock) as mocked_store_tts_queue,
        patch("core.components.removable.time_signal.datetime") as mocked_datetime,
    ):
        mocked_datetime.now.return_value.astimezone.return_value = fixed_now
        await component.event_time_signal._coro(component)

    mocked_print.assert_called_once_with("Afternoon 12")
    mocked_store_tts_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_time_signal_prints_expected_message_at_noon_for_japanese() -> None:
    component: TimeSignalManager = _make_component(_make_time_signal(language="ja", text=True, voice=False))
    assert component._configure_time_signal() is True

    fixed_now = datetime(2026, 3, 16, 12, 0, 0, tzinfo=UTC)
    with (
        patch.object(component, "print_console_message") as mocked_print,
        patch.object(component, "store_tts_queue", new_callable=AsyncMock) as mocked_store_tts_queue,
        patch("core.components.removable.time_signal.datetime") as mocked_datetime,
    ):
        mocked_datetime.now.return_value.astimezone.return_value = fixed_now
        await component.event_time_signal._coro(component)

    mocked_print.assert_called_once_with("Afternoon 0")
    mocked_store_tts_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_time_signal_prints_expected_message_at_late_night_for_english() -> None:
    component: TimeSignalManager = _make_component(_make_time_signal(language="en", text=True, voice=False))
    assert component._configure_time_signal() is True

    fixed_now = datetime(2026, 3, 16, 0, 0, 0, tzinfo=UTC)
    with (
        patch.object(component, "print_console_message") as mocked_print,
        patch.object(component, "store_tts_queue", new_callable=AsyncMock) as mocked_store_tts_queue,
        patch("core.components.removable.time_signal.datetime") as mocked_datetime,
    ):
        mocked_datetime.now.return_value.astimezone.return_value = fixed_now
        await component.event_time_signal._coro(component)

    mocked_print.assert_called_once_with("Late night 12")
    mocked_store_tts_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_time_signal_prints_expected_message_at_late_night_for_japanese() -> None:
    component: TimeSignalManager = _make_component(_make_time_signal(language="ja", text=True, voice=False))
    assert component._configure_time_signal() is True

    fixed_now = datetime(2026, 3, 16, 0, 0, 0, tzinfo=UTC)
    with (
        patch.object(component, "print_console_message") as mocked_print,
        patch.object(component, "store_tts_queue", new_callable=AsyncMock) as mocked_store_tts_queue,
        patch("core.components.removable.time_signal.datetime") as mocked_datetime,
    ):
        mocked_datetime.now.return_value.astimezone.return_value = fixed_now
        await component.event_time_signal._coro(component)

    mocked_print.assert_called_once_with("Late night 0")
    mocked_store_tts_queue.assert_not_awaited()

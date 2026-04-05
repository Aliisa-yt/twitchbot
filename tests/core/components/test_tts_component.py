"""Unit tests for core.components.tts_component module."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.components.tts_component import TTSServiceComponent
from models.voice_models import TimeSignalParam, TTSParam


def _make_context(*, broadcaster: bool = True) -> MagicMock:
    context = MagicMock()
    author = MagicMock()
    author.name = "tester"
    author.broadcaster = broadcaster
    context.author = author
    context.send = AsyncMock()
    context.bot = MagicMock()
    return context


@pytest.fixture
def tts_bundle() -> SimpleNamespace:
    playback_manager = MagicMock()
    playback_manager.is_playing = False
    playback_manager.cancel_playback = AsyncMock()

    playback_queue = MagicMock()
    playback_queue.clear = AsyncMock()

    file_manager = MagicMock()

    tts_manager = MagicMock()
    tts_manager.playback_manager = playback_manager
    tts_manager.playback_queue = playback_queue
    tts_manager.file_manager = file_manager
    tts_manager.enqueue_tts_synthesis = AsyncMock()

    shared = MagicMock()
    shared.config = MagicMock()
    shared.trans_manager = MagicMock()
    shared.tts_manager = tts_manager

    bot = MagicMock()
    bot.shared_data = shared

    component = TTSServiceComponent(bot)

    return SimpleNamespace(
        component=component,
        playback_manager=playback_manager,
        playback_queue=playback_queue,
        file_manager=file_manager,
        tts_manager=tts_manager,
    )


@pytest.mark.asyncio
async def test_skip_cancels_playback_when_playing(tts_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    tts_bundle.playback_manager.is_playing = True

    await tts_bundle.component.skip.callback(tts_bundle.component, context)

    tts_bundle.playback_manager.cancel_playback.assert_called_once()
    context.send.assert_called_once_with("Current playback cancelled.")


@pytest.mark.asyncio
async def test_skip_does_nothing_when_not_playing(tts_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    tts_bundle.playback_manager.is_playing = False

    await tts_bundle.component.skip.callback(tts_bundle.component, context)

    tts_bundle.playback_manager.cancel_playback.assert_not_called()
    context.send.assert_called_once_with("No active playback to skip.")


# ---------------------------------------------------------------------------
# event_safe_tts_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_safe_tts_message_enqueues_when_content_returned(tts_bundle: SimpleNamespace) -> None:
    payload = TTSParam(content="hello", content_lang="ja")
    tts_bundle.tts_manager.prepare_tts_content.return_value = payload

    await tts_bundle.component.event_safe_tts_message(payload)

    tts_bundle.tts_manager.prepare_tts_content.assert_called_once_with(payload)
    tts_bundle.tts_manager.enqueue_tts_synthesis.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_event_safe_tts_message_skips_enqueue_when_content_is_none(tts_bundle: SimpleNamespace) -> None:
    payload = TTSParam(content="hello", content_lang="ja")
    tts_bundle.tts_manager.prepare_tts_content.return_value = None

    await tts_bundle.component.event_safe_tts_message(payload)

    tts_bundle.tts_manager.enqueue_tts_synthesis.assert_not_awaited()


# ---------------------------------------------------------------------------
# event_safe_time_signal_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_safe_time_signal_message_enqueues_when_content_returned(tts_bundle: SimpleNamespace) -> None:
    payload = TimeSignalParam(content="12:00 o'clock", content_lang="ja")
    voice_param = MagicMock()
    queue_data = TTSParam(content="12:00 o'clock", content_lang="ja")
    tts_bundle.tts_manager.get_voice_param.return_value = voice_param
    tts_bundle.tts_manager.prepare_tts_content.return_value = queue_data

    await tts_bundle.component.event_safe_time_signal_message(payload)

    tts_bundle.tts_manager.get_voice_param.assert_called_once_with("ja", is_system=True)
    called_arg: TTSParam = tts_bundle.tts_manager.prepare_tts_content.call_args[0][0]
    assert called_arg.content == payload.content
    assert called_arg.content_lang == payload.content_lang
    assert called_arg.tts_info is voice_param
    tts_bundle.tts_manager.enqueue_tts_synthesis.assert_awaited_once_with(queue_data)


@pytest.mark.asyncio
async def test_event_safe_time_signal_message_skips_enqueue_when_content_is_none(tts_bundle: SimpleNamespace) -> None:
    payload = TimeSignalParam(content="12:00 o'clock", content_lang="ja")
    tts_bundle.tts_manager.prepare_tts_content.return_value = None

    await tts_bundle.component.event_safe_time_signal_message(payload)

    tts_bundle.tts_manager.enqueue_tts_synthesis.assert_not_awaited()


# ---------------------------------------------------------------------------
# event_safe_tts_clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_safe_tts_clear_calls_queue_clear(tts_bundle: SimpleNamespace) -> None:
    await tts_bundle.component.event_safe_tts_clear()

    tts_bundle.playback_queue.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_safe_tts_clear_cancels_playback_when_playing(tts_bundle: SimpleNamespace) -> None:
    tts_bundle.playback_manager.is_playing = True

    await tts_bundle.component.event_safe_tts_clear()

    tts_bundle.playback_manager.cancel_playback.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_safe_tts_clear_does_not_cancel_when_not_playing(tts_bundle: SimpleNamespace) -> None:
    tts_bundle.playback_manager.is_playing = False

    await tts_bundle.component.event_safe_tts_clear()

    tts_bundle.playback_manager.cancel_playback.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_safe_tts_clear_callback_enqueues_deletion_when_filepath_set(tts_bundle: SimpleNamespace) -> None:
    await tts_bundle.component.event_safe_tts_clear()

    callback = tts_bundle.playback_queue.clear.call_args.kwargs["callback"]
    filepath = Path("audio.wav")
    tts_param = TTSParam(filepath=filepath)

    await callback(tts_param)

    tts_bundle.file_manager.enqueue_file_deletion.assert_called_once_with(filepath)


@pytest.mark.asyncio
async def test_event_safe_tts_clear_callback_skips_deletion_when_filepath_none(tts_bundle: SimpleNamespace) -> None:
    await tts_bundle.component.event_safe_tts_clear()

    callback = tts_bundle.playback_queue.clear.call_args.kwargs["callback"]
    tts_param = TTSParam(filepath=None)

    await callback(tts_param)

    tts_bundle.file_manager.enqueue_file_deletion.assert_not_called()

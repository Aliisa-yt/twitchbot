"""Unit tests for core.components.chat_events module."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.components.chat_events import ChatEventsManager
from models.message_models import ChatMessageDTO
from models.voice_models import TTSParam
from utils.excludable_queue import ExcludableQueue


def _make_cog_bundle() -> SimpleNamespace:
    playback_queue: ExcludableQueue[TTSParam] = ExcludableQueue()
    file_manager = MagicMock()
    playback_manager = MagicMock()
    playback_manager.cancel_playback = AsyncMock()

    tts_manager = MagicMock()
    tts_manager.playback_queue = playback_queue
    tts_manager.file_manager = file_manager
    tts_manager.playback_manager = playback_manager

    shared = MagicMock()
    shared.config = MagicMock()
    shared.trans_manager = MagicMock()
    shared.tts_manager = tts_manager

    bot = MagicMock()
    bot.shared_data = shared

    cog = ChatEventsManager(bot)

    return SimpleNamespace(
        cog=cog,
        playback_queue=playback_queue,
        file_manager=file_manager,
        playback_manager=playback_manager,
    )


@pytest.mark.asyncio
async def test_event_chat_clear_clears_queue_and_cancels_playback() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()

    bundle.playback_manager.is_playing = True

    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file1.wav")))
    await bundle.playback_queue.put(TTSParam(filepath=None))
    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file2.wav")))

    await bundle.cog.event_chat_clear(payload)

    assert bundle.playback_queue.empty()
    bundle.file_manager.enqueue_file_deletion.assert_any_call(Path("/tmp/file1.wav"))
    bundle.file_manager.enqueue_file_deletion.assert_any_call(Path("/tmp/file2.wav"))
    bundle.playback_manager.cancel_playback.assert_called_once()


@pytest.mark.asyncio
async def test_event_chat_clear_skips_cancel_when_not_playing() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()

    bundle.playback_manager.is_playing = False

    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file3.wav")))

    await bundle.cog.event_chat_clear(payload)

    assert bundle.playback_queue.empty()
    bundle.playback_manager.cancel_playback.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_message_drops_newest_on_overflow() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    bundle.cog._message_queue = ExcludableQueue(maxsize=2)

    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="1"))
    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="2"))
    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="3"))

    assert bundle.cog._message_queue.qsize() == 2

    first: ChatMessageDTO = bundle.cog._message_queue.get_nowait()
    second: ChatMessageDTO = bundle.cog._message_queue.get_nowait()
    bundle.cog._message_queue.task_done()
    bundle.cog._message_queue.task_done()

    assert [first.message_id, second.message_id] == ["1", "2"]

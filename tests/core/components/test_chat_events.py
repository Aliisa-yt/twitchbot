"""Unit tests for core.components.chat_events module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
    shared.config.TTS = MagicMock()
    shared.config.TTS.MAX_CONCURRENT_MESSAGES = 3
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
async def test_component_load_initializes_worker_and_semaphore() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    fake_task = MagicMock(spec=asyncio.Task)

    bundle.cog.shared.config.TTS.MAX_CONCURRENT_MESSAGES = 5

    with patch("core.components.chat_events.asyncio.create_task", return_value=fake_task) as mocked_create_task:
        await bundle.cog.component_load()

    assert bundle.cog._message_worker_task is fake_task
    assert bundle.cog._concurrency_sem is not None
    assert bundle.cog._concurrency_sem._value == 5
    mocked_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_component_load_uses_default_on_invalid_concurrency() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    fake_task = MagicMock(spec=asyncio.Task)

    bundle.cog.shared.config.TTS.MAX_CONCURRENT_MESSAGES = "invalid"

    with patch("core.components.chat_events.asyncio.create_task", return_value=fake_task):
        await bundle.cog.component_load()

    assert bundle.cog._concurrency_sem is not None
    assert bundle.cog._concurrency_sem._value == 3


@pytest.mark.asyncio
async def test_component_teardown_cancels_worker_and_spawned_tasks() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()

    bundle.cog._message_worker_task = asyncio.create_task(asyncio.sleep(10))
    spawned_task = asyncio.create_task(asyncio.sleep(10))
    bundle.cog._spawned_tasks.add(spawned_task)
    bundle.cog._concurrency_sem = asyncio.Semaphore(2)

    await bundle.cog.component_teardown()

    assert bundle.cog._message_worker_task is None
    assert bundle.cog._spawned_tasks == set()
    assert bundle.cog._concurrency_sem is None
    assert spawned_task.cancelled()


@pytest.mark.asyncio
async def test_event_message_skips_enqueue_when_ignored() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()

    bundle.cog._should_ignore_message = MagicMock(return_value=True)
    bundle.cog._enqueue_message = AsyncMock()

    await bundle.cog.event_message(payload)

    bundle.cog._enqueue_message.assert_not_called()


@pytest.mark.asyncio
async def test_event_message_enqueues_dto_when_not_ignored() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()
    dto = ChatMessageDTO(message_id="msg-1")

    bundle.cog._should_ignore_message = MagicMock(return_value=False)
    bundle.cog._enqueue_message = AsyncMock()

    with patch("core.components.chat_events.ChatMessageDTO.from_twitch_message", return_value=dto) as from_twitch:
        await bundle.cog.event_message(payload)

    from_twitch.assert_called_once_with(payload)
    bundle.cog._enqueue_message.assert_awaited_once_with(dto)


@pytest.mark.asyncio
async def test_handle_message_task_calls_task_done_on_handler_error() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    dto = ChatMessageDTO(message_id="msg-2")

    bundle.cog._concurrency_sem = asyncio.Semaphore(1)
    bundle.cog._handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    bundle.cog._message_queue.task_done = MagicMock()

    await bundle.cog._handle_message_task(dto)

    bundle.cog._message_queue.task_done.assert_called_once()


@pytest.mark.asyncio
async def test_task_done_callback_discards_task_and_logs_exception() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()

    async def _raise_error() -> None:
        msg = "task error"
        raise RuntimeError(msg)

    task = asyncio.create_task(_raise_error())
    with pytest.raises(RuntimeError):
        await task

    bundle.cog._spawned_tasks.add(task)

    with patch("core.components.chat_events.logger.error") as mocked_logger:
        bundle.cog._task_done_callback(task)

    assert task not in bundle.cog._spawned_tasks
    mocked_logger.assert_called_once()


@pytest.mark.asyncio
async def test_message_worker_loop_spawns_task_for_each_dto() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    dto = ChatMessageDTO(message_id="msg-3")
    fake_task = MagicMock(spec=asyncio.Task)

    bundle.cog._message_queue.get = AsyncMock(side_effect=[dto, asyncio.CancelledError()])

    with patch("core.components.chat_events.asyncio.create_task", return_value=fake_task) as mocked_create_task:
        with pytest.raises(asyncio.CancelledError):
            await bundle.cog._message_worker_loop()

    mocked_create_task.assert_called_once()
    assert fake_task in bundle.cog._spawned_tasks
    fake_task.add_done_callback.assert_called_once()


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

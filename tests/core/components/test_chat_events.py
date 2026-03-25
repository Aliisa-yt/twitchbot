"""Unit tests for core.components.chat_events module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.chat_events import ChatEventsManager
from models.message_models import ChatMessageDTO
from models.translation_models import TranslationInfo
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
        bundle.cog._ensure_message_worker_running()

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

    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    bundle.cog._handle_message = AsyncMock(side_effect=RuntimeError("boom"))
    bundle.cog._message_queue.task_done = MagicMock()

    await bundle.cog._handle_message_task(dto, semaphore)

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

    bundle.cog._concurrency_sem = asyncio.Semaphore(1)
    bundle.cog._message_queue.get = AsyncMock(side_effect=[dto, asyncio.CancelledError()])

    with (
        patch("core.components.chat_events.asyncio.create_task", return_value=fake_task) as mocked_create_task,
        pytest.raises(asyncio.CancelledError),
    ):
        await bundle.cog._message_worker_loop()

    mocked_create_task.assert_called_once()
    assert fake_task in bundle.cog._spawned_tasks
    fake_task.add_done_callback.assert_called_once()


@pytest.mark.asyncio
async def test_enqueue_message_drops_when_component_unavailable() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    dto = ChatMessageDTO(message_id="msg-unavailable")

    bundle.cog._is_available = False
    bundle.cog._ensure_message_worker_running = MagicMock(return_value=True)

    await bundle.cog._enqueue_message(dto)

    assert bundle.cog._message_queue.empty()
    bundle.cog._ensure_message_worker_running.assert_not_called()


@pytest.mark.asyncio
async def test_message_worker_loop_drops_message_when_semaphore_not_initialized() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    dto = ChatMessageDTO(message_id="msg-no-semaphore")

    bundle.cog._concurrency_sem = None
    bundle.cog._message_queue.get = AsyncMock(side_effect=[dto, asyncio.CancelledError()])
    bundle.cog._message_queue.task_done = MagicMock()

    with (
        patch("core.components.chat_events.asyncio.create_task") as mocked_create_task,
        patch("core.components.chat_events.logger.error") as mocked_logger,
        pytest.raises(asyncio.CancelledError),
    ):
        await bundle.cog._message_worker_loop()

    mocked_create_task.assert_not_called()
    bundle.cog._message_queue.task_done.assert_called_once()
    mocked_logger.assert_called_once()


@pytest.mark.asyncio
async def test_event_chat_clear_clears_message_queue_and_dispatches_tts_clear() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()

    bundle.playback_manager.is_playing = True

    await bundle.cog._message_queue.put(ChatMessageDTO(message_id="clear-target"))

    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file1.wav")))
    await bundle.playback_queue.put(TTSParam(filepath=None))
    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file2.wav")))

    await bundle.cog.event_chat_clear(payload)

    assert bundle.cog._message_queue.empty()
    assert bundle.playback_queue.qsize() == 3
    bundle.cog.bot.safe_dispatch.assert_called_once_with("tts_clear")
    bundle.file_manager.enqueue_file_deletion.assert_not_called()
    bundle.playback_manager.cancel_playback.assert_not_called()


@pytest.mark.asyncio
async def test_event_chat_clear_dispatches_tts_clear_without_direct_cancel_when_not_playing() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    payload = MagicMock()

    bundle.playback_manager.is_playing = False

    await bundle.playback_queue.put(TTSParam(filepath=Path("/tmp/file3.wav")))

    await bundle.cog.event_chat_clear(payload)

    assert bundle.playback_queue.qsize() == 1
    bundle.cog.bot.safe_dispatch.assert_called_once_with("tts_clear")
    bundle.playback_manager.cancel_playback.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_message_drops_newest_on_overflow() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    bundle.cog._message_queue = ExcludableQueue(maxsize=2)
    await bundle.cog.component_load()

    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="1"))
    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="2"))
    await bundle.cog._enqueue_message(ChatMessageDTO(message_id="3"))

    assert bundle.cog._message_queue.qsize() == 2

    first: ChatMessageDTO = bundle.cog._message_queue.get_nowait()
    second: ChatMessageDTO = bundle.cog._message_queue.get_nowait()
    bundle.cog._message_queue.task_done()
    bundle.cog._message_queue.task_done()

    assert [first.message_id, second.message_id] == ["1", "2"]


@pytest.mark.asyncio
async def test_enqueue_message_processes_all_under_burst() -> None:
    bundle: SimpleNamespace = _make_cog_bundle()
    bundle.cog._handle_message = AsyncMock(return_value=None)

    await bundle.cog.component_load()

    for i in range(15):
        await bundle.cog._enqueue_message(ChatMessageDTO(message_id=f"burst-{i}"))

    await asyncio.wait_for(bundle.cog._message_queue.join(), timeout=2.0)

    assert bundle.cog._handle_message.await_count == 15
    assert bundle.cog._message_queue.empty()

    await bundle.cog.component_teardown()


# ---------------------------------------------------------------------------
# _handle_message branch coverage
# ---------------------------------------------------------------------------


def _setup_handle_message_mocks(cog: ChatEventsManager) -> SimpleNamespace:
    """Patch _handle_message dependencies and return the mocks as a SimpleNamespace."""
    message = MagicMock()
    message.content = "hello"
    message.emote.has_valid_emotes = False

    trans_info = TranslationInfo(content="hello")

    cog._preprocess_message = MagicMock(return_value=message)
    cog.prepare_translate_parameters = MagicMock(return_value=trans_info)
    cog.trans_manager.refresh_active_engine_list = MagicMock()
    cog.trans_manager.detect_language = AsyncMock(return_value=True)
    cog.trans_manager.determine_target_language = MagicMock(return_value=True)
    cog.trans_manager.perform_translation = AsyncMock(return_value=True)
    cog._process_original_tts = AsyncMock()
    cog._process_translated_tts = AsyncMock()
    cog._output_and_send_translation = AsyncMock()

    return SimpleNamespace(message=message, trans_info=trans_info)


@pytest.mark.asyncio
async def test_handle_message_skips_when_detect_language_fails_and_no_emotes() -> None:
    """When detect_language returns False and no valid emotes, processing stops early."""
    bundle = _make_cog_bundle()
    mocks = _setup_handle_message_mocks(bundle.cog)
    mocks.trans_info.src_lang = None
    bundle.cog.trans_manager.detect_language = AsyncMock(return_value=False)
    mocks.message.emote.has_valid_emotes = False

    with patch("core.components.chat_events.TransManager.parse_language_prefix"):
        await bundle.cog._handle_message(ChatMessageDTO(message_id="m1"))

    bundle.cog._process_original_tts.assert_not_called()
    bundle.cog.trans_manager.determine_target_language.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_continues_with_default_langs_when_emotes_only() -> None:
    """When detect_language returns False but valid emotes exist, default langs are set and processing continues."""
    bundle = _make_cog_bundle()
    mocks = _setup_handle_message_mocks(bundle.cog)
    mocks.trans_info.src_lang = None
    bundle.cog.trans_manager.detect_language = AsyncMock(return_value=False)
    mocks.message.emote.has_valid_emotes = True
    bundle.cog.shared.config.TRANSLATION = MagicMock()
    bundle.cog.shared.config.TRANSLATION.NATIVE_LANGUAGE = "ja"
    bundle.cog.shared.config.TRANSLATION.SECOND_LANGUAGE = "en"

    with patch("core.components.chat_events.TransManager.parse_language_prefix"):
        await bundle.cog._handle_message(ChatMessageDTO(message_id="m2"))

    assert mocks.trans_info.src_lang == "ja"
    assert mocks.trans_info.tgt_lang == "en"
    bundle.cog._process_original_tts.assert_awaited_once()
    bundle.cog.trans_manager.determine_target_language.assert_called_once()


@pytest.mark.asyncio
async def test_handle_message_skips_translation_when_no_target_language() -> None:
    """When determine_target_language returns False, translation and subsequent TTS are skipped."""
    bundle = _make_cog_bundle()
    _setup_handle_message_mocks(bundle.cog)
    bundle.cog.trans_manager.detect_language = AsyncMock(return_value=True)
    bundle.cog.trans_manager.determine_target_language = MagicMock(return_value=False)

    with patch("core.components.chat_events.TransManager.parse_language_prefix"):
        await bundle.cog._handle_message(ChatMessageDTO(message_id="m3"))

    bundle.cog._process_original_tts.assert_awaited_once()
    bundle.cog.trans_manager.perform_translation.assert_not_called()
    bundle.cog._process_translated_tts.assert_not_called()


@pytest.mark.asyncio
async def test_handle_message_skips_tts_when_translation_fails() -> None:
    """When perform_translation returns False, translated TTS and output are skipped."""
    bundle = _make_cog_bundle()
    _setup_handle_message_mocks(bundle.cog)
    bundle.cog.trans_manager.detect_language = AsyncMock(return_value=True)
    bundle.cog.trans_manager.determine_target_language = MagicMock(return_value=True)
    bundle.cog.trans_manager.perform_translation = AsyncMock(return_value=False)

    with patch("core.components.chat_events.TransManager.parse_language_prefix"):
        await bundle.cog._handle_message(ChatMessageDTO(message_id="m4"))

    bundle.cog._process_original_tts.assert_awaited_once()
    bundle.cog._process_translated_tts.assert_not_called()
    bundle.cog._output_and_send_translation.assert_not_called()

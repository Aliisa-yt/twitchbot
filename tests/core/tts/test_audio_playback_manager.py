"""Unit tests for core.tts.audio_playback_manager module."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast
from unittest.mock import MagicMock

import numpy as np
import pytest

from core.tts import audio_playback_manager as apm
from core.tts.audio_playback_manager import AudioPlaybackManager
from models.voice_models import TTSParam

if TYPE_CHECKING:
    from config.loader import Config
    from utils.excludable_queue import ExcludableQueue


def _make_config(limit_time: str = "2.5") -> Config:
    return cast("Config", SimpleNamespace(TTS=SimpleNamespace(LIMIT_TIME=limit_time)))


@pytest.fixture
def manager() -> AudioPlaybackManager:
    config: apm.Config = _make_config()
    file_manager = MagicMock()
    playback_queue = MagicMock()
    return AudioPlaybackManager(config, file_manager, playback_queue, asyncio.Event())


def test_get_timelimit_valid(manager: AudioPlaybackManager) -> None:
    assert manager._get_timelimit() == 2.5


def test_get_timelimit_invalid(manager: AudioPlaybackManager) -> None:
    manager.config.TTS.LIMIT_TIME = "not-a-number"  # type: ignore  # noqa: PGH003
    assert manager._get_timelimit() is None


@pytest.mark.asyncio
async def test_cancel_playback_sets_event_and_cancels_task(manager: AudioPlaybackManager) -> None:
    manager.cancel_playback_event = asyncio.Event()
    manager.play_task = asyncio.create_task(asyncio.sleep(10))

    await manager.cancel_playback()

    assert manager.cancel_playback_event.is_set()
    assert manager.play_task.cancelled() or manager.play_task.done()


def test_is_playing_false_when_stream_none(manager: AudioPlaybackManager) -> None:
    manager.stream = None
    assert manager.is_playing is False


def test_is_playing_true_when_stream_active(manager: AudioPlaybackManager) -> None:
    stream = MagicMock()
    stream.active = True
    manager.stream = stream
    assert manager.is_playing is True


def test_release_audio_resources_closes_stream(manager: AudioPlaybackManager) -> None:
    mock_stream = MagicMock()
    manager.stream = mock_stream

    manager.release_audio_resources()

    mock_stream.stop.assert_called_once()
    mock_stream.close.assert_called_once()
    assert manager.stream is None


def test_stream_callback_logic_aborts_on_terminate_event() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = True
    cancel_playback_event = MagicMock()
    outdata = np.ones((256, 1), dtype=np.int16)

    action = apm._stream_callback_logic(
        outdata,
        256,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert action == apm._CallbackAction.ABORT
    assert np.all(outdata == 0)
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


def test_stream_callback_logic_completes_on_short_read() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = False
    cancel_playback_event = MagicMock()
    outdata = np.zeros((256, 1), dtype=np.int16)

    data = np.ones((128, 1), dtype=np.int16)
    sf.read.return_value = data

    action = apm._stream_callback_logic(
        outdata,
        256,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert action == apm._CallbackAction.STOP
    assert np.all(outdata[:128] == 1)
    assert np.all(outdata[128:] == 0)
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


def test_stream_callback_logic_aborts_on_soundfile_error() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = False
    cancel_playback_event = MagicMock()
    outdata = np.ones((256, 1), dtype=np.int16)
    sf.read.side_effect = apm.soundfile.SoundFileRuntimeError("fail")

    action = apm._stream_callback_logic(
        outdata,
        256,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert action == apm._CallbackAction.ABORT
    assert np.all(outdata == 0)
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


@pytest.mark.asyncio
async def test_playback_queue_processor_skips_invalid_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _ = monkeypatch
    config: apm.Config = _make_config("0")
    file_manager = MagicMock()

    class FakeQueue:
        def __init__(self) -> None:
            self._items: list[TTSParam] = [TTSParam(filepath=None)]
            self._task_done_mock = MagicMock()

        async def get(self) -> TTSParam:
            if not self._items:
                raise asyncio.QueueShutDown
            return self._items.pop(0)

        def task_done(self) -> None:
            self._task_done_mock()

    playback_queue = FakeQueue()
    manager = AudioPlaybackManager(
        config, file_manager, cast("ExcludableQueue[TTSParam]", playback_queue), asyncio.Event()
    )
    manager.release_audio_resources = MagicMock()

    await manager.playback_queue_processor()

    playback_queue._task_done_mock.assert_called_once()
    manager.release_audio_resources.assert_called_once()


@pytest.mark.asyncio
async def test_play_sounddevice_enqueues_deletion_on_unsupported_format(manager: AudioPlaybackManager) -> None:
    class FakeSoundFile:
        subtype: str = "PCM_24"
        channels: int = 1
        samplerate: int = 16000

        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    original_soundfile = apm.soundfile.SoundFile
    apm.soundfile.SoundFile = lambda _: FakeSoundFile()  # type: ignore[method-assign]

    try:
        file_path = Path("dummy.wav")
        await manager._play_sounddevice(file_path, asyncio.Event())
    finally:
        apm.soundfile.SoundFile = original_soundfile  # type: ignore[assignment]

    cast("MagicMock", manager.file_manager).enqueue_file_deletion.assert_called_once_with(file_path)


@pytest.mark.asyncio
async def test_cancel_playback_skips_done_task(manager: AudioPlaybackManager) -> None:
    task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
    await task  # ensure task completes naturally
    manager.play_task = task
    assert task.done()

    await manager.cancel_playback()

    assert manager.cancel_playback_event.is_set()


def test_is_playing_false_when_stream_inactive(manager: AudioPlaybackManager) -> None:
    stream = MagicMock()
    stream.active = False
    manager.stream = stream
    assert manager.is_playing is False


def test_open_output_stream_returns_false_on_exception(
    manager: AudioPlaybackManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(apm.sounddevice, "OutputStream", MagicMock(side_effect=Exception("open fail")))
    sf = MagicMock()
    sf.samplerate = 44100
    sf.channels = 1
    result = manager._open_output_stream(sf, "int16", 2048, MagicMock())
    assert result is False


@pytest.mark.asyncio
async def test_playback_queue_processor_cancel_propagates(
    manager: AudioPlaybackManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """External task cancellation propagates immediately (regression for review item 1)."""
    play_started: asyncio.Event = asyncio.Event()

    async def slow_play(_file_path: Path, _terminate_event: asyncio.Event) -> None:
        play_started.set()
        await asyncio.sleep(100)

    monkeypatch.setattr(manager, "_play_sounddevice", slow_play)
    monkeypatch.setattr(apm.FileUtils, "validate_file_path", MagicMock())

    class FakeQueue:
        def __init__(self) -> None:
            self._sent = False

        async def get(self) -> TTSParam:
            if not self._sent:
                self._sent = True
                return TTSParam(filepath=Path("test.wav"))
            await asyncio.sleep(100)
            raise AssertionError

        def task_done(self) -> None:
            pass

    manager.playback_queue = cast("ExcludableQueue[TTSParam]", FakeQueue())
    outer_task: asyncio.Task[None] = asyncio.create_task(manager.playback_queue_processor())
    await play_started.wait()
    inner_play_task = manager.play_task
    outer_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await outer_task

    if inner_play_task and not inner_play_task.done():
        inner_play_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await inner_play_task


@pytest.mark.asyncio
async def test_play_sounddevice_enqueues_deletion_on_cancelled(
    manager: AudioPlaybackManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deletion is enqueued even when _play_sounddevice is cancelled via CancelledError."""

    class FakeSoundFile:
        subtype: str = "PCM_16"
        channels: int = 1
        samplerate: int = 16000

        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            pass

    monkeypatch.setattr(apm.soundfile, "SoundFile", lambda _: FakeSoundFile())
    monkeypatch.setattr(apm.sounddevice, "OutputStream", MagicMock(return_value=MagicMock()))

    file_path = Path("cancel_test.wav")
    task: asyncio.Task[None] = asyncio.create_task(manager._play_sounddevice(file_path, asyncio.Event()))
    await asyncio.sleep(0)  # advance to cancel_playback_event.wait()
    task.cancel()
    await task  # CancelledError is absorbed by _play_sounddevice

    cast("MagicMock", manager.file_manager).enqueue_file_deletion.assert_called_once_with(file_path)

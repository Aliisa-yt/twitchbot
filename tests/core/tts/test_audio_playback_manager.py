"""Unit tests for core.tts.audio_playback_manager module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Self, cast
from unittest.mock import MagicMock

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
def manager(monkeypatch: pytest.MonkeyPatch) -> AudioPlaybackManager:
    monkeypatch.setattr(apm.pyaudio, "PyAudio", MagicMock)
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
    stream.is_active.return_value = True
    manager.stream = stream
    assert manager.is_playing is True


def test_release_pyaudio_terminates(manager: AudioPlaybackManager) -> None:
    mock_pyaudio = MagicMock()
    manager._pyaudio = mock_pyaudio

    manager.release_pyaudio()

    mock_pyaudio.terminate.assert_called_once()
    assert manager._pyaudio is None


def test_pyaudio_property_recreates_instance(monkeypatch: pytest.MonkeyPatch, manager: AudioPlaybackManager) -> None:
    created = MagicMock()
    monkeypatch.setattr(apm.pyaudio, "PyAudio", MagicMock(return_value=created))
    manager._pyaudio = None

    assert manager.pyaudio is created


def test_stream_callback_logic_aborts_on_terminate_event() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = True
    cancel_playback_event = MagicMock()

    data, status = apm._stream_callback_logic(
        None,
        256,
        None,
        None,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert data is None
    assert status == apm.pyaudio.paAbort
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


def test_stream_callback_logic_completes_on_short_read() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = False
    cancel_playback_event = MagicMock()

    data = MagicMock()
    data.shape = (128,)
    data.tobytes.return_value = b"data"
    sf.read.return_value = data

    result_data, status = apm._stream_callback_logic(
        None,
        256,
        None,
        None,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert result_data == b"data"
    assert status == apm.pyaudio.paComplete
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


def test_stream_callback_logic_aborts_on_soundfile_error() -> None:
    sf = MagicMock()
    loop = MagicMock()
    terminate_event = MagicMock()
    terminate_event.is_set.return_value = False
    cancel_playback_event = MagicMock()
    sf.read.side_effect = apm.soundfile.SoundFileRuntimeError("fail")

    data, status = apm._stream_callback_logic(
        None,
        256,
        None,
        None,
        sf=sf,
        dtype="int16",
        loop=loop,
        terminate_event=terminate_event,
        cancel_playback_event=cancel_playback_event,
    )

    assert data is None
    assert status == apm.pyaudio.paAbort
    loop.call_soon_threadsafe.assert_called_once_with(cancel_playback_event.set)


@pytest.mark.asyncio
async def test_playback_queue_processor_skips_invalid_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apm.pyaudio, "PyAudio", MagicMock)
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
    manager.release_pyaudio = MagicMock()

    await manager.playback_queue_processor()

    playback_queue._task_done_mock.assert_called_once()
    manager.release_pyaudio.assert_called_once()


@pytest.mark.asyncio
async def test_play_pyaudio_enqueues_deletion_on_unsupported_format(
    monkeypatch: pytest.MonkeyPatch, manager: AudioPlaybackManager
) -> None:
    class FakeSoundFile:
        subtype: str = "PCM_24"
        channels: int = 1
        samplerate: int = 16000

        def __enter__(self) -> Self:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(apm.soundfile, "SoundFile", lambda _: FakeSoundFile())

    file_path = Path("dummy.wav")
    await manager._play_pyaudio(file_path, asyncio.Event())

    cast("MagicMock", manager.file_manager).enqueue_file_deletion.assert_called_once_with(file_path)

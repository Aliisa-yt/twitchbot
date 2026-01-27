import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, Self
from unittest.mock import MagicMock

import pyaudio
import pytest

from core.tts.audio_playback_manager import FORMAT_CONV, AudioPlaybackManager, _stream_callback_logic

if TYPE_CHECKING:
    from collections.abc import Callable

# Patch sys.modules so imports work even if dependencies are missing
# sys.modules["pyaudio"] = MagicMock()
# sys.modules["soundfile"] = MagicMock()
# sys.modules["handlers.voice_models"] = MagicMock()
# sys.modules["config.loader"] = MagicMock()
# sys.modules["utils.excludable_queue"] = MagicMock()


@pytest.fixture
def fake_config():
    class _TTS:
        LIMIT_TIME = "2.5"

    class Config:
        TTS = _TTS()

    return Config()


@pytest.fixture
def fake_tts_param(tmp_path: Path):
    # Simulate TTSParam with a .wav file path
    class FakeTTSParam:
        def __init__(self, filepath) -> None:
            self.filepath = filepath

    wav_file: Path = tmp_path / "test.wav"
    wav_file.write_bytes(b"RIFF....WAVEfmt ")  # Not a real wav, but enough for path testing
    return FakeTTSParam(wav_file)


@pytest.fixture
def fake_queue():
    # Minimal async queue mock
    class FakeQueue:
        def __init__(self) -> None:
            self._items = asyncio.Queue()

        async def get(self):
            return await self._items.get()

        def task_done(self) -> None:
            pass

        async def put(self, item) -> None:
            await self._items.put(item)

    return FakeQueue()


@pytest.fixture
def playback_manager(fake_config, fake_queue) -> AudioPlaybackManager:
    return AudioPlaybackManager(fake_config, fake_queue, asyncio.Event())


def test_get_valid_file_path_accepts_wav(playback_manager, fake_tts_param) -> None:
    path = playback_manager._get_valid_file_path(fake_tts_param)
    assert path is not None
    assert str(path).endswith(".wav")


def test_get_valid_file_path_rejects_nonwav(playback_manager, tmp_path) -> None:
    class FakeTTSParam:
        def __init__(self, filepath) -> None:
            self.filepath = filepath

    fake_param = FakeTTSParam(tmp_path / "test.mp3")
    assert playback_manager._get_valid_file_path(fake_param) is None


def test_get_valid_file_path_none(playback_manager) -> None:
    class FakeTTSParam:
        filepath = None

    assert playback_manager._get_valid_file_path(FakeTTSParam()) is None


def test_get_timelimit_valid(playback_manager) -> None:
    assert playback_manager._get_timelimit() == 2.5


def test_get_timelimit_invalid(playback_manager) -> None:
    playback_manager.config.TTS.LIMIT_TIME = "not_a_number"
    assert playback_manager._get_timelimit() is None


@pytest.mark.asyncio
async def test_cancel_playback_sets_event(playback_manager) -> None:
    playback_manager.cancel_playback_event = asyncio.Event()
    playback_manager.play_task = None
    await playback_manager.cancel_playback()
    assert playback_manager.cancel_playback_event.is_set()


@pytest.mark.asyncio
async def test_cancel_playback_cancels_task(playback_manager) -> None:
    # Simulate a running task
    async def dummy() -> None:
        await asyncio.sleep(1)

    task = asyncio.create_task(dummy())
    playback_manager.play_task = task
    await playback_manager.cancel_playback()
    assert task.cancelled() or task.done()


def test_is_playing_false_when_stream_none(playback_manager) -> None:
    playback_manager.stream = None
    assert playback_manager.is_playing is False


def test_is_playing_true_when_stream_active(playback_manager) -> None:
    mock_stream = MagicMock()
    mock_stream.is_active.return_value = True
    playback_manager.stream = mock_stream
    assert playback_manager.is_playing is True


def test_is_playing_false_when_stream_inactive(playback_manager) -> None:
    mock_stream = MagicMock()
    mock_stream.is_active.return_value = False
    playback_manager.stream = mock_stream
    assert playback_manager.is_playing is False


def test_pyaudio_property_recreates_instance(playback_manager) -> None:
    playback_manager._pyaudio = None
    pa = playback_manager.pyaudio
    assert pa is not None


def test_release_pyaudio(playback_manager) -> None:
    mock_pyaudio = MagicMock()
    playback_manager._pyaudio = mock_pyaudio
    playback_manager.release_pyaudio()
    assert playback_manager._pyaudio is None
    mock_pyaudio.terminate.assert_called_once()


def test_format_conv_keys() -> None:
    # Ensure all keys in _format_conv are valid
    for k, v in FORMAT_CONV.items():
        assert isinstance(k, str)
        assert isinstance(v, tuple)
        assert len(v) == 2


def test_stream_callback_logic_finished_event_sets_cancel() -> None:
    # Setup
    sf = MagicMock()
    dtype = "int16"
    loop = MagicMock()
    finished_event = MagicMock()
    cancel_playback_event = MagicMock()
    finished_event.is_set.return_value = True
    # Call
    result = _stream_callback_logic(
        None,
        1024,
        None,
        None,
        sf=sf,
        dtype=dtype,
        loop=loop,
        terminate_event=finished_event,
        cancel_playback_event=cancel_playback_event,
    )
    # assert result[1] == sys.modules["pyaudio"].paAbort
    assert result[1] == pyaudio.paAbort


def test_stream_callback_logic_reads_data() -> None:
    sf = MagicMock()
    dtype = "int16"
    loop = MagicMock()
    finished_event = MagicMock()
    cancel_playback_event = MagicMock()
    finished_event.is_set.return_value = False
    data = MagicMock()
    data.shape = (1024,)
    data.tobytes.return_value = b"abc"
    sf.read.return_value = data
    result = _stream_callback_logic(
        None,
        1024,
        None,
        None,
        sf=sf,
        dtype=dtype,
        loop=loop,
        terminate_event=finished_event,
        cancel_playback_event=cancel_playback_event,
    )
    assert result[0] == b"abc"


@pytest.mark.asyncio
async def test_file_deletion_worker_retries_and_deletes(tmp_path, fake_config) -> None:
    # Arrange: manager with its own deletion worker
    pm = AudioPlaybackManager(fake_config, MagicMock(), asyncio.Event())

    # Prepare dummy path
    f: Path = tmp_path / "to_delete.wav"
    f.write_bytes(b"x")

    # Monkeypatch Path.unlink to raise PermissionError first two times for this path
    call_counts: dict[str, int] = {str(f): 0}
    original_unlink: Callable[..., None] = Path.unlink

    def fake_unlink(self: Path, *args, **kwargs) -> None:  # type: ignore[override]
        if str(self) == str(f):
            cnt: int = call_counts[str(self)]
            call_counts[str(self)] = cnt + 1
            if cnt < 2:
                msg = "locked"
                raise PermissionError(msg)
        return original_unlink(self, *args, **kwargs)

    # Patch
    import pathlib as _pathlib  # local import to avoid global name confusion

    _orig_path_unlink: Callable[..., None] = _pathlib.Path.unlink
    _pathlib.Path.unlink = fake_unlink  # type: ignore[assignment]

    # Start worker
    deletion_task: asyncio.Task[None] = asyncio.create_task(pm._file_deletion_worker())
    try:
        # Enqueue file for deletion
        pm._deletion_queue.put_nowait(f)
        # Wait a bit for retries to occur
        # 2 failures * 0.5s delay + margins
        await asyncio.sleep(1.2)
        # Ensure file is deleted and retried at least twice
        assert not f.exists()
        assert call_counts[str(f)] >= 2
    finally:
        deletion_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await deletion_task
        # Restore monkeypatch
        _pathlib.Path.unlink = _orig_path_unlink  # type: ignore[assignment]


@pytest.mark.asyncio
async def test__play_pyaudio_enqueues_file_and_clears_stream(tmp_path, fake_config) -> None:
    # Arrange
    pm = AudioPlaybackManager(fake_config, MagicMock(), asyncio.Event())

    # Dummy SoundFile context manager
    class DummySF:
        def __init__(self, _path) -> None:
            self.subtype = "PCM_16"
            self.samplerate = 16000
            self.channels = 1

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_) -> Literal[False]:
            return False

    # Dummy PyAudio stream that immediately triggers cancel event when started
    class DummyStream:
        def __init__(self, on_start) -> None:
            self._on_start = on_start

        def start_stream(self) -> None:
            # signal playback end immediately
            self._on_start()

        def stop_stream(self) -> None:
            pass

        def close(self) -> None:
            pass

    class DummyPA:
        def open(self, **_kwargs) -> DummyStream:
            # Provide a stream whose start sets the cancel event
            return DummyStream(on_start=pm.cancel_playback_event.set)

    # Patch dependencies
    import core.tts.audio_playback_manager as apm_mod

    _orig_sf = apm_mod.soundfile.SoundFile
    apm_mod.soundfile.SoundFile = DummySF  # type: ignore[assignment]
    pm._pyaudio = DummyPA()  # type: ignore[assignment]

    try:
        # Use a temp path (does not need to be a real wav since DummySF ignores content)
        f = tmp_path / "x.wav"
        f.write_bytes(b"x")
        await pm._play_pyaudio(f, asyncio.Event())

        # Assert stream cleared and file enqueued for deletion
        assert pm.stream is None
        queued: Path = await pm._deletion_queue.get()
        assert queued == f
    finally:
        apm_mod.soundfile.SoundFile = _orig_sf  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_play_voicefile_task_timeout_clears_play_task(tmp_path) -> None:
    # Config with very short timeout
    cfg: Any = SimpleNamespace(TTS=SimpleNamespace(LIMIT_TIME="0.1"))

    # Minimal playback queue that our manager expects
    class MiniQ:
        def __init__(self) -> None:
            self._q = asyncio.Queue()

        async def get(self):
            return await self._q.get()

        async def put(self, item):
            await self._q.put(item)

        def task_done(self) -> None:
            pass

    q: Any = MiniQ()
    pm = AudioPlaybackManager(cfg, q, asyncio.Event())

    # Mock _play_pyaudio to simulate long-running playback
    async def slow_play(_path, _evt):
        await asyncio.sleep(5)

    pm._play_pyaudio = slow_play  # type: ignore[method-assign]

    # Enqueue a TTSParam-like with valid wav path
    class P:
        def __init__(self, p: Path) -> None:
            self.filepath = p

    wav = tmp_path / "ok.wav"
    wav.write_bytes(b"RIFF..WAVE")
    await q.put(P(wav))

    # Run the task and allow it to process one item, then cancel the loop
    task = asyncio.create_task(pm.playback_queue_processor())
    try:
        await asyncio.sleep(0.3)
        # After timeout, play_task should have been cleared
        assert pm.play_task is None
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

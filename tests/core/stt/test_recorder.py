from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest

from core.stt.recorder import SegmentMode, STTLevelEvent, STTRecorder, STTSegment

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _FakeInputStream:
    def __init__(
        self,
        *,
        samplerate: int,
        channels: int,
        dtype: str,
        device: str | int | None,
        callback: Callable,
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.callback = callback
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_start_input_monitoring_applies_device_rate_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=22050,
        channels=1,
        input_device="default",
        level_interval_ms=10,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    event_received = asyncio.Event()
    received_level: list[STTLevelEvent] = []

    async def on_level(event: STTLevelEvent) -> None:
        received_level.append(event)
        event_received.set()

    await recorder.start_input_monitoring(on_level_event=on_level)

    assert recorder.is_monitoring is True
    assert len(created_streams) == 1
    stream = created_streams[0]
    assert stream.started is True
    assert stream.samplerate == 22050
    assert stream.channels == 1
    assert stream.device is None

    indata = np.array([[1000], [-1000], [500]], dtype=np.int16)
    stream.callback(indata, len(indata), None, 0)

    await asyncio.wait_for(event_received.wait(), timeout=1.0)
    assert received_level
    assert 0.0 <= received_level[0].rms <= 1.0
    assert received_level[0].muted is False

    await recorder.stop_input_monitoring()
    assert stream.stopped is True
    assert stream.closed is True
    assert recorder.is_monitoring is False


@pytest.mark.asyncio
async def test_input_monitoring_emits_muted_level(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="2",
        level_interval_ms=10,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    event_received = asyncio.Event()
    received_level: list[STTLevelEvent] = []

    def on_level(event: STTLevelEvent) -> None:
        received_level.append(event)
        event_received.set()

    recorder.set_mute(mute=True)
    await recorder.start_input_monitoring(on_level_event=on_level)

    stream = created_streams[0]
    assert stream.device == 2

    indata = np.array([[20000], [18000], [-19000]], dtype=np.int16)
    stream.callback(indata, len(indata), None, 0)

    await asyncio.wait_for(event_received.wait(), timeout=1.0)
    assert received_level
    assert received_level[0].muted is True
    assert received_level[0].rms == 0.0

    await recorder.close()


@pytest.mark.asyncio
async def test_threshold_segmentation_queues_pcm_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
        start_level_db=-34.0,
        stop_level_db=-40.0,
        pre_buffer_ms=100,
        post_buffer_ms=20,
        max_segment_sec=10,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    await recorder.start_input_monitoring()
    stream = created_streams[0]

    speech = np.full((160, 1), 2000, dtype=np.int16)
    silence = np.zeros((400, 1), dtype=np.int16)
    stream.callback(speech, len(speech), None, 0)
    stream.callback(silence, len(silence), None, 0)

    segment = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert segment.audio_path.exists()
    assert segment.duration_sec > 0

    await recorder.close()
    segment.audio_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_max_segment_duration_flushes_without_silence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
        start_level_db=-40.0,
        stop_level_db=-60.0,
        pre_buffer_ms=0,
        post_buffer_ms=1000,
        max_segment_sec=1,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    await recorder.start_input_monitoring()
    stream = created_streams[0]

    voice_chunk = np.full((8000, 1), 2500, dtype=np.int16)
    stream.callback(voice_chunk, len(voice_chunk), None, 0)
    stream.callback(voice_chunk, len(voice_chunk), None, 0)

    segment = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert segment.audio_path.exists()
    assert segment.duration_sec >= 1.0

    await recorder.close()
    segment.audio_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_start_input_monitoring_logs_available_input_devices_on_open_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="Mic Device Name",
        level_interval_ms=10,
    )

    def failing_input_stream(**kwargs) -> _FakeInputStream:
        _ = kwargs
        msg = "Error querying device"
        raise ValueError(msg)

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", failing_input_stream)
    monkeypatch.setattr(
        "core.stt.recorder.sd.query_devices",
        lambda: [
            {"name": "Speakers", "max_input_channels": 0},
            {"name": "Microphone (USB)", "max_input_channels": 2},
            {"name": "Microphone (USB)", "max_input_channels": 2},
        ],
    )

    caplog.set_level(logging.WARNING)

    with pytest.raises(RuntimeError, match="Failed to start STT input stream"):
        await recorder.start_input_monitoring()

    assert "Available STT input devices (configured=Mic Device Name, unique=1)" in caplog.text
    assert "[1,2] Microphone (USB) (in=2)" in caplog.text


@pytest.mark.asyncio
async def test_set_mute_drops_queued_segments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
    )

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        return _FakeInputStream(**kwargs)

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    await recorder.start_input_monitoring()
    segment = await recorder.record_mock_segment(duration_sec=0.1)
    assert segment is not None
    assert queue.qsize() == 1
    assert segment.audio_path.exists()

    recorder.set_mute(mute=True)
    for _ in range(20):
        if queue.empty():
            break
        await asyncio.sleep(0.01)

    assert queue.empty() is True
    assert segment.audio_path.exists() is False
    await recorder.close()


@pytest.mark.asyncio
async def test_set_mute_resets_active_segmentation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
        start_level_db=-34.0,
        stop_level_db=-40.0,
        pre_buffer_ms=100,
        post_buffer_ms=20,
        max_segment_sec=10,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    await recorder.start_input_monitoring()
    stream = created_streams[0]

    speech = np.full((160, 1), 2000, dtype=np.int16)
    stream.callback(speech, len(speech), None, 0)
    recorder.set_mute(mute=True)
    recorder.set_mute(mute=False)

    silence = np.zeros((400, 1), dtype=np.int16)
    stream.callback(silence, len(silence), None, 0)

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.1)

    await recorder.close()


@pytest.mark.asyncio
async def test_watch_input_health_attempts_reconnect_when_stalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
    )

    recorder._monitoring = True
    recorder._stream = cast(
        "Any",
        _FakeInputStream(
            samplerate=16000,
            channels=1,
            dtype="int16",
            device=None,
            callback=lambda *_: None,
        ),
    )
    recorder._input_stall_timeout_sec = 0.0
    recorder._reconnect_backoff_sec = 0.0
    recorder._last_audio_callback_monotonic = time.monotonic() - 1.0

    reconnect_called = asyncio.Event()

    async def fake_to_thread(func, /, *args, **kwargs):
        _ = args, kwargs
        func()
        reconnect_called.set()

    sleep_call_count = 0

    async def fake_sleep(_delay: float) -> None:
        nonlocal sleep_call_count
        sleep_call_count += 1
        if sleep_call_count >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(recorder, "_restart_input_stream", lambda: None)
    monkeypatch.setattr("core.stt.recorder.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("core.stt.recorder.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await recorder._watch_input_health()

    assert reconnect_called.is_set()


def test_open_input_stream_fallback_from_default_to_available_index(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
    )

    created_streams: list[_FakeInputStream] = []

    def fake_input_stream(**kwargs) -> _FakeInputStream:
        device = kwargs.get("device")
        if device is None:
            msg = "default device failed"
            raise ValueError(msg)

        stream = _FakeInputStream(**kwargs)
        created_streams.append(stream)
        return stream

    monkeypatch.setattr(
        "core.stt.recorder.sd.query_devices",
        lambda: [{"max_input_channels": 0}, {"max_input_channels": 1}],
    )
    monkeypatch.setattr("core.stt.recorder.sd.InputStream", fake_input_stream)

    recorder._open_input_stream()

    assert recorder._stream is not None
    assert created_streams
    assert created_streams[0].device == 1
    assert created_streams[0].started is True


@pytest.mark.asyncio
async def test_watch_input_health_attempts_reconnect_when_stream_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(
        segment_queue=queue,
        tmp_directory=tmp_path,
        sample_rate=16000,
        channels=1,
        input_device="default",
        level_interval_ms=10,
    )

    recorder._monitoring = True
    recorder._stream = None
    recorder._input_stall_timeout_sec = 999.0
    recorder._reconnect_backoff_sec = 0.0
    recorder._last_audio_callback_monotonic = time.monotonic()

    reconnect_called = asyncio.Event()

    async def fake_to_thread(func, /, *args, **kwargs):
        _ = args, kwargs
        func()
        reconnect_called.set()

    sleep_call_count = 0

    async def fake_sleep(_delay: float) -> None:
        nonlocal sleep_call_count
        sleep_call_count += 1
        if sleep_call_count >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(recorder, "_restart_input_stream", lambda: None)
    monkeypatch.setattr("core.stt.recorder.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("core.stt.recorder.asyncio.sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await recorder._watch_input_health()

    assert reconnect_called.is_set()


# ---------------------------------------------------------------------------
# Tests added to cover gaps identified in review
# ---------------------------------------------------------------------------


def test_normalize_threshold_pair_swaps_when_start_less_than_stop(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    start, stop = recorder._normalize_threshold_pair(-50.0, -20.0)

    assert start == -20.0
    assert stop == -50.0


def test_normalize_threshold_pair_preserves_order_when_start_greater(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    start, stop = recorder._normalize_threshold_pair(-20.0, -40.0)

    assert start == -20.0
    assert stop == -40.0


def test_set_thresholds_updates_db_values_and_propagates_to_vad(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    recorder.set_thresholds(start_level_db=-25.0, stop_level_db=-45.0)

    assert recorder.start_level_db == -25.0
    assert recorder.stop_level_db == -45.0
    # Linear level values should be consistent: start level > stop level
    assert recorder._start_level > recorder._stop_level


def test_set_thresholds_swaps_when_start_less_than_stop(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    recorder.set_thresholds(start_level_db=-50.0, stop_level_db=-20.0)

    # Values should be swapped so start > stop
    assert recorder.start_level_db == -20.0
    assert recorder.stop_level_db == -50.0


def test_set_vad_threshold_clamps_above_one(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    result = recorder.set_vad_threshold(threshold=2.5)

    assert result == 1.0
    assert recorder.vad_threshold == 1.0


def test_set_vad_threshold_clamps_below_zero(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    result = recorder.set_vad_threshold(threshold=-0.3)

    assert result == 0.0
    assert recorder.vad_threshold == 0.0


@pytest.mark.asyncio
async def test_record_mock_segment_white_noise_produces_nonzero_pcm(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path, sample_rate=16000, channels=1)

    segment = await recorder.record_mock_segment(duration_sec=0.05, mode=SegmentMode.WHITE_NOISE)

    assert segment is not None
    assert segment.audio_path.exists()
    pcm_bytes = segment.audio_path.read_bytes()
    assert len(pcm_bytes) > 0
    # White noise should not be all zeros
    assert any(b != 0 for b in pcm_bytes)

    segment.audio_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_close_without_start_input_monitoring_completes_normally(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)

    # Should not raise even when monitoring was never started
    await recorder.close()

    assert recorder.is_monitoring is False


@pytest.mark.asyncio
async def test_dispatch_level_events_skips_when_callback_is_none(tmp_path: Path) -> None:
    queue: asyncio.Queue[STTSegment] = asyncio.Queue()
    recorder = STTRecorder(segment_queue=queue, tmp_directory=tmp_path)
    recorder._on_level_event = None

    # Enqueue an event and run dispatch briefly — no callback set, no exception expected
    recorder._level_queue.put_nowait(STTLevelEvent(rms=0.1, peak=0.2, muted=False, timestamp=0.0))

    dispatch_task = asyncio.create_task(recorder._dispatch_level_events())
    await asyncio.sleep(0.05)
    dispatch_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await dispatch_task

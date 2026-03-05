from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import numpy as np
import pytest

from core.stt.recorder import STTLevelEvent, STTRecorder, STTSegment

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

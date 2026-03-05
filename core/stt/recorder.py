"""Audio segment recorder for STT pipeline.

Recorder handles microphone level monitoring and threshold-based segmentation,
then writes temporary PCM files and enqueues them for STT processing.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from os import urandom
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

from utils.logger_utils import LoggerUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    import logging
    from typing import Any

logger: logging.Logger = LoggerUtils.get_logger(__name__)

INT16_SAMPLE_WIDTH_BYTES: int = 2
DEFAULT_SEGMENT_SEC: float = 1.0
DEFAULT_LEVEL_INTERVAL_MS: int = 100
INT16_DIVISOR: float = 32768.0
DEFAULT_START_LEVEL_dB: float = -20.0
DEFAULT_STOP_LEVEL_dB: float = -40.0
DEFAULT_MIN_LEVEL_dB: float = -60.0
DEFAULT_PRE_BUFFER_MS: int = 300
DEFAULT_POST_BUFFER_MS: int = 500
DEFAULT_MAX_SEGMENT_SEC: int = 20


class SegmentMode(StrEnum):
    """Audio content mode for synthetic segment generation."""

    SILENCE = "silence"
    WHITE_NOISE = "white_noise"


@dataclass(frozen=True)
class STTSegment:
    """Recorded audio segment metadata."""

    audio_path: Path
    sample_rate: int
    channels: int
    duration_sec: float
    created_at: float


@dataclass(frozen=True)
class STTLevelEvent:
    """Audio input level snapshot.

    Attributes:
        rms (float): RMS level in 0.0-1.0.
        peak (float): Peak level in 0.0-1.0.
        muted (bool): Whether recorder is muted.
        timestamp (float): Event timestamp in epoch seconds.
    """

    rms: float
    peak: float
    muted: bool
    timestamp: float


type LevelEventCallback = Callable[[STTLevelEvent], Awaitable[None] | None]


class STTRecorder:
    """Recorder façade used by STT manager."""

    def __init__(
        self,
        segment_queue: asyncio.Queue[STTSegment],
        tmp_directory: Path,
        sample_rate: int = 16000,
        channels: int = 1,
        input_device: str | int | None = "default",
        level_interval_ms: int = DEFAULT_LEVEL_INTERVAL_MS,
        start_level_db: float = DEFAULT_START_LEVEL_dB,
        stop_level_db: float = DEFAULT_STOP_LEVEL_dB,
        pre_buffer_ms: int = DEFAULT_PRE_BUFFER_MS,
        post_buffer_ms: int = DEFAULT_POST_BUFFER_MS,
        max_segment_sec: int = DEFAULT_MAX_SEGMENT_SEC,
    ) -> None:
        self._segment_queue: asyncio.Queue[STTSegment] = segment_queue
        self._tmp_directory: Path = tmp_directory
        self._sample_rate: int = sample_rate
        self._channels: int = channels
        self._input_device: str | int | None = input_device
        self._level_interval_sec: float = max(level_interval_ms, 10) / 1000.0
        self._muted: bool = False
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._level_queue: asyncio.Queue[STTLevelEvent] = asyncio.Queue(maxsize=16)
        self._level_dispatch_task: asyncio.Task[None] | None = None
        self._on_level_event: LevelEventCallback | None = None
        self._last_level_emit_time: float = 0.0
        self._monitoring: bool = False
        self._current_level: float = 0.0
        normalized_start, normalized_stop = self._normalize_threshold_pair(start_level_db, stop_level_db)
        self._start_level_db: float = normalized_start
        self._stop_level_db: float = normalized_stop
        self._start_level: float = self._normalize_level(TTSUtils.db_to_linear(normalized_start))
        self._stop_level: float = self._normalize_level(TTSUtils.db_to_linear(normalized_stop))
        self._pre_buffer_ms: int = max(0, int(pre_buffer_ms))
        self._post_buffer_ms: int = max(0, int(post_buffer_ms))
        self._max_segment_sec: int = max(1, int(max_segment_sec))
        self._pre_buffer_chunks: deque[np.ndarray] = deque()
        self._pre_buffer_frames: int = 0
        self._segment_chunks: list[np.ndarray] = []
        self._segment_frames: int = 0
        self._recording_active: bool = False
        self._silence_duration_sec: float = 0.0
        self._pending_segment_tasks: set[asyncio.Task[None]] = set()

    @property
    def input_device(self) -> str | int | None:
        return self._input_device

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def current_level(self) -> float:
        return self._current_level

    @property
    def is_monitoring(self) -> bool:
        return self._monitoring

    @property
    def muted(self) -> bool:
        return self._muted

    @property
    def start_level_db(self) -> float:
        return self._start_level_db

    @property
    def stop_level_db(self) -> float:
        return self._stop_level_db

    def set_thresholds(self, *, start_level_db: float, stop_level_db: float) -> None:
        """Update segmentation thresholds.

        Args:
            start_level_db (float): Start threshold in dB.
            stop_level_db (float): Stop threshold in dB.
        """
        applied_start, applied_stop = self._normalize_threshold_pair(start_level_db, stop_level_db)
        self._start_level_db = applied_start
        self._stop_level_db = applied_stop
        self._start_level = self._normalize_level(TTSUtils.db_to_linear(applied_start))
        self._stop_level = self._normalize_level(TTSUtils.db_to_linear(applied_stop))

    def set_mute(self, *, mute: bool) -> None:
        self._muted = mute

    async def start_input_monitoring(self, on_level_event: LevelEventCallback | None = None) -> None:
        """Start microphone input monitoring and level notifications.

        Args:
            on_level_event (LevelEventCallback | None): Optional callback invoked for each level event.

        Raises:
            RuntimeError: If input stream could not be opened.
        """
        if self._monitoring:
            logger.debug("STT input monitoring already started")
            return

        self._loop = asyncio.get_running_loop()
        self._on_level_event = on_level_event
        self._level_dispatch_task = asyncio.create_task(self._dispatch_level_events(), name="stt_level_dispatch_task")

        try:
            await asyncio.to_thread(self._open_input_stream)
        except Exception:
            if self._level_dispatch_task is not None:
                self._level_dispatch_task.cancel()
                self._level_dispatch_task = None
            self._on_level_event = None
            self._loop = None
            raise

        self._monitoring = True
        logger.info(
            "STT input monitoring started (device=%s, sample_rate=%d, channels=%d)",
            self._input_device,
            self._sample_rate,
            self._channels,
        )

    async def stop_input_monitoring(self) -> None:
        """Stop microphone input monitoring and background dispatch task."""
        if self._stream is not None:
            await asyncio.to_thread(self._close_input_stream)

        self._flush_active_segment()
        if self._pending_segment_tasks:
            await asyncio.gather(*list(self._pending_segment_tasks), return_exceptions=True)
            self._pending_segment_tasks.clear()

        self._monitoring = False
        self._current_level = 0.0
        self._on_level_event = None

        if self._level_dispatch_task is not None:
            self._level_dispatch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._level_dispatch_task
            self._level_dispatch_task = None

        self._loop = None
        self._clear_level_queue()
        self._reset_segmentation_state()
        logger.info("STT input monitoring stopped")

    async def record_mock_segment(
        self,
        duration_sec: float = DEFAULT_SEGMENT_SEC,
        mode: SegmentMode = SegmentMode.SILENCE,
    ) -> STTSegment | None:
        """Create synthetic PCM segment and enqueue it.

        Args:
            duration_sec (float): Segment length in seconds.
            mode (SegmentMode): Synthetic sample mode.

        Returns:
            STTSegment | None: Created segment metadata, or None when muted.
        """
        if self._muted:
            logger.debug("STT mock segment generation skipped because recorder is muted")
            return None

        if duration_sec <= 0:
            msg = "duration_sec must be greater than 0"
            raise ValueError(msg)

        frame_count: int = int(duration_sec * self._sample_rate)
        pcm_data: bytes = self._create_pcm(frame_count, mode)

        self._tmp_directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="wb", suffix=".pcm", dir=self._tmp_directory, delete=False) as file:
            file.write(pcm_data)
            segment_path = Path(file.name)

        segment = STTSegment(
            audio_path=segment_path,
            sample_rate=self._sample_rate,
            channels=self._channels,
            duration_sec=duration_sec,
            created_at=time.time(),
        )
        await self._segment_queue.put(segment)
        logger.debug("Mock STT segment queued: path=%s duration=%.2f", segment.audio_path, segment.duration_sec)
        return segment

    def _create_pcm(self, frame_count: int, mode: SegmentMode) -> bytes:
        if mode is SegmentMode.SILENCE:
            sample_count: int = frame_count * self._channels
            return b"\x00\x00" * sample_count

        total_samples: int = frame_count * self._channels
        total_size: int = total_samples * INT16_SAMPLE_WIDTH_BYTES
        return urandom(total_size)

    def _open_input_stream(self) -> None:
        resolved_device: str | int | None = self._resolve_input_device(self._input_device)
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                device=resolved_device,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as err:  # noqa: BLE001
            self._log_available_input_devices()
            msg = f"Failed to start STT input stream: {err}"
            raise RuntimeError(msg) from err

    def _log_available_input_devices(self) -> None:
        try:
            devices: list[dict[str, Any]] = list(sd.query_devices())
        except Exception as query_err:  # noqa: BLE001
            logger.warning("Failed to query STT input device list: %s", query_err)
            return

        grouped_inputs: dict[tuple[str, int], list[int]] = {}
        for index, device in enumerate(devices):
            max_input_channels = int(device.get("max_input_channels", 0))
            if max_input_channels <= 0:
                continue
            device_name = str(device.get("name", "<unknown>"))
            key = (device_name, max_input_channels)
            indices = grouped_inputs.setdefault(key, [])
            indices.append(index)

        configured_device: str | int | None = self._input_device
        if not grouped_inputs:
            logger.warning(
                "No STT input-capable audio devices found (configured=%s).",
                configured_device,
            )
            return

        sorted_items = sorted(grouped_inputs.items(), key=lambda item: item[1][0])
        formatted_inputs: list[str] = []
        for (device_name, max_input_channels), indices in sorted_items:
            index_label = ",".join(str(value) for value in indices)
            formatted_inputs.append(f"  - [{index_label}] {device_name} (in={max_input_channels})")

        joined_devices = "\n".join(formatted_inputs)
        logger.warning(
            "Available STT input devices (configured=%s, unique=%d):\n%s",
            configured_device,
            len(formatted_inputs),
            joined_devices,
        )

    def _close_input_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        with contextlib.suppress(Exception):  # noqa: BLE001
            stream.stop()
        with contextlib.suppress(Exception):  # noqa: BLE001
            stream.close()

    @staticmethod
    def _resolve_input_device(input_device: str | int | None) -> str | int | None:
        if input_device is None:
            return None
        if isinstance(input_device, int):
            return input_device

        device_name: str = str(input_device).strip()
        if not device_name or device_name.lower() == "default":
            return None
        if device_name.isdigit():
            return int(device_name)
        return device_name

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
        _ = frames, time_info
        if status:
            logger.debug("STT input callback status: %s", status)

        event: STTLevelEvent = self._build_level_event(indata)
        self._current_level = event.rms
        if not self._muted:
            self._process_segmenting(indata, frames, event.rms)

        now: float = time.monotonic()
        if now - self._last_level_emit_time < self._level_interval_sec:
            return
        self._last_level_emit_time = now

        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._enqueue_level_event, event)

    def _build_level_event(self, indata: np.ndarray) -> STTLevelEvent:
        if self._muted:
            return STTLevelEvent(rms=0.0, peak=0.0, muted=True, timestamp=time.time())

        if indata.size == 0:
            return STTLevelEvent(rms=0.0, peak=0.0, muted=False, timestamp=time.time())

        float_data = indata.astype(np.float32, copy=False) / INT16_DIVISOR
        rms = float(np.sqrt(np.mean(np.square(float_data), dtype=np.float32)))
        peak = float(np.max(np.abs(float_data), initial=0.0))
        return STTLevelEvent(rms=rms, peak=peak, muted=False, timestamp=time.time())

    def _process_segmenting(self, indata: np.ndarray, frames: int, rms: float) -> None:
        if frames <= 0:
            return

        chunk = np.array(indata, dtype=np.int16, copy=True)
        if not self._recording_active:
            if rms >= self._start_level:
                self._start_segment(trigger_chunk=chunk, trigger_frames=frames)
            else:
                self._push_pre_buffer(chunk, frames)
            return

        self._segment_chunks.append(chunk)
        self._segment_frames += frames

        if rms <= self._stop_level:
            self._silence_duration_sec += frames / self._sample_rate
        else:
            self._silence_duration_sec = 0.0

        should_stop_by_silence: bool = self._silence_duration_sec >= (self._post_buffer_ms / 1000)
        should_stop_by_max_len: bool = self._segment_frames >= int(self._max_segment_sec * self._sample_rate)
        if should_stop_by_silence or should_stop_by_max_len:
            self._flush_active_segment()

    def _start_segment(self, *, trigger_chunk: np.ndarray, trigger_frames: int) -> None:
        self._recording_active = True
        self._silence_duration_sec = 0.0
        self._segment_chunks = list(self._pre_buffer_chunks)
        self._segment_frames = self._pre_buffer_frames
        self._segment_chunks.append(trigger_chunk)
        self._segment_frames += trigger_frames
        self._pre_buffer_chunks.clear()
        self._pre_buffer_frames = 0

    def _flush_active_segment(self) -> None:
        if not self._recording_active or self._segment_frames <= 0 or not self._segment_chunks:
            self._reset_segmentation_state()
            return

        segment_array = np.concatenate(self._segment_chunks, axis=0)
        pcm_data: bytes = segment_array.astype(np.int16, copy=False).tobytes(order="C")

        self._tmp_directory.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="wb", suffix=".pcm", dir=self._tmp_directory, delete=False) as file:
            file.write(pcm_data)
            segment_path = Path(file.name)

        duration_sec: float = self._segment_frames / self._sample_rate
        segment = STTSegment(
            audio_path=segment_path,
            sample_rate=self._sample_rate,
            channels=self._channels,
            duration_sec=duration_sec,
            created_at=time.time(),
        )
        self._schedule_segment_enqueue(segment)
        self._reset_segmentation_state()

    def _schedule_segment_enqueue(self, segment: STTSegment) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            logger.warning("STT event loop unavailable; dropping segment path=%s", segment.audio_path)
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)
            return

        loop.call_soon_threadsafe(self._create_segment_enqueue_task, segment)

    def _create_segment_enqueue_task(self, segment: STTSegment) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)
            return

        task: asyncio.Task[None] = loop.create_task(self._enqueue_segment(segment), name="stt_segment_queue_put")
        self._pending_segment_tasks.add(task)
        task.add_done_callback(self._pending_segment_tasks.discard)

    async def _enqueue_segment(self, segment: STTSegment) -> None:
        try:
            await self._segment_queue.put(segment)
            logger.debug("STT segment queued: path=%s duration=%.2f", segment.audio_path, segment.duration_sec)
        except asyncio.QueueShutDown:
            logger.debug("STT segment queue is shutting down; dropping segment path=%s", segment.audio_path)
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)

    def _push_pre_buffer(self, chunk: np.ndarray, frames: int) -> None:
        self._pre_buffer_chunks.append(chunk)
        self._pre_buffer_frames += frames

        max_pre_frames: int = int((self._pre_buffer_ms / 1000) * self._sample_rate)
        while self._pre_buffer_chunks and self._pre_buffer_frames > max_pre_frames:
            removed = self._pre_buffer_chunks.popleft()
            self._pre_buffer_frames -= int(removed.shape[0])

    def _reset_segmentation_state(self) -> None:
        self._recording_active = False
        self._silence_duration_sec = 0.0
        self._segment_chunks.clear()
        self._segment_frames = 0
        self._pre_buffer_chunks.clear()
        self._pre_buffer_frames = 0

    @staticmethod
    def _normalize_level(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _clamp_level_db(value: float) -> float:
        return max(DEFAULT_MIN_LEVEL_dB, min(0.0, float(value)))

    @classmethod
    def _normalize_threshold_pair(cls, start_level_db: float, stop_level_db: float) -> tuple[float, float]:
        start = cls._clamp_level_db(start_level_db)
        stop = cls._clamp_level_db(stop_level_db)
        if start < stop:
            return stop, start
        return start, stop

    def _enqueue_level_event(self, event: STTLevelEvent) -> None:
        if self._level_queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._level_queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._level_queue.put_nowait(event)

    async def _dispatch_level_events(self) -> None:
        while True:
            event: STTLevelEvent = await self._level_queue.get()
            callback: Callable[[STTLevelEvent], Awaitable[None] | None] | None = self._on_level_event
            if callback is None:
                continue

            try:
                result: Awaitable[None] | None = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as err:  # noqa: BLE001
                logger.warning("STT level callback failed: %s", err)

    def _clear_level_queue(self) -> None:
        while True:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._level_queue.get_nowait()
                continue
            break

    async def close(self) -> None:
        """Close recorder resources."""
        await self.stop_input_monitoring()

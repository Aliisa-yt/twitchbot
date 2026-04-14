"""Audio segment recorder for STT pipeline.

Recorder handles microphone level monitoring and threshold-based segmentation,
then writes temporary PCM files and enqueues them for STT processing.
"""

import asyncio
import contextlib
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from os import urandom
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Final

import numpy as np
import sounddevice as sd

from core.stt.vad import LevelVADProcessor, SileroOnnxVADProcessor, VADDecision, VADProcessorInterface
from utils.logger_utils import LoggerUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    import logging
    from typing import Any

logger: logging.Logger = LoggerUtils.get_logger(__name__)

INT16_SAMPLE_WIDTH_BYTES: Final[int] = 2
DEFAULT_SEGMENT_SEC: Final[float] = 1.0
DEFAULT_LEVEL_INTERVAL_MS: Final[int] = 100
INT16_DIVISOR: Final[float] = 32768.0
DEFAULT_START_LEVEL_dB: Final[float] = -20.0
DEFAULT_STOP_LEVEL_dB: Final[float] = -40.0
DEFAULT_MIN_LEVEL_dB: Final[float] = -60.0
DEFAULT_PRE_BUFFER_MS: Final[int] = 300
DEFAULT_POST_BUFFER_MS: Final[int] = 500
DEFAULT_MAX_SEGMENT_SEC: Final[int] = 20
DEFAULT_INPUT_STALL_TIMEOUT_SEC: Final[float] = 2.0
DEFAULT_RECONNECT_BACKOFF_SEC: Final[float] = 3.0
DEFAULT_VAD_MODE: Final[str] = "level"
DEFAULT_SILERO_ONNX_MODEL_PATH: Final[str] = "data/stt/silero/silero_vad.onnx"
DEFAULT_SILERO_VAD_THRESHOLD: Final[float] = 0.5


class VADMode(StrEnum):
    """VAD mode selector for recorder segmentation."""

    LEVEL = "level"
    SILERO_ONNX = "silero_onnx"


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
    """Recorder façade used by STT manager.

    The STT Recorder manages the microphone input stream, performs VAD-based segmentation and queues
    the recorded segments for processing. The recorder supports the adjustment of dynamic thresholds,
    muting and the generation of synthetic segments.

    Properties:
        input_device (str | int | None): Configured audio input device.
        sample_rate (int): Configured audio sample rate.
        channels (int): Configured audio channel count.
        current_level (float): Current input level in 0.0-1.0.
        is_monitoring (bool): Whether input monitoring is active.
        muted (bool): Whether recorder is muted.
        start_level_db (float): Start threshold in dB.
        stop_level_db (float): Stop threshold in dB.
        vad_mode (VADMode): VAD mode used for segmentation.
        vad_threshold (float): VAD probability threshold for probability-based VAD modes.
    """

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
        vad_mode: str = DEFAULT_VAD_MODE,
        vad_silero_model_path: str = DEFAULT_SILERO_ONNX_MODEL_PATH,
        vad_threshold: float = DEFAULT_SILERO_VAD_THRESHOLD,
        vad_onnx_threads: int = 1,
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
        self._start_level: float = self._normalize_level(TTSUtils.log_to_linear(normalized_start))
        self._stop_level: float = self._normalize_level(TTSUtils.log_to_linear(normalized_stop))
        self._pre_buffer_ms: int = max(0, int(pre_buffer_ms))
        self._post_buffer_ms: int = max(0, int(post_buffer_ms))
        self._max_segment_sec: int = max(1, int(max_segment_sec))
        self._pre_buffer_chunks: deque[np.ndarray] = deque()
        self._pre_buffer_frames: int = 0
        self._segment_chunks: list[np.ndarray] = []
        self._segment_frames: int = 0
        self._vad_mode: VADMode = self._normalize_vad_mode(vad_mode)
        self._vad_threshold: float = max(0.0, min(1.0, float(vad_threshold)))
        self._vad_processor: VADProcessorInterface = self._create_vad_processor(
            vad_mode=self._vad_mode,
            vad_silero_model_path=vad_silero_model_path,
            vad_threshold=self._vad_threshold,
            vad_onnx_threads=vad_onnx_threads,
        )
        self._pending_segment_tasks: set[asyncio.Task[None]] = set()
        self._input_watchdog_task: asyncio.Task[None] | None = None
        self._last_audio_callback_monotonic: float = time.monotonic()
        self._last_reconnect_attempt_monotonic: float = 0.0
        self._input_stall_timeout_sec: float = DEFAULT_INPUT_STALL_TIMEOUT_SEC
        self._reconnect_backoff_sec: float = DEFAULT_RECONNECT_BACKOFF_SEC
        self._segment_epoch: int = 0

    @staticmethod
    def _normalize_vad_mode(vad_mode: str) -> VADMode:
        try:
            return VADMode(vad_mode.strip().lower())
        except ValueError:
            return VADMode.LEVEL

    def _create_vad_processor(
        self,
        *,
        vad_mode: VADMode,
        vad_silero_model_path: str,
        vad_threshold: float,
        vad_onnx_threads: int,
    ) -> VADProcessorInterface:
        if vad_mode is VADMode.SILERO_ONNX:
            model_path: Path = self._resolve_resource_path(vad_silero_model_path)
            if not model_path.exists():
                msg = f"Silero ONNX model file not found: {model_path}"
                raise RuntimeError(msg)

            logger.info("STT recorder VAD mode: silero_onnx (model=%s)", model_path)
            return SileroOnnxVADProcessor(
                model_path=model_path,
                threshold=vad_threshold,
                post_buffer_ms=self._post_buffer_ms,
                max_segment_sec=self._max_segment_sec,
                sample_rate=self._sample_rate,
                onnx_threads=max(1, int(vad_onnx_threads)),
            )

        logger.info("STT recorder VAD mode: level")
        return LevelVADProcessor(
            start_level=self._start_level,
            stop_level=self._stop_level,
            post_buffer_ms=self._post_buffer_ms,
            max_segment_sec=self._max_segment_sec,
        )

    @staticmethod
    def _resolve_resource_path(path_text: str) -> Path:
        candidate: Path = Path(path_text)
        if candidate.is_absolute():
            return candidate

        meipass: str | None = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / candidate

        return candidate

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

    @property
    def vad_mode(self) -> VADMode:
        return self._vad_mode

    @property
    def vad_threshold(self) -> float:
        return self._vad_threshold

    def set_thresholds(self, *, start_level_db: float, stop_level_db: float) -> None:
        """Update segmentation thresholds.

        Args:
            start_level_db (float): Start threshold in dB.
            stop_level_db (float): Stop threshold in dB.
        """
        applied_start, applied_stop = self._normalize_threshold_pair(start_level_db, stop_level_db)
        self._start_level_db = applied_start
        self._stop_level_db = applied_stop
        self._start_level = self._normalize_level(TTSUtils.log_to_linear(applied_start))
        self._stop_level = self._normalize_level(TTSUtils.log_to_linear(applied_stop))
        self._vad_processor.set_thresholds(start_level=self._start_level, stop_level=self._stop_level)

    def set_vad_threshold(self, *, threshold: float) -> float:
        """Update VAD threshold used by probability-based VAD modes.

        Args:
            threshold (float): VAD probability threshold in the range 0.0-1.0.

        Returns:
            float: Applied threshold value.
        """
        self._vad_threshold = self._vad_processor.set_vad_threshold(threshold=threshold)
        return self._vad_threshold

    def set_mute(self, *, mute: bool) -> None:
        if mute and not self._muted:
            # Drop partial captures and queued segments so unmuting never replays stale audio.
            self._segment_epoch += 1
            self._reset_segmentation_state()
            self._schedule_segment_queue_purge()
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
        self._last_audio_callback_monotonic = time.monotonic()

        try:
            await asyncio.to_thread(self._open_input_stream)
        except Exception:
            if self._level_dispatch_task is not None:  # pyright: ignore[reportUnnecessaryComparison]
                self._level_dispatch_task.cancel()
                self._level_dispatch_task = None
            self._on_level_event = None
            self._loop = None
            raise

        self._monitoring = True
        self._input_watchdog_task = asyncio.create_task(self._watch_input_health(), name="stt_input_watchdog_task")
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
        await asyncio.sleep(0)  # allow call_soon_threadsafe callbacks to run before snapshotting tasks
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

        if self._input_watchdog_task is not None:
            self._input_watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._input_watchdog_task
            self._input_watchdog_task = None

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
        candidates: list[str | int | None] = self._build_input_device_candidates(resolved_device)
        last_error: Exception | None = None

        for candidate in candidates:
            try:
                self._open_input_stream_with_device(candidate)
                if candidate != resolved_device:
                    logger.warning(
                        "STT input stream fallback selected device=%s (configured=%s)",
                        candidate,
                        self._input_device,
                    )
                break
            except Exception as err:  # noqa: BLE001
                last_error = err
                self._close_input_stream()
        else:
            self._log_available_input_devices()
            err_text: str = str(last_error) if last_error is not None else "unknown error"
            msg = f"Failed to start STT input stream: {err_text}"
            raise RuntimeError(msg) from last_error

    def _open_input_stream_with_device(self, device: str | int | None) -> None:
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="int16",
            device=device,
            callback=self._audio_callback,
        )
        self._stream.start()

    def _build_input_device_candidates(self, resolved_device: str | int | None) -> list[str | int | None]:
        if resolved_device is not None:
            return [resolved_device]

        candidates: list[str | int | None] = [None]
        candidates.extend(self._list_available_input_device_indices())

        return list(dict.fromkeys(candidates))

    def _list_available_input_device_indices(self) -> list[int]:
        try:
            devices: list[dict[str, Any]] = list(sd.query_devices())
        except (sd.PortAudioError, OSError, ValueError, RuntimeError):
            return []

        indices: list[int] = []
        for index, device in enumerate(devices):
            max_input_channels = int(device.get("max_input_channels", 0))
            if max_input_channels > 0:
                indices.append(index)
        return indices

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

        joined_devices: str = "\n".join(formatted_inputs)
        logger.warning(
            "Available STT input devices (configured=%s, unique=%d):\n%s",
            configured_device,
            len(formatted_inputs),
            joined_devices,
        )

    def _close_input_stream(self) -> None:
        stream: sd.InputStream | None = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except (sd.PortAudioError, OSError) as err:
            logger.debug("Ignoring STT input stream stop error during shutdown: %s", err)
        except Exception as err:  # noqa: BLE001
            logger.warning("Unexpected error while stopping STT input stream: %s", err)

        try:
            stream.close()
        except (sd.PortAudioError, OSError) as err:
            logger.debug("Ignoring STT input stream close error during shutdown: %s", err)
        except Exception as err:  # noqa: BLE001
            logger.warning("Unexpected error while closing STT input stream: %s", err)

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
        # NOTE: this method runs on the sounddevice callback thread.
        # _last_audio_callback_monotonic, _muted, and _current_level are accessed
        # from both this thread and the event loop thread; safe under CPython GIL.
        _ = frames, time_info
        self._last_audio_callback_monotonic = time.monotonic()
        if status:
            logger.warning("STT input callback status: %s", status)

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
        chunk = np.array(indata, dtype=np.int16, copy=True)
        decision: VADDecision = self._vad_processor.process_chunk(
            chunk=chunk,
            frames=frames,
            sample_rate=self._sample_rate,
            rms=rms,
            current_segment_frames=self._segment_frames,
        )

        if decision.push_pre_buffer:
            self._push_pre_buffer(chunk, frames)
            return

        if decision.start_segment:
            self._start_segment(trigger_chunk=chunk, trigger_frames=frames)
            return

        if decision.append_to_segment:
            self._segment_chunks.append(chunk)
            self._segment_frames += frames

        if decision.flush_segment:
            self._flush_active_segment()

    def _start_segment(self, *, trigger_chunk: np.ndarray, trigger_frames: int) -> None:
        self._segment_chunks = list(self._pre_buffer_chunks)
        self._segment_frames = self._pre_buffer_frames
        self._segment_chunks.append(trigger_chunk)
        self._segment_frames += trigger_frames
        self._pre_buffer_chunks.clear()
        self._pre_buffer_frames = 0

    def _flush_active_segment(self) -> None:
        if self._segment_frames <= 0 or not self._segment_chunks:
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
        self._schedule_segment_enqueue(segment, segment_epoch=self._segment_epoch)
        self._reset_segmentation_state()

    def _schedule_segment_enqueue(self, segment: STTSegment, *, segment_epoch: int) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            logger.warning("STT event loop unavailable; dropping segment path=%s", segment.audio_path)
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)
            return

        loop.call_soon_threadsafe(self._create_segment_enqueue_task, segment, segment_epoch)

    def _create_segment_enqueue_task(self, segment: STTSegment, segment_epoch: int) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)
            return

        task: asyncio.Task[None] = loop.create_task(
            self._enqueue_segment(segment, segment_epoch),
            name="stt_segment_queue_put",
        )
        self._pending_segment_tasks.add(task)
        task.add_done_callback(self._pending_segment_tasks.discard)

    async def _enqueue_segment(self, segment: STTSegment, segment_epoch: int) -> None:
        try:
            if segment_epoch != self._segment_epoch:
                with contextlib.suppress(OSError):
                    segment.audio_path.unlink(missing_ok=True)
                return
            await self._segment_queue.put(segment)
            logger.debug("STT segment queued: path=%s duration=%.2f", segment.audio_path, segment.duration_sec)
        except asyncio.QueueShutDown:
            logger.debug("STT segment queue is shutting down; dropping segment path=%s", segment.audio_path)
            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)

    def _schedule_segment_queue_purge(self) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._create_queue_purge_task)

    def _create_queue_purge_task(self) -> None:
        loop: asyncio.AbstractEventLoop | None = self._loop
        if loop is None:
            return
        task: asyncio.Task[None] = loop.create_task(self._purge_segment_queue(), name="stt_segment_queue_purge")
        self._pending_segment_tasks.add(task)
        task.add_done_callback(self._pending_segment_tasks.discard)

    async def _purge_segment_queue(self) -> None:
        while True:
            try:
                segment: STTSegment = self._segment_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            with contextlib.suppress(OSError):
                segment.audio_path.unlink(missing_ok=True)

    async def _watch_input_health(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if not self._monitoring:
                continue

            elapsed_sec: float = time.monotonic() - self._last_audio_callback_monotonic
            if self._stream is not None and elapsed_sec < self._input_stall_timeout_sec:
                continue

            now: float = time.monotonic()
            if now - self._last_reconnect_attempt_monotonic < self._reconnect_backoff_sec:
                continue

            self._last_reconnect_attempt_monotonic = now
            if self._stream is None:
                logger.warning("STT input stream is unavailable; attempting input stream reconnect")
            else:
                logger.warning(
                    "STT input callback stalled for %.2fs; attempting input stream reconnect",
                    elapsed_sec,
                )
            try:
                await asyncio.to_thread(self._restart_input_stream)
                self._last_audio_callback_monotonic = time.monotonic()
                logger.info("STT input stream reconnect succeeded")
            except Exception as err:  # noqa: BLE001
                logger.warning("STT input stream reconnect failed: %s", err)

    def _restart_input_stream(self) -> None:
        self._close_input_stream()
        self._open_input_stream()

    def _push_pre_buffer(self, chunk: np.ndarray, frames: int) -> None:
        self._pre_buffer_chunks.append(chunk)
        self._pre_buffer_frames += frames

        max_pre_frames: int = int((self._pre_buffer_ms / 1000) * self._sample_rate)
        while self._pre_buffer_chunks and self._pre_buffer_frames > max_pre_frames:
            removed = self._pre_buffer_chunks.popleft()
            self._pre_buffer_frames -= int(removed.shape[0])

    def _reset_segmentation_state(self) -> None:
        self._vad_processor.reset()
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
        start: float = cls._clamp_level_db(start_level_db)
        stop: float = cls._clamp_level_db(stop_level_db)
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
            try:
                self._level_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def close(self) -> None:
        """Close recorder resources."""
        await self.stop_input_monitoring()

"""STT manager lifecycle and orchestration."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from core.stt.engines import GoogleCloudSpeechToText, GoogleCloudSpeechToTextV2  # noqa: F401
from core.stt.processor import ProcessorOptions, STTProcessor
from core.stt.recorder import (
    DEFAULT_SILERO_ONNX_MODEL_PATH,
    DEFAULT_SILERO_VAD_THRESHOLD,
    DEFAULT_VAD_MODE,
    LevelEventCallback,
    SegmentMode,
    STTRecorder,
    STTSegment,
)
from core.stt.stt_interface import STTInterface, STTResult
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    from config.loader import Config
    from models.config_models import STT, VAD, LevelsVAD, SileroVAD

__all__: list[str] = ["STTManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class STTManager:
    """Manager responsible for STT pipeline lifecycle.

    This class initializes the STT engine, manages the recorder and processor components,
    and provides methods to control the STT system (e.g., mute, set thresholds).

    Attributes:
        config (Config): Application configuration object.

    Properties:
        enabled (bool): Indicates if the STT manager is initialized and active.
        recorder (STTRecorder | None): The STTRecorder instance if initialized, else None.
        is_muted (bool): Current mute state of the STT input monitoring.
    """

    _FIXED_SAMPLE_RATE: int = 16000
    _FIXED_CHANNELS: int = 1
    _TMP_DIR_REQUIRED_MSG: str = "GENERAL.TMP_DIR configuration is required for STT temporary file storage"

    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self._segment_queue: ExcludableQueue[STTSegment] = ExcludableQueue()
        self._terminate_event: asyncio.Event = asyncio.Event()
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._engine: STTInterface | None = None
        self._recorder: STTRecorder | None = None
        self._processor: STTProcessor | None = None
        self._on_level_event: LevelEventCallback | None = None
        self._enabled: bool = False
        self._mute: bool = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def recorder(self) -> STTRecorder | None:
        return self._recorder

    @property
    def is_muted(self) -> bool:
        return self._recorder.muted if self._recorder is not None else self._mute

    async def async_init(  # noqa: PLR0915
        self,
        on_result: Callable[[STTResult], Awaitable[None]] | None = None,
        on_level_event: LevelEventCallback | None = None,
    ) -> None:
        """Initialize STT manager and start background processor task."""
        if self._enabled:
            logger.warning("STT manager is already initialized")
            return

        if on_level_event is not None:
            self._on_level_event = on_level_event

        stt_config: STT | None = getattr(self.config, "STT", None)
        vad_config: VAD | None = getattr(self.config, "VAD", None)
        levels_vad_config: LevelsVAD | None = getattr(self.config, "LEVELS_VAD", None)
        silero_vad_config: SileroVAD | None = getattr(self.config, "SILERO_VAD", None)

        engine_name: str = getattr(stt_config, "ENGINE", "")
        engine_cls: type[STTInterface] | None = STTInterface.registered.get(engine_name)
        if engine_cls is None:
            logger.critical("STT engine class not found: '%s'", engine_name)
            return

        try:
            self._engine = engine_cls()
            self._engine.initialize(self.config)
            logger.info("STT engine initialized: '%s'", engine_name)
            print(f"Loaded Speech-to-Text engine: {engine_name}")
        except RuntimeError as err:
            logger.warning("STT engine '%s' could not be initialized: %s", engine_name, err)
            self._engine = None
            return

        tmp_dir_path: Path = self._resolve_tmp_dir()
        input_device: str = str(getattr(stt_config, "INPUT_DEVICE", "default"))
        start_level: float = float(getattr(levels_vad_config, "START", -20.0))
        stop_level: float = float(getattr(levels_vad_config, "STOP", -40.0))
        pre_buffer_ms: int = int(getattr(vad_config, "PRE_BUFFER_MS", 300))
        post_buffer_ms: int = int(getattr(vad_config, "POST_BUFFER_MS", 500))
        max_segment_sec: int = int(getattr(vad_config, "MAX_SEGMENT_SEC", 20))
        vad_mode: str = str(getattr(vad_config, "MODE", DEFAULT_VAD_MODE))
        vad_silero_model_path: str = str(getattr(silero_vad_config, "MODEL_PATH", DEFAULT_SILERO_ONNX_MODEL_PATH))
        vad_threshold: float = float(getattr(silero_vad_config, "THRESHOLD", DEFAULT_SILERO_VAD_THRESHOLD))
        vad_onnx_threads: int = int(getattr(silero_vad_config, "ONNX_THREADS", 1))
        language: str = str(getattr(stt_config, "LANGUAGE", "ja-JP"))
        retry_max: int = int(getattr(stt_config, "RETRY_MAX", 3))
        retry_backoff_ms: int = int(getattr(stt_config, "RETRY_BACKOFF_MS", 500))
        self._mute = bool(getattr(stt_config, "MUTE", False))

        refresh_rate: int = int(getattr(self.config.GUI, "LEVEL_METER_REFRESH_RATE", 10))
        refresh_rate = max(10, min(100, refresh_rate))  # 10fps to 100fps
        level_interval_ms: int = int(1000 / refresh_rate)

        self._recorder = STTRecorder(
            segment_queue=self._segment_queue,
            tmp_directory=tmp_dir_path,
            # Keep these fixed: recognition quality and current pipeline assumptions depend on them.
            sample_rate=self._FIXED_SAMPLE_RATE,
            channels=self._FIXED_CHANNELS,
            input_device=input_device,
            start_level_db=start_level,
            stop_level_db=stop_level,
            pre_buffer_ms=pre_buffer_ms,
            post_buffer_ms=post_buffer_ms,
            max_segment_sec=max_segment_sec,
            vad_mode=vad_mode,
            vad_silero_model_path=vad_silero_model_path,
            vad_threshold=vad_threshold,
            vad_onnx_threads=vad_onnx_threads,
            level_interval_ms=level_interval_ms,
        )
        self._recorder.set_mute(mute=self._mute)
        options = ProcessorOptions(language=language, retry_max=retry_max, retry_backoff_ms=retry_backoff_ms)
        self._processor = STTProcessor(
            segment_queue=self._segment_queue,
            terminate_event=self._terminate_event,
            engine=self._engine,
            options=options,
            on_result=on_result,
        )

        try:
            await self._recorder.start_input_monitoring(on_level_event=self._on_level_event)
        except RuntimeError as err:
            logger.error("STT input monitoring could not be started: %s", err)
            print(f"STT input monitoring could not be started: {err}")
            self._engine = None
            self._recorder = None
            self._processor = None
            self._enabled = False
            return

        task: asyncio.Task[None] = asyncio.create_task(self._processor.run(), name="STT-Processor-Task")
        self._background_tasks.add(task)
        self._enabled = True

        logger.info("STT manager initialized")

    def set_level_event_callback(self, callback: LevelEventCallback | None) -> None:
        """Set callback for STT level events.

        Args:
            callback (LevelEventCallback | None): Callback invoked for each input level event.
        """
        self._on_level_event = callback

    def set_mute(self, *, mute: bool) -> bool:
        """Set STT mute state.

        Args:
            mute (bool): True to mute STT input monitoring, False to unmute.

        Returns:
            bool: Current mute state.
        """
        self._mute = mute
        if self._recorder is not None:
            self._recorder.set_mute(mute=mute)
        return self._mute

    def toggle_mute(self) -> bool:
        """Toggle STT mute state.

        Returns:
            bool: Updated mute state.
        """
        return self.set_mute(mute=not self.is_muted)

    def set_thresholds(self, *, start_level_db: float, stop_level_db: float) -> tuple[float, float]:
        """Update recorder segmentation thresholds.

        Args:
            start_level_db (float): Start threshold in dB.
            stop_level_db (float): Stop threshold in dB.

        Returns:
            tuple[float, float]: Applied (start_level, stop_level) values.
        """
        if self._recorder is None:
            msg = "STT recorder is not initialized. Call async_init() first."
            raise RuntimeError(msg)

        self._recorder.set_thresholds(start_level_db=start_level_db, stop_level_db=stop_level_db)
        return self._recorder.start_level_db, self._recorder.stop_level_db

    def set_vad_threshold(self, *, threshold: float) -> float:
        """Update recorder VAD threshold for probability-based modes.

        Args:
            threshold (float): VAD threshold in the range 0.0-1.0.

        Returns:
            float: Applied VAD threshold.
        """
        if self._recorder is None:
            msg = "STT recorder is not initialized. Call async_init() first."
            raise RuntimeError(msg)

        return self._recorder.set_vad_threshold(threshold=threshold)

    async def close(self) -> None:
        """Gracefully terminate STT background tasks."""
        self._enabled = False
        self._terminate_event.set()
        self._segment_queue.shutdown()

        if self._recorder is not None:
            await self._recorder.close()

        if self._background_tasks:
            done_tasks: set[asyncio.Task[None]]
            pending_tasks: set[asyncio.Task[None]]
            done_tasks, pending_tasks = await asyncio.wait(self._background_tasks, timeout=2.0)

            for task in done_tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    err: BaseException | None = task.exception()
                    if err is not None:
                        logger.warning("STT background task failed (name=%s): %s", task.get_name(), err)

            for task in pending_tasks:
                task.cancel()

            if pending_tasks:
                logger.warning("Some STT tasks are still pending: %s", [task.get_name() for task in pending_tasks])
                await asyncio.gather(*pending_tasks, return_exceptions=True)

            self._background_tasks.clear()

        self._processor = None
        self._recorder = None
        self._engine = None
        self._terminate_event.clear()

    async def enqueue_silence_segment_for_test(self, duration_sec: float = 1.0) -> None:
        """Enqueue silence segment for pipeline tests without microphone input."""
        if self._recorder is None:
            msg = "STT recorder is not initialized. Call async_init() first."
            raise RuntimeError(msg)
        await self._recorder.record_mock_segment(duration_sec=duration_sec, mode=SegmentMode.SILENCE)

    async def enqueue_white_noise_segment_for_test(self, duration_sec: float = 1.0) -> None:
        """Enqueue white-noise segment for pipeline tests without microphone input."""
        if self._recorder is None:
            msg = "STT recorder is not initialized. Call async_init() first."
            raise RuntimeError(msg)
        await self._recorder.record_mock_segment(duration_sec=duration_sec, mode=SegmentMode.WHITE_NOISE)

    def _resolve_tmp_dir(self) -> Path:
        # Fail fast instead of falling back when TMP_DIR is missing.
        # Other features rely on this path as well, so fallback would only hide a misconfiguration.
        try:
            tmp_dir: Path | None = self.config.GENERAL.TMP_DIR
        except AttributeError as err:
            msg = self._TMP_DIR_REQUIRED_MSG
            raise RuntimeError(msg) from err

        if not tmp_dir:
            msg = self._TMP_DIR_REQUIRED_MSG
            raise RuntimeError(msg)
        return Path(tmp_dir)

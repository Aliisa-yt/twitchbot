"""Queue processor for STT audio segments."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.stt.stt_interface import (
    STTExceptionError,
    STTInput,
    STTInterface,
    STTNonRetriableError,
    STTNotAvailableError,
    STTResult,
)
from utils.file_utils import FileUtils, FileUtilsError
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from core.stt.recorder import STTSegment

__all__: list[str] = ["ProcessorOptions", "STTProcessor"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

@dataclass(frozen=True)
class ProcessorOptions:
    language: str = "ja-JP"


class STTProcessor:
    """Background processor that consumes STT segments."""

    def __init__(
        self,
        segment_queue: asyncio.Queue[STTSegment],
        terminate_event: asyncio.Event,
        engine: STTInterface | None,
        options: ProcessorOptions,
        on_result: Callable[[STTResult], Awaitable[None]] | None = None,
    ) -> None:
        self._segment_queue: asyncio.Queue[STTSegment] = segment_queue
        self._terminate_event: asyncio.Event = terminate_event
        self._engine: STTInterface | None = engine
        self._options: ProcessorOptions = options
        self._on_result: Callable[[STTResult], Awaitable[None]] | None = on_result

    async def run(self) -> None:
        """Consume queued segments until termination."""
        logger.info("STT processor started")

        while not self._terminate_event.is_set():
            try:
                segment: STTSegment = await self._segment_queue.get()
            except asyncio.QueueShutDown:
                logger.debug("STT segment queue shutdown detected")
                break

            await self._process_segment(segment)

        logger.info("STT processor terminated")

    async def _process_segment(self, segment: STTSegment) -> None:
        try:
            if self._engine is None or not self._engine.is_available:
                logger.warning("STT engine unavailable; dropping segment path=%s", segment.audio_path)
                return

            stt_input: STTInput = STTInput(
                audio_path=segment.audio_path,
                language=self._options.language,
                sample_rate=segment.sample_rate,
                channels=segment.channels,
            )
            result: STTResult | None = await self._transcribe_once(stt_input)
            if result is None:
                return

            if self._on_result is not None:
                await self._on_result(result)
        finally:
            self._cleanup_segment_file(segment.audio_path)

    async def _transcribe_once(self, stt_input: STTInput) -> STTResult | None:
        engine: STTInterface | None = self._engine
        if engine is None:
            logger.error("STT engine is not initialized")
            return None
        try:
            return await asyncio.to_thread(engine.transcribe, stt_input)
        except STTNonRetriableError as err:
            logger.error(
                "STT non-retriable transcribe error (language=%s): %s",
                stt_input.language,
                type(err).__name__,
            )
        except STTNotAvailableError as err:
            logger.warning(
                "STT engine became unavailable during transcribe (language=%s): %s",
                stt_input.language,
                type(err).__name__,
            )
        except STTExceptionError as err:
            logger.warning(
                "STT transcribe failed (language=%s): %s",
                stt_input.language,
                type(err).__name__,
            )
        except Exception as err:  # noqa: BLE001
            logger.error(
                "Unexpected non-STT exception during transcribe (language=%s): %s",
                stt_input.language,
                type(err).__name__,
            )
        return None

    def _cleanup_segment_file(self, file_path: Path) -> None:
        # Use shared file utility to centralize path validation and delete behavior.
        try:
            FileUtils.remove(file_path)
        except FileUtilsError as err:
            logger.warning("Failed to remove STT temp file path=%s err=%s", file_path, err)

"""Speech-to-Text package for Twitchbot.

This package provides STT interfaces, manager lifecycle control, audio segment recording,
and asynchronous processing pipeline components.
"""

from __future__ import annotations

from core.stt.processor import STTProcessor
from core.stt.recorder import SegmentMode, STTLevelEvent, STTRecorder, STTSegment
from core.stt.stt_interface import (
    STTExceptionError,
    STTInterface,
    STTNonRetriableError,
    STTNotAvailableError,
    STTQuotaExceededError,
    STTRateLimitError,
    STTResult,
    STTRetriableError,
)
from core.stt.stt_manager import STTManager

__all__: list[str] = [
    "STTExceptionError",
    "STTInterface",
    "STTLevelEvent",
    "STTManager",
    "STTNonRetriableError",
    "STTNotAvailableError",
    "STTProcessor",
    "STTQuotaExceededError",
    "STTRateLimitError",
    "STTRecorder",
    "STTResult",
    "STTRetriableError",
    "STTSegment",
    "SegmentMode",
]

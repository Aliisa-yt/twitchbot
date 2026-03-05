"""Speech-to-Text package for Twitchbot.

This package provides STT interfaces, manager lifecycle control, audio segment recording,
and asynchronous processing pipeline components.
"""

from __future__ import annotations

from core.stt.interface import STTExceptionError, STTInterface, STTNotAvailableError, STTResult
from core.stt.manager import STTManager
from core.stt.processor import STTProcessor
from core.stt.recorder import SegmentMode, STTLevelEvent, STTRecorder, STTSegment

__all__: list[str] = [
    "STTExceptionError",
    "STTInterface",
    "STTLevelEvent",
    "STTManager",
    "STTNotAvailableError",
    "STTProcessor",
    "STTRecorder",
    "STTResult",
    "STTSegment",
    "SegmentMode",
]

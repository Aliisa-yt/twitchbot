"""VAD processors for STT recorder."""

from __future__ import annotations

from core.stt.vad.interface import VADDecision, VADProcessorInterface
from core.stt.vad.level import LevelVADProcessor

__all__: list[str] = ["LevelVADProcessor", "VADDecision", "VADProcessorInterface"]

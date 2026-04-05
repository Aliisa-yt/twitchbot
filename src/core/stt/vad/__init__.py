"""VAD processors for STT recorder."""

from __future__ import annotations

from core.stt.vad.level import LevelVADProcessor
from core.stt.vad.silero_onnx import SileroOnnxVADProcessor
from core.stt.vad.vad_interface import VADDecision, VADProcessorInterface

__all__: list[str] = ["LevelVADProcessor", "SileroOnnxVADProcessor", "VADDecision", "VADProcessorInterface"]

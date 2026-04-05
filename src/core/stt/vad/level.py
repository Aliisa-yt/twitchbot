"""Level-based VAD processor implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.stt.vad.vad_interface import VADDecision

if TYPE_CHECKING:
    import numpy as np


@dataclass
class LevelVADProcessor:
    """Threshold-based VAD state machine used by existing recorder behavior."""

    start_level: float
    stop_level: float
    post_buffer_ms: int
    max_segment_sec: int

    def __post_init__(self) -> None:
        self._recording_active: bool = False
        self._silence_duration_sec: float = 0.0

    def reset(self) -> None:
        self._recording_active = False
        self._silence_duration_sec = 0.0

    def set_thresholds(self, *, start_level: float, stop_level: float) -> None:
        self.start_level = start_level
        self.stop_level = stop_level

    def set_vad_threshold(self, *, threshold: float) -> float:
        """Accept VAD threshold updates for interface compatibility.

        Level-based VAD does not use a probability threshold, so this method
        keeps the existing behavior unchanged and returns a clamped value.
        """
        return max(0.0, min(1.0, float(threshold)))

    def process_chunk(
        self,
        *,
        chunk: np.ndarray,
        frames: int,
        sample_rate: int,
        rms: float,
        current_segment_frames: int,
    ) -> VADDecision:
        _ = chunk
        if frames <= 0:
            return VADDecision()

        if not self._recording_active:
            if rms >= self.start_level:
                self._recording_active = True
                self._silence_duration_sec = 0.0
                return VADDecision(start_segment=True)
            return VADDecision(push_pre_buffer=True)

        if rms <= self.stop_level:
            self._silence_duration_sec += frames / sample_rate
        else:
            self._silence_duration_sec = 0.0

        total_frames: int = current_segment_frames + frames
        should_stop_by_silence: bool = self._silence_duration_sec >= (self.post_buffer_ms / 1000)
        should_stop_by_max_len: bool = total_frames >= int(self.max_segment_sec * sample_rate)
        should_flush: bool = should_stop_by_silence or should_stop_by_max_len
        if should_flush:
            self._recording_active = False
            self._silence_duration_sec = 0.0
        return VADDecision(append_to_segment=True, flush_segment=should_flush)

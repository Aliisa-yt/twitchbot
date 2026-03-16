"""VAD processor interface definitions for STT recorder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class VADDecision:
    """Decision returned by VAD processor for a single audio chunk."""

    push_pre_buffer: bool = False
    start_segment: bool = False
    append_to_segment: bool = False
    flush_segment: bool = False


class VADProcessorInterface(Protocol):
    """Contract for pluggable VAD processors used by STT recorder."""

    def reset(self) -> None:
        """Reset internal VAD state."""
        ...

    def set_thresholds(self, *, start_level: float, stop_level: float) -> None:
        """Update thresholds for processors that use level-based gating."""
        ...

    def process_chunk(
        self,
        *,
        chunk: np.ndarray,
        frames: int,
        sample_rate: int,
        rms: float,
        current_segment_frames: int,
    ) -> VADDecision:
        """Process one chunk and return recorder actions."""
        ...

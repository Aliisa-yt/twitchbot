"""Silero ONNX-based VAD processor implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
import onnxruntime as ort

from core.stt.vad.vad_interface import VADDecision

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@dataclass
class SileroOnnxVADProcessor:
    """ONNX Runtime based VAD state machine.

    This class keeps recorder-side start/append/flush behavior compatible with the
    existing level-based flow while switching the speech gate to model inference.

    The Silero VAD ONNX model requires a preceding audio context (64 samples at 16 kHz,
    32 samples at 8 kHz) to be prepended to each window before inference. Without this
    context the model returns near-zero probabilities for all inputs regardless of content.
    """

    model_path: Path
    threshold: float
    post_buffer_ms: int
    max_segment_sec: int
    sample_rate: int
    window_size: int = 512  # 512 samples = 32 ms at 16 kHz; use 256 for 8 kHz
    onnx_threads: int = 1
    _recording_active: bool = field(init=False, default=False)
    _silence_duration_sec: float = field(init=False, default=0.0)
    _tail_buffer: np.ndarray = field(init=False, default_factory=lambda: np.empty((0,), dtype=np.float32))
    _session: ort.InferenceSession = field(init=False)  # type: ignore[misc]
    _input_names: list[str] = field(init=False, default_factory=list)
    _output_names: list[str] = field(init=False, default_factory=list)
    _state_cache: dict[str, np.ndarray] = field(init=False, default_factory=dict)
    _context_size: int = field(init=False, default=0)
    _context: np.ndarray = field(init=False)  # type: ignore[misc]

    def __post_init__(self) -> None:
        providers: list[str] = ["CPUExecutionProvider"]
        session_options: ort.SessionOptions = self._build_session_options()
        self._session = ort.InferenceSession(str(self.model_path), sess_options=session_options, providers=providers)
        self._input_names = [meta.name for meta in self._session.get_inputs()]
        self._output_names = [meta.name for meta in self._session.get_outputs()]
        self.threshold = max(0.0, min(1.0, float(self.threshold)))  # Confidence Threshold
        # Silero VAD requires preceding context samples: 64 at 16 kHz, 32 at 8 kHz.
        self._context_size = 64 if self.sample_rate >= 16000 else 32
        self._context = np.zeros((1, self._context_size), dtype=np.float32)

    def _build_session_options(self) -> ort.SessionOptions:
        options = ort.SessionOptions()
        threads: int = max(1, int(self.onnx_threads))
        # Number of parallel threads.
        # Set this to a value no higher than the number of physical CPU cores.
        # The default is 0 (automatic).
        options.intra_op_num_threads = threads
        # As there are no parallel graph nodes, the value is either 1 or 0 (the default is 1)
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        return options

    def reset(self) -> None:
        self._recording_active = False
        self._silence_duration_sec = 0.0
        self._tail_buffer = np.empty((0,), dtype=np.float32)
        self._state_cache.clear()
        self._context = np.zeros((1, self._context_size), dtype=np.float32)

    def set_thresholds(self, *, start_level: float, stop_level: float) -> None:
        # Silero ONNX mode does not use level thresholds from UI slider.
        _ = start_level, stop_level

    def set_vad_threshold(self, *, threshold: float) -> float:
        """Update and return Silero VAD probability threshold."""
        self.threshold = max(0.0, min(1.0, float(threshold)))
        return self.threshold

    def process_chunk(
        self,
        *,
        chunk: np.ndarray,
        frames: int,
        sample_rate: int,
        rms: float,
        current_segment_frames: int,
    ) -> VADDecision:
        # Contract: frames must equal chunk.shape[0] (guaranteed by STTRecorder callback).
        _ = rms
        if frames <= 0:
            return VADDecision()

        speech_prob: float = self._infer_chunk_speech_probability(chunk=chunk, sample_rate=sample_rate)

        if not self._recording_active:
            if speech_prob >= self.threshold:
                self._recording_active = True
                self._silence_duration_sec = 0.0
                return VADDecision(start_segment=True)
            return VADDecision(push_pre_buffer=True)

        if speech_prob < self.threshold:
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

    def _infer_chunk_speech_probability(self, *, chunk: np.ndarray, sample_rate: int) -> float:
        mono: np.ndarray = self._to_mono_float32(chunk)
        if mono.size == 0:
            return 0.0

        self._tail_buffer = np.concatenate((self._tail_buffer, mono))
        if self._tail_buffer.size < self.window_size:
            return 0.0

        probabilities: list[float] = []
        offset: int = 0
        while offset + self.window_size <= self._tail_buffer.size:
            window = self._tail_buffer[offset : offset + self.window_size]
            probabilities.append(self._run_session(window=window, sample_rate=sample_rate))
            offset += self.window_size

        self._tail_buffer = self._tail_buffer[offset:]
        if not probabilities:
            return 0.0
        return float(max(probabilities))

    @staticmethod
    def _to_mono_float32(chunk: np.ndarray) -> np.ndarray:
        """Convert int16 PCM chunk to mono float32 normalized to [-1.0, 1.0].

        Args:
            chunk: Audio samples in int16 PCM format (values in -32768 to 32767).
                   Multi-channel input is averaged to mono before normalization.
        """
        if chunk.ndim == 2 and chunk.shape[1] > 1:
            mono = np.mean(chunk.astype(np.float32, copy=False), axis=1, dtype=np.float32)
        else:
            mono = chunk.reshape(-1).astype(np.float32, copy=False)
        scaled = mono / 32768.0
        return np.asarray(scaled, dtype=np.float32)

    def _run_session(self, *, window: np.ndarray, sample_rate: int) -> float:
        # Prepend context to the audio window. The Silero VAD model requires this preceding
        # context (64 samples at 16 kHz) to produce meaningful speech probabilities.
        audio: np.ndarray = window.reshape(1, -1).astype(np.float32, copy=False)
        model_input: np.ndarray = np.concatenate([self._context, audio], axis=1)

        # Input routing heuristics for Silero VAD v5 ONNX (inputs: "input", "sr", "state").
        # Check sr/sample_rate first to prevent "sr_input"-style names from matching audio.
        inputs: dict[str, np.ndarray] = {}
        for input_meta in self._session.get_inputs():
            name: str = input_meta.name
            lowered: str = name.lower()

            if "sr" in lowered or "sample_rate" in lowered:
                inputs[name] = np.array(sample_rate, dtype=np.int64)
                continue

            if lowered in {"input", "x", "audio"} or "input" in lowered:
                inputs[name] = model_input
                continue

            if "state" in lowered:
                inputs[name] = self._resolve_state_input(name=name, shape=input_meta.shape)
                continue

            inputs[name] = self._zeros_for_shape(input_meta.shape)

        outputs: Sequence[Any] = self._session.run(None, inputs)
        self._update_state_cache(outputs=outputs)

        # Update context with the last context_size samples of the padded model input.
        self._context = model_input[..., -self._context_size :]

        if not outputs:
            return 0.0
        return float(np.asarray(outputs[0], dtype=np.float32).reshape(-1)[0])

    def _resolve_state_input(self, *, name: str, shape: Sequence[int | str | None]) -> np.ndarray:
        cached: np.ndarray | None = self._state_cache.get(name)
        if cached is not None:
            return cached
        return self._zeros_for_shape(shape)

    def _update_state_cache(self, *, outputs: Sequence[Any]) -> None:
        # Map state outputs to state inputs 1:1 by declaration order.
        # This is correct for Silero VAD v5 (single state [2, 1, 128]) and also handles
        # models with multiple state tensors, avoiding the "last output overwrites all
        # inputs" problem that arises with a naive broadcast approach.
        state_output_indices: list[int] = [
            idx for idx, name in enumerate(self._output_names) if "state" in name.lower() and idx < len(outputs)
        ]
        state_input_names: list[str] = [name for name in self._input_names if "state" in name.lower()]
        for out_idx, in_name in zip(state_output_indices, state_input_names, strict=False):
            self._state_cache[in_name] = np.asarray(outputs[out_idx], dtype=np.float32)

    @staticmethod
    def _zeros_for_shape(shape: Sequence[int | str | None]) -> np.ndarray:
        resolved: list[int] = []
        for dim in shape:
            if isinstance(dim, int) and dim > 0:
                resolved.append(dim)
            else:
                resolved.append(1)
        return np.zeros(tuple(resolved), dtype=np.float32)

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from core.stt.vad.silero_onnx import SileroOnnxVADProcessor


class _FakeMeta:
    def __init__(self, name: str, shape: list[int | str | None]) -> None:
        self.name = name
        self.shape = shape


class _FakeSession:
    def __init__(self, probs: list[float]) -> None:
        self._inputs = [
            _FakeMeta("input", [1, 512]),
            _FakeMeta("sr", [1]),
            _FakeMeta("state", [2, 1, 128]),
        ]
        self._outputs = [
            _FakeMeta("output", [1, 1]),
            _FakeMeta("state_out", [2, 1, 128]),
        ]
        self._probs = deque(probs)
        self.run_inputs: list[dict[str, np.ndarray]] = []

    def get_inputs(self) -> list[_FakeMeta]:
        return self._inputs

    def get_outputs(self) -> list[_FakeMeta]:
        return self._outputs

    def run(self, _output_names: Any, inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        self.run_inputs.append(inputs)
        prob: float = self._probs.popleft() if self._probs else 0.0
        state_out = np.full((2, 1, 128), fill_value=0.25, dtype=np.float32)
        return [np.array([prob], dtype=np.float32), state_out]


def _build_processor(monkeypatch: pytest.MonkeyPatch, probs: list[float], **kwargs: Any) -> _FakeSession:
    fake_session = _FakeSession(probs=probs)

    def fake_inference_session(*args: Any, **inner_kwargs: Any) -> _FakeSession:
        _ = args, inner_kwargs
        return fake_session

    monkeypatch.setattr("core.stt.vad.silero_onnx.ort.InferenceSession", fake_inference_session)

    defaults: dict[str, Any] = {
        "model_path": "data/stt/silero/silero_vad.onnx",
        "threshold": 0.5,
        "post_buffer_ms": 20,
        "max_segment_sec": 1,
        "sample_rate": 16000,
        "window_size": 512,
    }
    defaults.update(kwargs)

    _ = SileroOnnxVADProcessor(**defaults)
    return fake_session


def test_process_chunk_starts_segment_when_probability_is_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_processor(monkeypatch, probs=[0.9])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=1,
        sample_rate=16000,
    )

    decision = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=0,
    )

    assert decision.start_segment is True
    assert decision.push_pre_buffer is False


def test_process_chunk_pushes_pre_buffer_when_probability_is_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_processor(monkeypatch, probs=[0.1])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=1,
        sample_rate=16000,
    )

    decision = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=0,
    )

    assert decision.push_pre_buffer is True
    assert decision.start_segment is False


def test_process_chunk_flushes_by_silence_after_recording_started(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_processor(monkeypatch, probs=[0.9, 0.1])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=10,
        sample_rate=16000,
    )

    _ = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=0,
    )

    decision = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=512,
    )

    assert decision.append_to_segment is True
    assert decision.flush_segment is True


def test_process_chunk_flushes_by_max_segment_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_processor(monkeypatch, probs=[0.9, 0.9])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=1000,
        max_segment_sec=1,
        sample_rate=16000,
    )

    _ = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=0,
    )

    decision = processor.process_chunk(
        chunk=np.zeros((8000, 1), dtype=np.int16),
        frames=8000,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=8000,
    )

    assert decision.append_to_segment is True
    assert decision.flush_segment is True


def test_process_chunk_reuses_state_output_as_next_state_input(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session = _build_processor(monkeypatch, probs=[0.9, 0.9])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=10,
        sample_rate=16000,
    )

    _ = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=0,
    )
    _ = processor.process_chunk(
        chunk=np.zeros((512, 1), dtype=np.int16),
        frames=512,
        sample_rate=16000,
        rms=0.0,
        current_segment_frames=512,
    )

    assert len(fake_session.run_inputs) >= 2
    first_state = fake_session.run_inputs[0]["state"]
    second_state = fake_session.run_inputs[1]["state"]
    assert np.allclose(first_state, 0.0)
    assert np.allclose(second_state, 0.25)


def test_post_init_applies_onnx_thread_setting_to_session_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_options: dict[str, Any] = {}

    class _SessionCaptureFakeSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__(probs=[0.0])

    def fake_inference_session(*args: Any, **inner_kwargs: Any) -> _SessionCaptureFakeSession:
        _ = args
        captured_options["sess_options"] = inner_kwargs.get("sess_options")
        return _SessionCaptureFakeSession()

    monkeypatch.setattr("core.stt.vad.silero_onnx.ort.InferenceSession", fake_inference_session)

    _ = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=1,
        sample_rate=16000,
        onnx_threads=3,
    )

    sess_options = captured_options.get("sess_options")
    assert sess_options is not None
    assert sess_options.intra_op_num_threads == 3
    assert sess_options.inter_op_num_threads == 1


def test_set_vad_threshold_clamps_to_valid_range(monkeypatch: pytest.MonkeyPatch) -> None:
    _build_processor(monkeypatch, probs=[0.0])
    processor = SileroOnnxVADProcessor(
        model_path=Path("data/stt/silero/silero_vad.onnx"),
        threshold=0.5,
        post_buffer_ms=20,
        max_segment_sec=1,
        sample_rate=16000,
    )

    applied_high = processor.set_vad_threshold(threshold=1.8)
    applied_low = processor.set_vad_threshold(threshold=-0.1)

    assert applied_high == pytest.approx(1.0)
    assert applied_low == pytest.approx(0.0)

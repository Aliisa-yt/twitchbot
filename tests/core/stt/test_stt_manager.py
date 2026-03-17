from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from core.stt.interface import STTInterface, STTResult
from core.stt.manager import STTManager

if TYPE_CHECKING:
    from models.config_models import Config


class _FakeRecorder:
    last_instance: _FakeRecorder | None = None
    last_kwargs: dict[str, Any] | None = None

    def __init__(self, **kwargs: Any) -> None:
        _FakeRecorder.last_kwargs = kwargs
        self.start_level = 0.6
        self.stop_level = 0.4
        self.muted = False
        self.started_with_callback = None
        self.closed = False
        self.vad_threshold = 0.5
        _FakeRecorder.last_instance = self

    def set_mute(self, *, mute: bool) -> None:
        self.muted = mute

    async def start_input_monitoring(self, on_level_event=None) -> None:
        self.started_with_callback = on_level_event

    async def close(self) -> None:
        self.closed = True

    def set_vad_threshold(self, *, threshold: float) -> float:
        self.vad_threshold = max(0.0, min(1.0, float(threshold)))
        return self.vad_threshold


class _FailingRecorder(_FakeRecorder):
    async def start_input_monitoring(self, on_level_event=None) -> None:
        _ = on_level_event
        msg = "invalid input device"
        raise RuntimeError(msg)


class _FakeProcessor:
    def __init__(self, **kwargs: Any) -> None:
        _ = kwargs

    async def run(self) -> None:
        return None


class _FakeEngine:
    @property
    def is_available(self) -> bool:
        return True

    @staticmethod
    def fetch_engine_name() -> str:
        return "fake_stt"

    def initialize(self, _config) -> None:
        return None

    def transcribe(self, _stt_input) -> STTResult:
        return STTResult(text="", language="ja-JP")


def _make_config(*, enabled: bool = True) -> SimpleNamespace:
    stt = SimpleNamespace(
        ENABLED=enabled,
        ENGINE="",
        SAMPLE_RATE=16000,
        CHANNELS=1,
        INPUT_DEVICE="default",
        START_LEVEL=0.6,
        STOP_LEVEL=0.4,
        PRE_BUFFER_MS=300,
        POST_BUFFER_MS=500,
        MAX_SEGMENT_SEC=20,
        LANGUAGE="ja-JP",
        RETRY_MAX=3,
        RETRY_BACKOFF_MS=500,
        MUTE=False,
    )
    general = SimpleNamespace(TMP_DIR="tmp")
    gui = SimpleNamespace(LEVEL_METER_REFRESH_RATE="10")
    return SimpleNamespace(STT=stt, GENERAL=general, GUI=gui)


@pytest.mark.asyncio
async def test_async_init_uses_pre_registered_level_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.stt.manager.STTRecorder", _FakeRecorder)
    monkeypatch.setattr("core.stt.manager.STTProcessor", _FakeProcessor)

    config = _make_config(enabled=True)
    config.STT.ENGINE = "fake_stt"
    monkeypatch.setitem(STTInterface.registered, "fake_stt", _FakeEngine)

    manager = STTManager(cast("Config", config))

    async def on_level(_event) -> None:
        return None

    manager.set_level_event_callback(on_level)
    await manager.async_init(on_result=None)

    recorder = _FakeRecorder.last_instance
    assert recorder is not None
    assert recorder.started_with_callback is on_level

    await manager.close()


@pytest.mark.asyncio
async def test_async_init_prefers_explicit_level_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.stt.manager.STTRecorder", _FakeRecorder)
    monkeypatch.setattr("core.stt.manager.STTProcessor", _FakeProcessor)
    config = _make_config(enabled=True)
    config.STT.ENGINE = "fake_stt"
    monkeypatch.setitem(STTInterface.registered, "fake_stt", _FakeEngine)

    manager = STTManager(cast("Config", config))

    async def old_callback(_event) -> None:
        return None

    async def new_callback(_event) -> None:
        return None

    manager.set_level_event_callback(old_callback)
    await manager.async_init(on_result=None, on_level_event=new_callback)

    recorder = _FakeRecorder.last_instance
    assert recorder is not None
    assert recorder.started_with_callback is new_callback

    await manager.close()


@pytest.mark.asyncio
async def test_async_init_disabled_does_not_create_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.stt.manager.STTRecorder", _FakeRecorder)
    monkeypatch.setattr("core.stt.manager.STTProcessor", _FakeProcessor)

    _FakeRecorder.last_instance = None
    manager = STTManager(cast("Config", _make_config(enabled=False)))

    async def on_level(_event) -> None:
        return None

    manager.set_level_event_callback(on_level)
    await manager.async_init(on_result=None)

    assert manager.enabled is False
    assert manager.recorder is None
    assert _FakeRecorder.last_instance is None


@pytest.mark.asyncio
async def test_async_init_when_input_monitoring_fails_keeps_manager_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.stt.manager.STTRecorder", _FailingRecorder)
    monkeypatch.setattr("core.stt.manager.STTProcessor", _FakeProcessor)

    config = _make_config(enabled=True)
    config.STT.ENGINE = "fake_stt"
    monkeypatch.setitem(STTInterface.registered, "fake_stt", _FakeEngine)

    manager = STTManager(cast("Config", config))
    await manager.async_init(on_result=None)

    assert manager.enabled is False
    assert len(manager._background_tasks) == 0

    await manager.close()


@pytest.mark.asyncio
async def test_async_init_passes_vad_settings_to_recorder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.stt.manager.STTRecorder", _FakeRecorder)
    monkeypatch.setattr("core.stt.manager.STTProcessor", _FakeProcessor)

    config = _make_config(enabled=True)
    config.STT.ENGINE = "fake_stt"
    config.STT.VAD_MODE = "silero_onnx"
    config.STT.VAD_SILERO_MODEL_PATH = "data/stt/silero/silero_vad.onnx"
    config.STT.VAD_THRESHOLD = 0.42
    config.STT.VAD_ONNX_THREADS = 2
    monkeypatch.setitem(STTInterface.registered, "fake_stt", _FakeEngine)

    manager = STTManager(cast("Config", config))
    await manager.async_init(on_result=None)

    assert _FakeRecorder.last_kwargs is not None
    assert _FakeRecorder.last_kwargs["vad_mode"] == "silero_onnx"
    assert _FakeRecorder.last_kwargs["vad_silero_model_path"] == "data/stt/silero/silero_vad.onnx"
    assert _FakeRecorder.last_kwargs["vad_threshold"] == pytest.approx(0.42)
    assert _FakeRecorder.last_kwargs["vad_onnx_threads"] == 2

    await manager.close()


def test_set_vad_threshold_delegates_to_recorder() -> None:
    manager = STTManager(cast("Config", _make_config(enabled=True)))
    manager._recorder = cast("Any", _FakeRecorder())

    applied = manager.set_vad_threshold(threshold=0.73)
    recorder = cast("Any", manager._recorder)

    assert applied == pytest.approx(0.73)
    assert recorder.vad_threshold == pytest.approx(0.73)


def test_set_vad_threshold_raises_when_recorder_missing() -> None:
    manager = STTManager(cast("Config", _make_config(enabled=True)))

    with pytest.raises(RuntimeError, match="STT recorder is not initialized"):
        _ = manager.set_vad_threshold(threshold=0.5)

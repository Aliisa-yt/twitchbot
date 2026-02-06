# ruff: noqa: N802

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pythoncom = pytest.importorskip("pythoncom")
pytest.importorskip("win32com.client")

cevio_core: ModuleType = importlib.import_module("core.tts.engines.cevio_core")
CevioCore = cevio_core.CevioCore

from models.voice_models import TTSInfo, TTSParam, Voice  # noqa: E402


class FakeStringArray:
    def __init__(self, items: list[str]) -> None:
        self._items: list[str] = items
        self.Length: int = len(items)

    def At(self, idx: int) -> str:
        return self._items[idx]


class FakeTalker:
    def __init__(self, presets: dict[str, Voice]) -> None:
        self._presets: dict[str, Voice] = presets
        self.AvailableCasts = FakeStringArray(list(presets.keys()))
        self._cast: str = ""
        self.Volume: int = 0
        self.Speed: int = 0
        self.Tone: int = 0
        self.Alpha: int = 0
        self.ToneScale: int = 0
        self.output_calls: list[tuple[str, Path]] = []
        self.output_result: bool = True

    @property
    def Cast(self) -> str:
        return self._cast

    @Cast.setter
    def Cast(self, value: str) -> None:
        self._cast = value
        preset: Voice | None = self._presets.get(value)
        if preset is not None:
            self.Volume = preset.volume or 0
            self.Speed = preset.speed or 0
            self.Tone = preset.tone or 0
            self.Alpha = preset.alpha or 0
            self.ToneScale = preset.intonation or 0

    def OutputWaveToFile(self, content: str, path: Path) -> bool:
        self.output_calls.append((content, path))
        return self.output_result


def test_init_rejects_invalid_cevio_type() -> None:
    msg = "Unsupported CeVIO type: bad"
    with pytest.raises(ValueError, match=msg):
        CevioCore(cevio_type="bad")


def test_get_apiname_returns_expected_values() -> None:
    control, talk = CevioCore._get_apiname("AI")
    assert control == "CeVIO.Talk.RemoteService2.ServiceControl2V40"
    assert talk == "CeVIO.Talk.RemoteService2.Talker2V40"

    control, talk = CevioCore._get_apiname("CS7")
    assert control == "CeVIO.Talk.RemoteService.ServiceControlV40"
    assert talk == "CeVIO.Talk.RemoteService.TalkerV40"

    control, talk = CevioCore._get_apiname("bad")
    assert (control, talk) == ("", "")


def test_connect_cevio_handles_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = CevioCore(cevio_type="AI")
    monkeypatch.setattr(cevio_core.platform, "system", lambda: "Linux")

    assert engine.connect_cevio("AI") is False


def test_connect_cevio_dispatch_failure_calls_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyComError(Exception):
        pass

    engine = CevioCore(cevio_type="AI")

    monkeypatch.setattr(cevio_core.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cevio_core, "com_error", DummyComError)
    init_mock = MagicMock()
    uninit_mock = MagicMock()
    monkeypatch.setattr(pythoncom, "CoInitializeEx", init_mock)
    monkeypatch.setattr(pythoncom, "CoUninitialize", uninit_mock)
    monkeypatch.setattr(cevio_core.win32com.client, "Dispatch", MagicMock(side_effect=DummyComError("boom")))

    assert engine.connect_cevio("AI") is False
    init_mock.assert_called_once()
    uninit_mock.assert_called_once()


def test_connect_cevio_start_host_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyComError(Exception):
        pass

    engine = CevioCore(cevio_type="AI")
    engine._Interface__tts_config.linkedstartup = True

    monkeypatch.setattr(cevio_core.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cevio_core, "com_error", DummyComError)
    init_mock = MagicMock()
    uninit_mock = MagicMock()
    monkeypatch.setattr(pythoncom, "CoInitializeEx", init_mock)
    monkeypatch.setattr(pythoncom, "CoUninitialize", uninit_mock)

    control = SimpleNamespace(StartHost=MagicMock(return_value=1))
    dispatch_mock = MagicMock(return_value=control)
    monkeypatch.setattr(cevio_core.win32com.client, "Dispatch", dispatch_mock)

    assert engine.connect_cevio("AI") is False
    dispatch_mock.assert_called_once()
    uninit_mock.assert_called_once()


def test_get_preset_parameters_collects_casts() -> None:
    engine = CevioCore(cevio_type="AI")
    presets: dict[str, Voice] = {
        "A": Voice(cast="A", volume=10, tone=20, speed=30, alpha=40, intonation=50),
        "B": Voice(cast="B", volume=11, tone=21, speed=31, alpha=41, intonation=51),
    }
    talker = FakeTalker(presets)

    result = engine._get_preset_parameters(talker)

    assert set(result) == {"A", "B"}
    assert result["A"].volume == 10
    assert result["B"].intonation == 51


@pytest.mark.asyncio
async def test_speech_synthesis_uses_thread_and_play(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = CevioCore(cevio_type="AI")
    tts_param = TTSParam(content="hello")

    async def fake_to_thread(func, *args, **kwargs) -> None:
        func(*args, **kwargs)

    monkeypatch.setattr(cevio_core.asyncio, "to_thread", fake_to_thread)
    engine._speech_synthesis_main = MagicMock()
    engine.play = AsyncMock()

    await engine.speech_synthesis(tts_param)
    engine._speech_synthesis_main.assert_called_once_with(tts_param)
    engine.play.assert_called_once_with(tts_param)


def test_speech_synthesis_main_generates_wave_file(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = CevioCore(cevio_type="AI")
    engine.cevio = SimpleNamespace(IsHostStarted=True)
    engine._Interface__tts_config.earlyspeech = True

    preset = Voice(cast="alpha", volume=10, tone=20, speed=30, alpha=40, intonation=50)
    engine.talk_preset = {"alpha": preset}
    talker = FakeTalker(engine.talk_preset)
    engine.talker = talker

    tts_info = TTSInfo(voice=Voice(cast="alpha", volume=80, speed=15))
    tts_param = TTSParam(content="x" * 40, tts_info=tts_info)

    monkeypatch.setattr(engine, "create_audio_filename", lambda **_kwargs: Path("voice.wav"))
    monkeypatch.setattr(engine, "_adjust_cevio_speed", lambda _base, _len: 55)

    engine._speech_synthesis_main(tts_param)

    assert talker.Volume == 80
    assert talker.Speed == 55
    assert tts_param.filepath == Path("voice.wav")
    assert talker.output_calls == [("x" * 40, Path("voice.wav"))]


def test_speech_synthesis_main_skips_on_missing_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = CevioCore(cevio_type="AI")
    engine.cevio = SimpleNamespace(IsHostStarted=True)
    engine.talker = FakeTalker({})
    engine.talk_preset = {}

    tts_info = TTSInfo(voice=Voice(cast="missing"))
    tts_param = TTSParam(content="hello", tts_info=tts_info)

    monkeypatch.setattr(engine, "_get_preset_parameters", lambda _talker: {})

    engine._speech_synthesis_main(tts_param)

    assert tts_param.filepath is None


def test_adjust_cevio_speed_caps_and_handles_short_text() -> None:
    engine = CevioCore(cevio_type="AI")
    assert engine._adjust_cevio_speed(10, 30) == 10
    assert engine._adjust_cevio_speed(50, 200) <= 60

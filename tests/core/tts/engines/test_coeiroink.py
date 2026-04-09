"""Unit tests for core.tts.engines.coeiroink module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.tts.engines import coeiroink as coeiroink_module
from core.tts.engines import vv_core as vv_core_module
from core.tts.tts_interface import EngineContext
from models.voice_models import TTSInfo, TTSParam, Voice
from models.voicevox_models import AudioQueryType

if TYPE_CHECKING:
    from pathlib import Path

    from models.config_models import TTSEngine


class FakeAsyncHttp:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()
        self.post: AsyncMock = AsyncMock()
        self.close: AsyncMock = AsyncMock()

    def initialize_session(self) -> None:
        return None

    def add_handler(self, _content_type: str, _handler) -> None:
        return None


def _create_audio_query(
    *, pause_length: float | None = None, pause_length_scale: float | None = None
) -> AudioQueryType:
    return AudioQueryType.from_dict(
        {
            "accent_phrases": [],
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
            "volumeScale": 1.0,
            "prePhonemeLength": 0.1,
            "postPhonemeLength": 0.1,
            "pauseLength": pause_length,
            "pauseLengthScale": pause_length_scale,
            "outputSamplingRate": 24000,
            "outputStereo": False,
            "kana": "テスト",
        }
    )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> coeiroink_module.CoeiroInk:
    monkeypatch.setattr(vv_core_module, "AsyncHttp", FakeAsyncHttp)
    coeiroink = coeiroink_module.CoeiroInk()
    config = SimpleNamespace(
        SERVER="http://localhost:50031",
        TIMEOUT=3.0,
        EARLY_SPEECH=True,
        AUTO_STARTUP=False,
        EXECUTE_PATH=str(tmp_path / "coeiroink.exe"),
    )
    context = EngineContext(audio_save_directory=tmp_path, play_callback=AsyncMock())
    coeiroink.initialize_engine(cast("TTSEngine", config), context)
    return coeiroink


@pytest.fixture
def available_speakers() -> dict[str, dict[str, vv_core_module.SpeakerID]]:
    return {
        "ついなちゃん": {
            "ノーマル": vv_core_module.SpeakerID(uuid="uuid-tuina", style_id=10),
        },
    }


# ---------------------------------------------------------------------------
# fetch_engine_name
# ---------------------------------------------------------------------------


def test_fetch_engine_name_returns_coeiroink() -> None:
    assert coeiroink_module.CoeiroInk.fetch_engine_name() == "coeiroink"


# ---------------------------------------------------------------------------
# initialize_engine
# ---------------------------------------------------------------------------


def test_initialize_engine_sets_url_and_timeout(engine: coeiroink_module.CoeiroInk) -> None:
    # CoeiroInk.initialize_engine calls super(VoiceVox, self).initialize_engine → VVCore → Interface
    assert engine.url == "http://localhost:50031"
    assert engine.timeout == 3.0


# ---------------------------------------------------------------------------
# _set_synthesis_parameters: difference from VoiceVox
# ---------------------------------------------------------------------------


def test_set_synthesis_parameters_does_not_set_pause_length(
    engine: coeiroink_module.CoeiroInk,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CoeiroInk does NOT set pauseLength/pauseLengthScale unlike VoiceVox."""
    engine.available_speakers = available_speakers

    initial_pause = 0.5
    initial_pause_scale = 2.0
    audio_query = _create_audio_query(pause_length=initial_pause, pause_length_scale=initial_pause_scale)

    monkeypatch.setattr(engine, "_convert_parameters", MagicMock(return_value=1.0))
    monkeypatch.setattr(engine, "_adjust_reading_speed", MagicMock(return_value=1.0))

    tts_param = TTSParam(content="hello", tts_info=TTSInfo(voice=Voice(cast="ついなちゃん|ノーマル")))

    engine._set_synthesis_parameters(audio_query, tts_param)

    # pauseLength and pauseLengthScale must remain unchanged
    assert audio_query.pauseLength == initial_pause
    assert audio_query.pauseLengthScale == initial_pause_scale


def test_set_synthesis_parameters_sets_expected_fields(
    engine: coeiroink_module.CoeiroInk,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine.available_speakers = available_speakers

    convert_mock = MagicMock(side_effect=[1.1, 0.01, 1.3, 0.9])
    adjust_mock = MagicMock(return_value=1.2)
    monkeypatch.setattr(engine, "_convert_parameters", convert_mock)
    monkeypatch.setattr(engine, "_adjust_reading_speed", adjust_mock)

    audio_query = _create_audio_query(pause_length=None, pause_length_scale=None)
    tts_param = TTSParam(
        content="hello",
        tts_info=TTSInfo(voice=Voice(cast="ついなちゃん|ノーマル", speed=110, tone=10, intonation=130, volume=90)),
    )

    engine._set_synthesis_parameters(audio_query, tts_param)

    adjust_mock.assert_called_once_with(1.1, len("hello"))
    assert audio_query.speedScale == 1.2
    assert audio_query.pitchScale == 0.01
    assert audio_query.intonationScale == 1.3
    assert audio_query.volumeScale == 0.9
    assert audio_query.prePhonemeLength == 0.05
    assert audio_query.postPhonemeLength == 0.05
    assert audio_query.outputSamplingRate == 24000
    assert audio_query.outputStereo is False

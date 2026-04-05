"""Unit tests for core.tts.engines.coeiroink_v2 module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.tts.engines import coeiroink_v2 as coeiroink_v2_module
from core.tts.engines import vv_core as vv_core_module
from core.tts.tts_interface import EngineContext
from models.coeiroink_v2_models import Prosody, SpeakerMeta, WavMakingParam, WavProcessingParam, WavWithDuration
from models.voice_models import TTSInfo, TTSParam, UserTypeInfo, Voice

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


def _make_speaker_meta(name: str, uuid: str, style_name: str, style_id: int) -> SpeakerMeta:
    return SpeakerMeta.from_dict(
        {
            "speakerName": name,
            "speakerUuid": uuid,
            "styles": [
                {
                    "styleName": style_name,
                    "styleId": style_id,
                    "base64Icon": "",
                    "base64Portrait": None,
                }
            ],
            "version": "2.0.0",
            "base64Portrait": "",
        }
    )


def _make_prosody() -> Prosody:
    return Prosody(plain=["こんにちは"], detail=[[]])


def _make_wav_with_duration() -> WavWithDuration:
    return WavWithDuration(
        wav_base64="dGVzdA==",
        mora_durations=[],
        start_trim_buffer=0.05,
        end_trim_buffer=0.05,
    )


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> coeiroink_v2_module.CoeiroInk2:
    monkeypatch.setattr(vv_core_module, "AsyncHttp", FakeAsyncHttp)
    engine = coeiroink_v2_module.CoeiroInk2()
    config = SimpleNamespace(
        SERVER="http://localhost:50032",
        TIMEOUT=3.0,
        EARLY_SPEECH=False,
        AUTO_STARTUP=False,
        EXECUTE_PATH=str(tmp_path / "coeiroink.exe"),
    )
    context = EngineContext(audio_save_directory=tmp_path, play_callback=AsyncMock())
    engine.initialize_engine(cast("TTSEngine", config), context)
    return engine


@pytest.fixture
def available_speakers() -> dict[str, dict[str, vv_core_module.SpeakerID]]:
    return {
        "つくよみちゃん": {
            "れいせい": vv_core_module.SpeakerID(uuid="uuid-tsuku", style_id=0),
        },
        "おふとんP": {
            "ノーマル": vv_core_module.SpeakerID(uuid="uuid-ofuton", style_id=1),
        },
    }


# ---------------------------------------------------------------------------
# fetch_engine_name
# ---------------------------------------------------------------------------


def test_fetch_engine_name_returns_coeiroink2() -> None:
    assert coeiroink_v2_module.CoeiroInk2.fetch_engine_name() == "coeiroink2"


# ---------------------------------------------------------------------------
# initialize_engine
# ---------------------------------------------------------------------------


def test_initialize_engine_sets_common_config(engine: coeiroink_v2_module.CoeiroInk2) -> None:
    assert engine.url == "http://localhost:50032"
    assert engine.timeout == 3.0


# ---------------------------------------------------------------------------
# async_init
# ---------------------------------------------------------------------------


async def test_async_init_sets_check_status_command_and_fetches_speakers(
    engine: coeiroink_v2_module.CoeiroInk2,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_async_init = AsyncMock(return_value=None)
    monkeypatch.setattr(vv_core_module.VVCore, "async_init", super_async_init)
    fetch_mock = AsyncMock(return_value=available_speakers)
    monkeypatch.setattr(engine, "fetch_available_speakers", fetch_mock)

    param = UserTypeInfo(streamer={"ja": TTSInfo(engine="coeiroink2", voice=Voice(cast="つくよみちゃん|れいせい"))})
    await engine.async_init(param)

    assert engine.check_status_command == "/v1/engine_info"
    super_async_init.assert_awaited_once_with(param)
    fetch_mock.assert_awaited_once()
    assert engine.available_speakers == available_speakers


# ---------------------------------------------------------------------------
# fetch_available_speakers
# ---------------------------------------------------------------------------


async def test_fetch_available_speakers_calls_api_and_builds_map(
    engine: coeiroink_v2_module.CoeiroInk2,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    speakers = [
        _make_speaker_meta("つくよみちゃん", "uuid-tsuku", "れいせい", 0),
        _make_speaker_meta("おふとんP", "uuid-ofuton", "ノーマル", 1),
    ]
    api_request_mock = AsyncMock(return_value=speakers)
    monkeypatch.setattr(engine, "_api_request", api_request_mock)

    result = await engine.fetch_available_speakers()

    api_request_mock.assert_awaited_once_with(
        method="get",
        url="http://localhost:50032/v1/speakers",
        model=SpeakerMeta,
        is_list=True,
        log_action="GET speakers",
    )
    assert result["つくよみちゃん"]["れいせい"].uuid == "uuid-tsuku"
    assert result["おふとんP"]["ノーマル"].style_id == 1


# ---------------------------------------------------------------------------
# _build_speaker_id_map
# ---------------------------------------------------------------------------


def test_build_speaker_id_map_creates_nested_lookup(engine: coeiroink_v2_module.CoeiroInk2) -> None:
    speakers = [
        _make_speaker_meta("つくよみちゃん", "uuid-tsuku", "れいせい", 0),
        _make_speaker_meta("おふとんP", "uuid-ofuton", "ノーマル", 1),
    ]

    result = engine._build_speaker_id_map(speakers)

    assert result == {
        "つくよみちゃん": {"れいせい": vv_core_module.SpeakerID(uuid="uuid-tsuku", style_id=0)},
        "おふとんP": {"ノーマル": vv_core_module.SpeakerID(uuid="uuid-ofuton", style_id=1)},
    }


def test_build_speaker_id_map_with_multiple_styles(engine: coeiroink_v2_module.CoeiroInk2) -> None:
    speaker = SpeakerMeta.from_dict(
        {
            "speakerName": "マルチスタイル",
            "speakerUuid": "uuid-multi",
            "styles": [
                {"styleName": "ノーマル", "styleId": 10, "base64Icon": "", "base64Portrait": None},
                {"styleName": "ささやき", "styleId": 11, "base64Icon": "", "base64Portrait": None},
            ],
            "version": "2.0.0",
            "base64Portrait": "",
        }
    )

    result = engine._build_speaker_id_map([speaker])

    assert result["マルチスタイル"]["ノーマル"] == vv_core_module.SpeakerID(uuid="uuid-multi", style_id=10)
    assert result["マルチスタイル"]["ささやき"] == vv_core_module.SpeakerID(uuid="uuid-multi", style_id=11)


# ---------------------------------------------------------------------------
# _get_speaker_uuid
# ---------------------------------------------------------------------------


def test_get_speaker_uuid_resolves_from_available_speakers(
    engine: coeiroink_v2_module.CoeiroInk2,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
) -> None:
    engine.available_speakers = available_speakers
    tts_param = TTSParam(content="hello", tts_info=TTSInfo(voice=Voice(cast="つくよみちゃん|れいせい")))

    uuid = engine._get_speaker_uuid(tts_param)

    assert uuid == "uuid-tsuku"


def test_get_speaker_uuid_uses_default_when_cast_is_invalid(
    engine: coeiroink_v2_module.CoeiroInk2,
) -> None:
    engine.available_speakers = {}
    tts_param = TTSParam(content="hello", tts_info=TTSInfo(voice=Voice(cast="存在しない話者")))

    uuid = engine._get_speaker_uuid(tts_param)

    assert uuid == coeiroink_v2_module.DEFAULT_UUID


# ---------------------------------------------------------------------------
# _set_wav_making_param
# ---------------------------------------------------------------------------


def test_set_wav_making_param_uses_style_id_zero(
    engine: coeiroink_v2_module.CoeiroInk2,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine.available_speakers = available_speakers
    convert_mock = MagicMock(return_value=1.2)
    adjust_mock = MagicMock(return_value=1.3)
    monkeypatch.setattr(engine, "_convert_parameters", convert_mock)
    monkeypatch.setattr(engine, "_adjust_reading_speed", adjust_mock)

    prosody = _make_prosody()
    tts_param = TTSParam(
        content="こんにちは",
        tts_info=TTSInfo(voice=Voice(cast="つくよみちゃん|れいせい", speed=110)),
    )

    result = engine._set_wav_making_param(tts_param, prosody)

    assert isinstance(result, WavMakingParam)
    # style_id is always 0 (per CoeiroInk2 spec)
    assert result.style_id == 0
    assert result.text == "こんにちは"
    assert result.prosody_detail == prosody.detail
    assert result.speed_scale == 1.3
    adjust_mock.assert_called_once_with(1.2, len("こんにちは"))


# ---------------------------------------------------------------------------
# _set_wav_processing_param
# ---------------------------------------------------------------------------


def test_set_wav_processing_param_fixes_pitch_and_intonation(
    engine: coeiroink_v2_module.CoeiroInk2,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pitch_scale must be 0.0 and intonation_scale must be 1.0 regardless of voice params
    to avoid internal server error in CoeiroInk2 GPU version 2.12.x."""
    convert_mock = MagicMock(return_value=0.9)
    monkeypatch.setattr(engine, "_convert_parameters", convert_mock)

    wav_with_duration = _make_wav_with_duration()
    tts_param = TTSParam(
        content="test",
        tts_info=TTSInfo(voice=Voice(volume=80, tone=120, intonation=150)),
    )

    result = engine._set_wav_processing_param(tts_param, wav_with_duration)

    assert isinstance(result, WavProcessingParam)
    assert result.pitch_scale == 0.0
    assert result.intonation_scale == 1.0


def test_set_wav_processing_param_sets_volume_and_fixed_values(
    engine: coeiroink_v2_module.CoeiroInk2,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert_mock = MagicMock(return_value=0.8)
    monkeypatch.setattr(engine, "_convert_parameters", convert_mock)

    wav_with_duration = _make_wav_with_duration()
    tts_param = TTSParam(
        content="test",
        tts_info=TTSInfo(voice=Voice(volume=80)),
    )

    result = engine._set_wav_processing_param(tts_param, wav_with_duration)

    assert result.volume_scale == 0.8
    assert result.pre_phoneme_length == 0.05
    assert result.post_phoneme_length == 0.05
    assert result.output_sampling_rate == 44100
    assert result.sampled_interval_value == 0
    assert result.adjusted_f0 == []
    assert result.processing_algorithm == "coeiroink"
    assert result.pause_length == 0.25
    assert result.pause_start_trim_buffer == 0.0
    assert result.pause_end_trim_buffer == 0.0
    assert result.start_trim_buffer == wav_with_duration.start_trim_buffer
    assert result.end_trim_buffer == wav_with_duration.end_trim_buffer
    assert result.wav_base64 == wav_with_duration.wav_base64
    assert result.mora_durations == wav_with_duration.mora_durations


# ---------------------------------------------------------------------------
# api_command_procedure
# ---------------------------------------------------------------------------


async def test_api_command_procedure_calls_three_api_endpoints(
    engine: coeiroink_v2_module.CoeiroInk2,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine.available_speakers = available_speakers

    prosody = _make_prosody()
    wav_with_duration = _make_wav_with_duration()
    wav_bytes = b"wav-audio-data"
    api_request_mock = AsyncMock(side_effect=[prosody, wav_with_duration, wav_bytes])
    monkeypatch.setattr(engine, "_api_request", api_request_mock)

    tts_param = TTSParam(
        content="こんにちは",
        tts_info=TTSInfo(voice=Voice(cast="つくよみちゃん|れいせい", speed=100, volume=100)),
    )

    result = await engine.api_command_procedure(tts_param)

    assert result == wav_bytes
    assert api_request_mock.await_count == 3

    # First call: estimate_prosody
    first_call = api_request_mock.await_args_list[0]
    assert first_call.kwargs["method"] == "post"
    assert first_call.kwargs["url"] == "http://localhost:50032/v1/estimate_prosody"
    assert first_call.kwargs["model"] == Prosody
    assert first_call.kwargs["data"] == {"text": "こんにちは"}

    # Second call: predict_with_duration
    second_call = api_request_mock.await_args_list[1]
    assert second_call.kwargs["method"] == "post"
    assert second_call.kwargs["url"] == "http://localhost:50032/v1/predict_with_duration"
    assert second_call.kwargs["model"] == WavWithDuration

    # Third call: process
    third_call = api_request_mock.await_args_list[2]
    assert third_call.kwargs["method"] == "post"
    assert third_call.kwargs["url"] == "http://localhost:50032/v1/process"
    assert third_call.kwargs["model"] is None

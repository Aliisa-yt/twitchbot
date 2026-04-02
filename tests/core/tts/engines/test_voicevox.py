"""Unit tests for core.tts.engines.voicevox module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from core.tts.engines import voicevox as voicevox_module
from core.tts.engines import vv_core as vv_core_module
from core.tts.tts_interface import EngineContext
from handlers.async_comm import AsyncCommError
from models.voice_models import TTSInfo, TTSParam, UserTypeInfo, Voice
from models.voicevox_models import AudioQueryType, Speaker

if TYPE_CHECKING:
    from pathlib import Path


class FakeAsyncHttp:
    def __init__(self) -> None:
        self.get: AsyncMock = AsyncMock()
        self.post: AsyncMock = AsyncMock()
        self.close: AsyncMock = AsyncMock()

    def initialize_session(self) -> None:
        return None

    def add_handler(self, _content_type: str, _handler) -> None:
        return None


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> voicevox_module.VoiceVox:
    monkeypatch.setattr(vv_core_module, "AsyncHttp", FakeAsyncHttp)
    voicevox = voicevox_module.VoiceVox()
    config = SimpleNamespace(
        SERVER="http://localhost:50021",
        TIMEOUT=3.0,
        EARLY_SPEECH=True,
        AUTO_STARTUP=False,
        EXECUTE_PATH=str(tmp_path / "voicevox_engine.exe"),
    )
    context = EngineContext(audio_save_directory=tmp_path, play_callback=AsyncMock())
    voicevox.initialize_engine(cast("voicevox_module.TTSEngine", config), context)
    return voicevox


@pytest.fixture
def available_speakers() -> dict[str, dict[str, vv_core_module.SpeakerID]]:
    return {
        "四国めたん": {
            "ノーマル": vv_core_module.SpeakerID(uuid="uuid-metan", style_id=2),
        },
        "ずんだもん": {
            "あまあま": vv_core_module.SpeakerID(uuid="uuid-zunda", style_id=3),
        },
    }


def _create_audio_query() -> AudioQueryType:
    return AudioQueryType.from_dict(
        {
            "accent_phrases": [],
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
            "volumeScale": 1.0,
            "prePhonemeLength": 0.1,
            "postPhonemeLength": 0.1,
            "pauseLength": 0.2,
            "pauseLengthScale": 1.0,
            "outputSamplingRate": 24000,
            "outputStereo": False,
            "kana": "テスト",
        }
    )


def _create_speaker(name: str, speaker_uuid: str, style_name: str, style_id: int) -> Speaker:
    return Speaker.from_dict(
        {
            "name": name,
            "speaker_uuid": speaker_uuid,
            "styles": [{"name": style_name, "id": style_id, "type": "talk"}],
            "version": "0.0.1",
            "supported_features": {"permitted_synthesis_morphing": "SELF_ONLY"},
        }
    )


def test_fetch_engine_name_returns_voicevox() -> None:
    assert voicevox_module.VoiceVox.fetch_engine_name() == "voicevox"


def test_initialize_engine_sets_common_config(engine: voicevox_module.VoiceVox) -> None:
    assert engine.url == "http://localhost:50021"
    assert engine.timeout == 3.0


@pytest.mark.asyncio
async def test_fetch_available_speakers_builds_speaker_map(
    engine: voicevox_module.VoiceVox, monkeypatch: pytest.MonkeyPatch
) -> None:
    speakers: list[Speaker] = [
        _create_speaker("四国めたん", "uuid-metan", "ノーマル", 2),
        _create_speaker("ずんだもん", "uuid-zunda", "あまあま", 3),
    ]
    api_request_mock = AsyncMock(return_value=speakers)
    monkeypatch.setattr(engine, "_api_request", api_request_mock)

    result = await engine.fetch_available_speakers()

    api_request_mock.assert_awaited_once_with(
        method="get",
        url="http://localhost:50021/speakers",
        model=Speaker,
        is_list=True,
        log_action="GET speakers",
    )
    assert result["四国めたん"]["ノーマル"].style_id == 2
    assert result["ずんだもん"]["あまあま"].uuid == "uuid-zunda"


def test_build_speaker_id_map_creates_nested_lookup(engine: voicevox_module.VoiceVox) -> None:
    speakers: list[Speaker] = [
        _create_speaker("四国めたん", "uuid-metan", "ノーマル", 2),
        _create_speaker("ずんだもん", "uuid-zunda", "あまあま", 3),
    ]

    result = engine._build_speaker_id_map(speakers)

    assert result == {
        "四国めたん": {"ノーマル": vv_core_module.SpeakerID(uuid="uuid-metan", style_id=2)},
        "ずんだもん": {"あまあま": vv_core_module.SpeakerID(uuid="uuid-zunda", style_id=3)},
    }


@pytest.mark.asyncio
async def test_async_init_preloads_cast_speakers(
    engine: voicevox_module.VoiceVox,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_async_init = AsyncMock(return_value=None)
    monkeypatch.setattr(vv_core_module.VVCore, "async_init", super_async_init)
    monkeypatch.setattr(engine, "fetch_available_speakers", AsyncMock(return_value=available_speakers))
    api_request_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(engine, "_api_request", api_request_mock)

    param = UserTypeInfo(
        streamer={"ja": TTSInfo(engine="voicevox", voice=Voice(cast="四国めたん|ノーマル"))},
        moderator={"ja": TTSInfo(engine="voicevox", voice=Voice(cast="ずんだもん|あまあま"))},
    )

    await engine.async_init(param)

    super_async_init.assert_awaited_once_with(param)
    assert api_request_mock.await_count == 2
    await_calls = api_request_mock.await_args_list
    called_speakers = {item.kwargs["params"]["speaker"] for item in await_calls}
    assert called_speakers == {"2", "3"}
    for item in await_calls:
        assert item.kwargs["method"] == "post"
        assert item.kwargs["url"] == "http://localhost:50021/initialize_speaker"
        assert item.kwargs["params"]["skip_reinit"] == "true"
        assert item.kwargs["log_action"] == "POST initialize_speaker"


@pytest.mark.asyncio
async def test_async_init_swallows_async_comm_error(
    engine: voicevox_module.VoiceVox,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vv_core_module.VVCore, "async_init", AsyncMock(return_value=None))
    monkeypatch.setattr(engine, "fetch_available_speakers", AsyncMock(return_value=available_speakers))
    api_request_mock = AsyncMock(side_effect=AsyncCommError("failed to init speaker"))
    monkeypatch.setattr(engine, "_api_request", api_request_mock)

    param = UserTypeInfo(streamer={"ja": TTSInfo(engine="voicevox", voice=Voice(cast="四国めたん|ノーマル"))})

    await engine.async_init(param)


@pytest.mark.asyncio
async def test_api_command_procedure_requests_query_then_synthesis(
    engine: voicevox_module.VoiceVox,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_query = _create_audio_query()
    engine.available_speakers = available_speakers
    api_request_mock = AsyncMock(side_effect=[audio_query, b"wav-bytes"])
    set_synthesis_parameters_mock = MagicMock()
    monkeypatch.setattr(engine, "_api_request", api_request_mock)
    monkeypatch.setattr(engine, "_set_synthesis_parameters", set_synthesis_parameters_mock)

    tts_param = TTSParam(content="こんにちは", tts_info=TTSInfo(voice=Voice(cast="四国めたん|ノーマル")))

    result = await engine.api_command_procedure(tts_param)

    assert result == b"wav-bytes"
    set_synthesis_parameters_mock.assert_called_once_with(audio_query, tts_param)
    api_request_mock.assert_has_awaits(
        [
            call(
                method="post",
                url="http://localhost:50021/audio_query",
                model=AudioQueryType,
                params={"text": "こんにちは", "speaker": "2"},
                log_action="POST audio_query",
            ),
            call(
                method="post",
                url="http://localhost:50021/synthesis",
                model=None,
                data=audio_query.to_dict(),
                params={"speaker": "2", "interrogative_upspeak": "true"},
                log_action="POST synthesis",
            ),
        ]
    )


def test_set_synthesis_parameters_assigns_defaults_and_converted_values(
    engine: voicevox_module.VoiceVox,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine.available_speakers = available_speakers
    convert_parameters_mock = MagicMock(side_effect=[1.1, 0.02, 1.4, 0.8])
    adjust_reading_speed_mock = MagicMock(return_value=1.23)
    monkeypatch.setattr(engine, "_convert_parameters", convert_parameters_mock)
    monkeypatch.setattr(engine, "_adjust_reading_speed", adjust_reading_speed_mock)

    audio_query = _create_audio_query()
    tts_param = TTSParam(
        content="hello",
        tts_info=TTSInfo(voice=Voice(cast="四国めたん|ノーマル", speed=120, tone=50, intonation=140, volume=80)),
    )

    engine._set_synthesis_parameters(audio_query, tts_param)

    adjust_reading_speed_mock.assert_called_once_with(1.1, len("hello"))
    assert audio_query.speedScale == 1.23
    assert audio_query.pitchScale == 0.02
    assert audio_query.intonationScale == 1.4
    assert audio_query.volumeScale == 0.8
    assert audio_query.prePhonemeLength == 0.05
    assert audio_query.postPhonemeLength == 0.05
    assert audio_query.pauseLength == 0.25
    assert audio_query.pauseLengthScale == 1.0
    assert audio_query.outputSamplingRate == 24000
    assert audio_query.outputStereo is False


def test_get_style_id_resolves_from_cast(
    engine: voicevox_module.VoiceVox,
    available_speakers: dict[str, dict[str, vv_core_module.SpeakerID]],
) -> None:
    engine.available_speakers = available_speakers
    tts_param = TTSParam(content="hello", tts_info=TTSInfo(voice=Voice(cast="ずんだもん|あまあま")))

    style_id = engine._get_style_id(tts_param)

    assert style_id == 3

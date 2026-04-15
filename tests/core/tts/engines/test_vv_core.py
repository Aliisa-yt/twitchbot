"""Unit tests for core.tts.engines.vv_core module."""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override
from unittest.mock import AsyncMock, MagicMock

import pytest
from dataclasses_json import DataClassJsonMixin, dataclass_json

from core.tts.engines import vv_core as vv_module
from core.tts.tts_interface import EngineContext
from handlers.async_comm import AsyncCommError, AsyncCommTimeoutError
from models.voice_models import TTSParam

if TYPE_CHECKING:
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


class DummyVVCore(vv_module.VVCore):
    @staticmethod
    @override
    def fetch_engine_name() -> str:
        return "dummyvv"

    @override
    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        _ = ttsparam
        return b"voice"


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> DummyVVCore:
    monkeypatch.setattr(vv_module, "AsyncHttp", FakeAsyncHttp)
    vv_core = DummyVVCore()
    config = SimpleNamespace(
        SERVER="http://localhost:50021",
        TIMEOUT=2.5,
        EARLY_SPEECH=True,
        AUTO_STARTUP=False,
        EXECUTE_PATH=str(tmp_path / "dummy_engine.exe"),
    )
    context = EngineContext(audio_save_directory=tmp_path, play_callback=AsyncMock())
    vv_core.initialize_engine(cast("TTSEngine", config), context)
    return vv_core


@pytest.fixture
def available_speakers() -> dict[str, dict[str, vv_module.SpeakerID]]:
    return {
        "四国めたん": {
            "ノーマル": vv_module.SpeakerID(uuid="uuid-metan", style_id=2),
            "ツンツン": vv_module.SpeakerID(uuid="uuid-metan", style_id=7),
        },
        "ずんだもん": {
            "ノーマル": vv_module.SpeakerID(uuid="uuid-zunda", style_id=1),
            "あまあま": vv_module.SpeakerID(uuid="uuid-zunda", style_id=3),
        },
    }


def test_convert_parameters_with_int_and_clamp(engine: DummyVVCore) -> None:
    assert engine._convert_parameters(250, (0.50, 2.00, 1.00)) == 2.00
    assert engine._convert_parameters(25, (0.50, 2.00, 1.00)) == 0.50


def test_convert_parameters_with_none_and_reversed_range(engine: DummyVVCore) -> None:
    assert engine._convert_parameters(None, (2.00, 0.50, 1.00)) == 1.00
    assert engine._convert_parameters(1.25, (2.00, 0.50, 1.00)) == 1.25


def test_adjust_reading_speed_accelerates_for_long_text(engine: DummyVVCore) -> None:
    adjusted: float = engine._adjust_reading_speed(1.0, 100)

    assert 1.0 < adjusted <= 1.4


def test_adjust_reading_speed_keeps_original_for_short_text(engine: DummyVVCore) -> None:
    assert engine._adjust_reading_speed(1.1, 30) == 1.1


def test_get_speaker_id_from_numeric_cast_caches_result(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    speaker_id: vv_module.SpeakerID = engine.get_speaker_id_from_cast("3", available_speakers)

    assert speaker_id == vv_module.SpeakerID(uuid="uuid-zunda", style_id=3)
    assert engine.id_cache["3"] == speaker_id


def test_get_speaker_id_from_name_defaults_to_normal_style(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    speaker_id: vv_module.SpeakerID = engine.get_speaker_id_from_cast("四国めたん", available_speakers)

    assert speaker_id == available_speakers["四国めたん"]["ノーマル"]


def test_get_speaker_id_returns_default_when_cast_is_empty(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    speaker_id: vv_module.SpeakerID = engine.get_speaker_id_from_cast("", available_speakers)

    assert speaker_id == available_speakers["四国めたん"]["ノーマル"]


def test_get_speaker_name_and_uuid_from_style_id(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    assert engine.get_speaker_name_from_style_id(3, available_speakers) == "ずんだもん|あまあま"
    assert engine.get_speaker_uuid_from_style_id(3, available_speakers) == "uuid-zunda"
    assert engine.get_speaker_uuid_from_style_id(999, available_speakers) == ""


@pytest.mark.asyncio
async def test_api_request_get_returns_raw_response(engine: DummyVVCore) -> None:
    engine.async_http.get = AsyncMock(return_value={"ok": True})

    response = await engine._api_request(method="get", url="http://example.com", model=None, total_timeout=1.2)

    assert response == {"ok": True}
    engine.async_http.get.assert_awaited_once_with(url="http://example.com", total_timeout=1.2)


@pytest.mark.asyncio
async def test_api_request_post_deserializes_model(engine: DummyVVCore) -> None:
    @dataclass_json
    @dataclass
    class DummyModel(DataClassJsonMixin):
        value: int

    engine.async_http.post = AsyncMock(return_value={"value": 42})

    response: DummyModel = await engine._api_request(
        method="post",
        url="http://example.com",
        model=DummyModel,
        params={"speaker": "1"},
        data={"text": "hello"},
        total_timeout=0.7,
    )

    assert isinstance(response, DummyModel)
    assert response.value == 42


@pytest.mark.asyncio
async def test_api_request_deserializes_list_response(engine: DummyVVCore) -> None:
    @dataclass_json
    @dataclass
    class DummyModel(DataClassJsonMixin):
        value: int

    engine.async_http.get = AsyncMock(return_value=[{"value": 1}, {"value": 2}])

    response: list[DummyModel] = await engine._api_request(
        method="get",
        url="http://example.com",
        model=DummyModel,
        is_list=True,
        total_timeout=0.5,
    )

    assert [item.value for item in response] == [1, 2]


@pytest.mark.asyncio
async def test_api_request_raises_for_unsupported_method(engine: DummyVVCore) -> None:
    with pytest.raises(ValueError, match="Unsupported HTTP method"):
        await engine._api_request(method="put", url="http://example.com", model=None, total_timeout=1.0)


@pytest.mark.asyncio
async def test_api_request_wraps_deserialization_errors(engine: DummyVVCore) -> None:
    class FailingModel(DataClassJsonMixin):
        pass

    engine.async_http.get = AsyncMock(return_value={"value": 1})

    with pytest.raises(AsyncCommError):
        await engine._api_request(method="get", url="http://example.com", model=FailingModel, total_timeout=1.0)


@pytest.mark.asyncio
async def test_detect_engine_startup_sets_running_after_retry(
    engine: DummyVVCore, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine._api_request = AsyncMock(side_effect=[AsyncCommTimeoutError("not ready"), "0.0.1"])
    sleep_mock: AsyncMock = AsyncMock()
    monkeypatch.setattr(vv_module.asyncio, "sleep", sleep_mock)

    await engine._detect_engine_startup()

    assert engine.is_engine_running is True
    sleep_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_detect_engine_startup_handles_outer_timeout(engine: DummyVVCore) -> None:
    engine._api_request = AsyncMock(side_effect=TimeoutError())

    await engine._detect_engine_startup()

    assert engine.is_engine_running is False


@pytest.mark.asyncio
async def test_speech_synthesis_saves_file_and_calls_play(engine: DummyVVCore) -> None:
    engine.api_command_procedure = AsyncMock(return_value=b"wav-bytes")
    engine.create_audio_filename = MagicMock(return_value=Path("voice.wav"))
    engine.save_audio_file = MagicMock()
    engine.play = AsyncMock()
    tts_param = TTSParam(content="hello")

    await engine.speech_synthesis(tts_param)

    engine.save_audio_file.assert_called_once_with(Path("voice.wav"), b"wav-bytes")
    engine.play.assert_awaited_once_with(tts_param)
    assert tts_param.filepath == Path("voice.wav")


@pytest.mark.asyncio
async def test_speech_synthesis_raises_when_audio_data_is_empty(engine: DummyVVCore) -> None:
    engine.api_command_procedure = AsyncMock(return_value=b"")
    engine.play = AsyncMock()

    with pytest.raises(vv_module.TTSNotSupportedError):
        await engine.speech_synthesis(TTSParam(content="hello"))

    engine.play.assert_not_called()


@pytest.mark.asyncio
async def test_speech_synthesis_raises_when_audio_data_is_not_bytes(engine: DummyVVCore) -> None:
    engine.api_command_procedure = AsyncMock(return_value="not-bytes")
    engine.play = AsyncMock()

    with pytest.raises(vv_module.TTSNotSupportedError):
        await engine.speech_synthesis(TTSParam(content="hello"))

    engine.play.assert_not_called()


@pytest.mark.asyncio
async def test_speech_synthesis_logs_tts_file_error_without_raising(engine: DummyVVCore) -> None:
    engine.api_command_procedure = AsyncMock(return_value=b"wav-bytes")
    engine.create_audio_filename = MagicMock(return_value=Path("voice.wav"))
    engine.save_audio_file = MagicMock(side_effect=vv_module.TTSFileError("file error"))
    engine.play = AsyncMock()

    # TTSFileError must be caught and logged; speech_synthesis must not raise
    await engine.speech_synthesis(TTSParam(content="hello"))

    engine.play.assert_not_called()


@pytest.mark.asyncio
async def test_speech_synthesis_logs_async_comm_error_without_raising(engine: DummyVVCore) -> None:
    engine.api_command_procedure = AsyncMock(side_effect=AsyncCommError("comm error"))
    engine.play = AsyncMock()

    # AsyncCommError must be caught and logged; speech_synthesis must not raise
    await engine.speech_synthesis(TTSParam(content="hello"))

    engine.play.assert_not_called()


def test_convert_parameters_with_float_value_within_range(engine: DummyVVCore) -> None:
    result = engine._convert_parameters(1.25, (0.50, 2.00, 1.00))

    assert result == 1.25


def test_convert_parameters_with_invalid_type_returns_default(engine: DummyVVCore) -> None:
    result = engine._convert_parameters("bad", (0.50, 2.00, 1.00))  # type: ignore[arg-type]

    assert result == 1.00


def test_adjust_reading_speed_disabled_when_no_earlyspeech(engine: DummyVVCore) -> None:
    engine._tts_config.earlyspeech = False  # type: ignore[attr-defined]

    adjusted = engine._adjust_reading_speed(1.0, 100)

    assert adjusted == 1.0


def test_adjust_reading_speed_boundary_at_exactly_30_chars(engine: DummyVVCore) -> None:
    # Exactly 30 characters: threshold is NOT exceeded, so speed stays unchanged
    assert engine._adjust_reading_speed(1.0, 30) == 1.0


def test_adjust_reading_speed_caps_at_1_40(engine: DummyVVCore) -> None:
    adjusted = engine._adjust_reading_speed(2.0, 10000)

    assert adjusted == 1.40


def test_get_speaker_id_from_name_style_format(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    speaker_id = engine.get_speaker_id_from_cast("四国めたん|ツンツン", available_speakers)

    assert speaker_id == vv_module.SpeakerID(uuid="uuid-metan", style_id=7)
    assert engine.id_cache["四国めたん|ツンツン"] == speaker_id


def test_get_speaker_id_from_unknown_name_returns_default(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    speaker_id = engine.get_speaker_id_from_cast("存在しない|ノーマル", available_speakers)

    # Default is the first speaker's ノーマル style
    assert speaker_id == available_speakers["四国めたん"]["ノーマル"]


def test_get_speaker_id_with_empty_available_speakers(engine: DummyVVCore) -> None:
    speaker_id = engine.get_speaker_id_from_cast("四国めたん", {})

    assert speaker_id == vv_module.SpeakerID(uuid="", style_id=0)


def test_get_speaker_id_from_cast_cache_hit(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    # Populate the cache
    first = engine.get_speaker_id_from_cast("ずんだもん", available_speakers)
    # Corrupt available_speakers to confirm second call uses cache, not live lookup
    available_speakers.clear()
    second = engine.get_speaker_id_from_cast("ずんだもん", available_speakers)

    assert first == second


def test_get_speaker_id_with_empty_name_in_pipe_format(
    engine: DummyVVCore, available_speakers: dict[str, dict[str, vv_module.SpeakerID]]
) -> None:
    # "|style" format: name part is empty, should fall back to default
    speaker_id = engine.get_speaker_id_from_cast("|ノーマル", available_speakers)

    assert speaker_id == available_speakers["四国めたん"]["ノーマル"]


@pytest.mark.asyncio
async def test_api_request_wraps_key_error_as_async_comm_error(engine: DummyVVCore) -> None:
    class KeyErrorModel(DataClassJsonMixin):
        """Fake model whose from_dict always raises KeyError."""

        @classmethod
        def from_dict(cls, _kvs, *, _infer_missing: bool = False):  # type: ignore[override]
            msg = "missing_field"
            raise KeyError(msg)

    engine.async_http.get = AsyncMock(return_value={"data": "value"})

    with pytest.raises(AsyncCommError):
        await engine._api_request(method="get", url="http://example.com", model=KeyErrorModel, total_timeout=1.0)


def test_check_status_command_setter(engine: DummyVVCore) -> None:
    engine.check_status_command = "/v2/version"

    assert engine.check_status_command == "/v2/version"


@pytest.mark.asyncio
async def test_close_closes_async_http(engine: DummyVVCore) -> None:
    await engine.close()

    cast("AsyncMock", engine.async_http.close).assert_awaited_once()


def test_is_engine_running_property_initially_false(engine: DummyVVCore) -> None:
    assert engine.is_engine_running is False

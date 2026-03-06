from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

import core.stt.engines.google_cloud_speech_to_text_v2 as stt_v2_module
from core.stt.engines.google_cloud_speech_to_text_v2 import GoogleCloudSpeechToTextV2
from core.stt.interface import STTInput, STTNonRetriableError, STTNotAvailableError
from utils.file_utils import FileUtils

if TYPE_CHECKING:
    from config.loader import Config


class _FakeCloudSpeechModule:
    class GetRecognizerRequest:
        def __init__(self, *, name: str) -> None:
            self.name = name

    class CreateRecognizerRequest:
        def __init__(self, *, parent: str, recognizer_id: str, recognizer: Any) -> None:
            self.parent = parent
            self.recognizer_id = recognizer_id
            self.recognizer = recognizer

    class Recognizer:
        def __init__(self, *, default_recognition_config: Any) -> None:
            self.default_recognition_config = default_recognition_config

    class ExplicitDecodingConfig:
        class AudioEncoding:
            LINEAR16 = "LINEAR16"

        def __init__(
            self,
            *,
            encoding: str,
            sample_rate_hertz: int,
            audio_channel_count: int,
        ) -> None:
            _ = encoding, sample_rate_hertz, audio_channel_count

    class RecognitionFeatures:
        def __init__(self, *, enable_automatic_punctuation: bool) -> None:
            self.enable_automatic_punctuation = enable_automatic_punctuation

    class RecognitionConfig:
        def __init__(
            self,
            *,
            explicit_decoding_config: Any | None = None,
            language_codes: list[str] | None = None,
            model: str = "",
            features: Any | None = None,
        ) -> None:
            _ = explicit_decoding_config, features
            self.language_codes = language_codes or []
            self.model = model

    class RecognizeRequest:
        def __init__(self, *, recognizer: str, config: Any, content: bytes) -> None:
            self.recognizer = recognizer
            self.config = config
            self.content = content


class _FakeSpeechModule:
    types = _FakeCloudSpeechModule


def _fake_speech_module() -> _FakeSpeechModule:
    return _FakeSpeechModule()


class _FakeClient:
    def __init__(self, response: Any, *, recognizer_exists: bool = False) -> None:
        self._response = response
        self.last_request: Any | None = None
        self.last_create_request: Any | None = None
        self.recognizer_exists = recognizer_exists

    class _NotFoundError(Exception):
        pass

    class _FakeOperation:
        def __init__(self, recognizer_name: str) -> None:
            self._recognizer_name = recognizer_name

        def result(self) -> Any:
            return SimpleNamespace(name=self._recognizer_name)

    def get_recognizer(self, *, request: Any = None, name: str | None = None) -> Any:
        recognizer_name = name or getattr(request, "name", "")
        if self.recognizer_exists:
            return SimpleNamespace(name=recognizer_name)
        msg = "404 recognizer not found"
        raise self._NotFoundError(msg)

    def create_recognizer(
        self, *, request: Any = None, parent: str = "", recognizer_id: str = "", recognizer: Any = None
    ) -> Any:
        if request is not None:
            self.last_create_request = request
            recognizer_name = f"{request.parent}/recognizers/{request.recognizer_id}"
            return self._FakeOperation(recognizer_name)

        _ = recognizer
        self.last_create_request = SimpleNamespace(parent=parent, recognizer_id=recognizer_id)
        recognizer_name = f"{parent}/recognizers/{recognizer_id}"
        return self._FakeOperation(recognizer_name)

    def recognize(self, *, request: Any) -> Any:
        self.last_request = request
        return self._response


class _InvalidArgumentError(Exception):
    pass


class _FailingClient(_FakeClient):
    def recognize(self, *, request: Any) -> Any:
        self.last_request = request
        msg = "invalid"
        raise _InvalidArgumentError(msg)


def test_initialize_enables_engine_with_credentials_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(
        engine,
        "_create_client",
        lambda _module: _FakeClient(response=SimpleNamespace(results=[]), recognizer_exists=True),
    )

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is True


def test_supported_languages_file_uses_fileutils_resource_path() -> None:
    expected = FileUtils.resource_path("data/stt/google-cloud-stt-v2_supported-languages.txt")

    assert expected == stt_v2_module.STT_V2_SUPPORTED_LANGUAGES_FILE


def test_initialize_keeps_engine_disabled_when_project_id_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: _FakeClient(response=SimpleNamespace(results=[])))

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is False


def test_initialize_does_not_fallback_to_google_cloud_api_oauth(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    fake_path = tmp_path / "service-account.json"
    fake_path.write_text('{"project_id": "test-project"}', encoding="utf-8")

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_OAUTH", str(fake_path))

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: _FakeClient(response=SimpleNamespace(results=[])))

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is False


def test_transcribe_returns_text_and_confidence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    response = SimpleNamespace(
        results=[
            SimpleNamespace(alternatives=[SimpleNamespace(transcript="hello", confidence=0.9)]),
            SimpleNamespace(alternatives=[SimpleNamespace(transcript="v2", confidence=0.7)]),
        ]
    )

    fake_client = _FakeClient(response=response, recognizer_exists=True)

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)
    config = SimpleNamespace(
        STT=SimpleNamespace(
            GOOGLE_CLOUD_STT_V2_LOCATION="global",
            GOOGLE_CLOUD_STT_V2_MODEL="latest_short",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="existing-recognizer",
        )
    )
    engine.initialize(config=cast("Config", config))

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    result = engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

    assert result.text == "hello v2"
    assert result.language == "ja-JP"
    assert result.confidence == pytest.approx(0.8)
    assert result.metadata is not None
    assert result.metadata["engine"] == "google_cloud_stt_v2"
    assert result.metadata["model"] == "latest_short"
    assert fake_client.last_request is not None
    assert fake_client.last_request.config.model == "latest_short"


def test_initialize_uses_stt_v2_location_and_model_from_config(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    response = SimpleNamespace(results=[])
    fake_client = _FakeClient(response=response)

    config = SimpleNamespace(
        STT=SimpleNamespace(
            GOOGLE_CLOUD_STT_V2_LOCATION="asia-northeast1",
            GOOGLE_CLOUD_STT_V2_MODEL="chirp_2",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="",
        )
    )

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)
    engine.initialize(config=cast("Config", config))

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    result = engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

    assert fake_client.last_request is not None
    assert fake_client.last_request.recognizer.startswith("projects/test-project/locations/asia-northeast1/")
    assert fake_client.last_request.config.model == "chirp_2"
    assert result.metadata is not None
    assert result.metadata["location"] == "asia-northeast1"
    assert result.metadata["model"] == "chirp_2"
    assert fake_client.last_create_request is not None
    assert fake_client.last_create_request.parent == "projects/test-project/locations/asia-northeast1"


def test_initialize_falls_back_when_location_and_model_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))

    fake_client = _FakeClient(response=SimpleNamespace(results=[]))

    config = SimpleNamespace(
        STT=SimpleNamespace(
            GOOGLE_CLOUD_STT_V2_LOCATION="",
            GOOGLE_CLOUD_STT_V2_MODEL="",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="",
        )
    )

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)

    caplog.set_level("WARNING")
    engine.initialize(config=cast("Config", config))

    assert engine.is_available is True
    assert "GOOGLE_CLOUD_STT_V2_LOCATION is not configured in ini" in caplog.text
    assert "GOOGLE_CLOUD_STT_V2_MODEL is not configured in ini" in caplog.text


def test_initialize_auto_assigns_location_and_model_from_language_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    metadata_file = tmp_path / "supported-languages.txt"
    metadata_file.write_text(
        "# test metadata\nLocation\tName\tBCP-47\tModel\n"
        "global\t日本語（日本）\tja-JP\tlong\n"
        "global\t日本語（日本）\tja-JP\tshort",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "core.stt.engines.google_cloud_speech_to_text_v2.STT_V2_SUPPORTED_LANGUAGES_FILE",
        metadata_file,
    )

    fake_client = _FakeClient(response=SimpleNamespace(results=[]), recognizer_exists=True)

    config = SimpleNamespace(
        STT=SimpleNamespace(
            LANGUAGE="ja-JP",
            GOOGLE_CLOUD_STT_V2_LOCATION="",
            GOOGLE_CLOUD_STT_V2_MODEL="",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="",
        )
    )

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)

    caplog.set_level("WARNING")
    engine.initialize(config=cast("Config", config))

    assert engine.is_available is True
    assert "Auto-assigned 'global' from STT.LANGUAGE=ja-JP" in caplog.text
    assert "Auto-assigned 'long' from STT.LANGUAGE=ja-JP" in caplog.text


def test_transcribe_raises_when_engine_not_available(tmp_path) -> None:
    engine = GoogleCloudSpeechToTextV2()
    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00")

    with pytest.raises(STTNotAvailableError):
        engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))


def test_initialize_shows_clear_message_when_create_permission_denied(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))

    fake_client = _FakeClient(response=SimpleNamespace(results=[]))

    class _DeniedOperation:
        def result(self) -> Any:
            msg = "403 Permission 'speech.recognizers.create' denied on resource [reason: 'IAM_PERMISSION_DENIED']"
            raise RuntimeError(msg)

    def denied_create_recognizer(
        *, request: Any = None, parent: str = "", recognizer_id: str = "", recognizer: Any = None
    ) -> Any:
        _ = request, parent, recognizer_id, recognizer
        return _DeniedOperation()

    fake_client.create_recognizer = denied_create_recognizer  # type: ignore[method-assign]

    config = SimpleNamespace(
        STT=SimpleNamespace(
            GOOGLE_CLOUD_STT_V2_LOCATION="asia-northeast1",
            GOOGLE_CLOUD_STT_V2_MODEL="chirp_2",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="",
        )
    )

    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)

    engine.initialize(config=cast("Config", config))

    assert engine.is_available is False


def test_transcribe_raises_non_retriable_error_for_invalid_argument(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text('{"project_id": "test-project"}', encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))

    fake_client = _FailingClient(response=SimpleNamespace(results=[]), recognizer_exists=True)
    engine = GoogleCloudSpeechToTextV2()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: fake_client)

    config = SimpleNamespace(
        STT=SimpleNamespace(
            GOOGLE_CLOUD_STT_V2_LOCATION="global",
            GOOGLE_CLOUD_STT_V2_MODEL="latest_short",
            GOOGLE_CLOUD_STT_V2_RECOGNIZER="existing-recognizer",
        )
    )
    engine.initialize(config=cast("Config", config))

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    with pytest.raises(STTNonRetriableError):
        engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

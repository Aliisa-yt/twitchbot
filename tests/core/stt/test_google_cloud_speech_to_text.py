from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from core.stt.engines.google_cloud_speech_to_text import GoogleCloudSpeechToText
from core.stt.stt_interface import STTInput, STTNonRetriableError, STTNotAvailableError

if TYPE_CHECKING:
    from config.loader import Config


class _FakeAudio:
    def __init__(self, *, content: bytes) -> None:
        self.content = content


class _FakeConfig:
    class AudioEncoding:
        LINEAR16 = "LINEAR16"

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


class _FakeSpeechModule:
    RecognitionAudio = _FakeAudio
    RecognitionConfig = _FakeConfig


def _fake_speech_module() -> _FakeSpeechModule:
    return _FakeSpeechModule()


class _FakeClient:
    def __init__(self, response: Any) -> None:
        self._response = response

    def recognize(self, *, config: Any, audio: Any) -> Any:
        _ = config, audio
        return self._response


class _InvalidArgumentError(Exception):
    pass


class _FailingClient:
    def recognize(self, *, config: Any, audio: Any) -> Any:
        _ = config, audio
        msg = "invalid"
        raise _InvalidArgumentError(msg)


def test_initialize_enables_engine_with_credentials_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))
    engine = GoogleCloudSpeechToText()

    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: _FakeClient(response=SimpleNamespace(results=[])))

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is True


def test_initialize_keeps_engine_disabled_without_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_API_OAUTH", raising=False)

    engine = GoogleCloudSpeechToText()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is False


def test_initialize_enables_engine_with_api_key_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_OAUTH", "dummy_api_key")

    engine = GoogleCloudSpeechToText()

    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is True


def test_initialize_treats_google_cloud_api_oauth_as_api_key_even_if_file_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake_path = tmp_path / "looks-like-credentials.json"
    fake_path.write_text("{}", encoding="utf-8")

    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_OAUTH", str(fake_path))

    engine = GoogleCloudSpeechToText()
    engine.initialize(config=cast("Config", SimpleNamespace()))

    assert engine.is_available is True


def test_transcribe_returns_text_and_confidence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))

    response = SimpleNamespace(
        results=[
            SimpleNamespace(alternatives=[SimpleNamespace(transcript="hello", confidence=0.9)]),
            SimpleNamespace(alternatives=[SimpleNamespace(transcript="world", confidence=0.7)]),
        ]
    )

    engine = GoogleCloudSpeechToText()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: _FakeClient(response=response))
    engine.initialize(config=cast("Config", SimpleNamespace()))

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    result = engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

    assert result.text == "hello world"
    assert result.language == "ja-JP"
    assert result.confidence == pytest.approx(0.8)
    assert result.metadata is not None
    assert result.metadata["engine"] == "google_cloud_stt"


def test_transcribe_raises_when_engine_not_available(tmp_path) -> None:
    engine = GoogleCloudSpeechToText()
    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00")

    with pytest.raises(STTNotAvailableError):
        engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))


def test_transcribe_uses_rest_when_api_key_mode(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_API_OAUTH", "dummy_api_key")

    engine = GoogleCloudSpeechToText()
    engine.initialize(config=cast("Config", SimpleNamespace()))

    captured_url: dict[str, str] = {}

    def fake_post_json(*, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        _ = payload
        captured_url["url"] = url
        return {
            "results": [
                {"alternatives": [{"transcript": "hello", "confidence": 0.9}]},
                {"alternatives": [{"transcript": "rest", "confidence": 0.5}]},
            ]
        }

    monkeypatch.setattr(engine, "_post_json", fake_post_json)

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    result = engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

    assert "speech:recognize" in captured_url["url"]
    assert "key=dummy_api_key" in captured_url["url"]
    assert result.text == "hello rest"
    assert result.confidence == pytest.approx(0.7)


def test_transcribe_raises_non_retriable_error_for_invalid_argument(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    creds_file = tmp_path / "gcp.json"
    creds_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(creds_file))

    engine = GoogleCloudSpeechToText()
    monkeypatch.setattr(engine, "_import_speech_module", _fake_speech_module)
    monkeypatch.setattr(engine, "_create_client", lambda _module: _FailingClient())
    engine.initialize(config=cast("Config", SimpleNamespace()))

    pcm_file = tmp_path / "sample.pcm"
    pcm_file.write_bytes(b"\x00\x00\x01\x00")

    with pytest.raises(STTNonRetriableError):
        engine.transcribe(STTInput(audio_path=pcm_file, language="ja-JP", sample_rate=16000, channels=1))

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

import pytest

from core.trans.engines import trans_google_cloud as trans_google_cloud_module
from core.trans.interface import (
    NotSupportedLanguagesError,
    Result,
    TranslateExceptionError,
    TranslationRateLimitError,
)

if TYPE_CHECKING:
    from models.translation_models import CharacterQuota


class DummyClient:
    detect_result: ClassVar[dict[str, Any]] = {"language": "EN", "confidence": 0.9}
    translate_result: ClassVar[dict[str, Any]] = {"translatedText": "ok", "detectedSourceLanguage": "EN"}
    detect_error: ClassVar[Exception | None] = None
    translate_error: ClassVar[Exception | None] = None

    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs
        self.languages_called = False

    def get_languages(self) -> list[dict[str, str]]:
        self.languages_called = True
        return []

    def detect_language(self, content: str) -> dict[str, Any]:
        _ = content
        err = type(self).detect_error
        if err is not None:
            raise err
        return type(self).detect_result

    def translate(self, content: str, target_language: str, source_language: str | None = None) -> dict[str, Any]:
        _ = content, target_language, source_language
        err = type(self).translate_error
        if err is not None:
            raise err
        return type(self).translate_result


@pytest.fixture(autouse=True)
def setup_google_cloud_module(monkeypatch: pytest.MonkeyPatch) -> None:
    DummyClient.detect_result = {"language": "EN", "confidence": 0.9}
    DummyClient.translate_result = {"translatedText": "ok", "detectedSourceLanguage": "EN"}
    DummyClient.detect_error = None
    DummyClient.translate_error = None
    monkeypatch.setattr(trans_google_cloud_module.translate, "Client", DummyClient)


@pytest.fixture
def config() -> Any:
    return SimpleNamespace(TRANSLATION=SimpleNamespace())


def test_inst_property_raises_when_uninitialized() -> None:
    engine = trans_google_cloud_module.GoogleCloudTranslation()

    with pytest.raises(TranslateExceptionError):
        _ = engine._inst


def test_initialize_sets_attributes_and_instance_with_api_key(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setenv("GOOGLE_CLOUD_API_OAUTH", "token")
    engine = trans_google_cloud_module.GoogleCloudTranslation()

    engine.initialize(config)

    assert engine.engine_attributes.name == "google_cloud"
    assert engine.engine_attributes.supports_dedicated_detection_api is True
    assert engine.engine_attributes.supports_quota_api is False
    assert isinstance(engine._inst, DummyClient)
    assert engine._inst.languages_called is True
    assert engine._inst.kwargs.get("_http") is not None


@pytest.mark.asyncio
async def test_detect_language_returns_result(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    result: Result = await engine.detect_language("hello", tgt_lang="ja")

    assert result.text is None
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "google_cloud", "confidence": "0.9"}


@pytest.mark.asyncio
async def test_detect_language_rate_limit_raises(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.detect_error = trans_google_cloud_module.TooManyRequests("limit")
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    with pytest.raises(TranslationRateLimitError):
        await engine.detect_language("hello", tgt_lang="ja")


@pytest.mark.asyncio
async def test_detect_language_google_error_raises(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.detect_error = trans_google_cloud_module.GoogleAPIError("bad")
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    with pytest.raises(TranslateExceptionError):
        await engine.detect_language("hello", tgt_lang="ja")


@pytest.mark.asyncio
async def test_translation_returns_result(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    result: Result = await engine.translation("hello", tgt_lang="ja", src_lang="en")

    assert result.text == "ok"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "google_cloud"}


@pytest.mark.asyncio
async def test_translation_raises_for_unsupported_language(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.translate_error = trans_google_cloud_module.BadRequest("bad")
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    with pytest.raises(NotSupportedLanguagesError):
        await engine.translation("hello", tgt_lang="xx", src_lang="en")


@pytest.mark.asyncio
async def test_translation_rate_limit_raises(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.translate_error = trans_google_cloud_module.TooManyRequests("limit")
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    with pytest.raises(TranslationRateLimitError):
        await engine.translation("hello", tgt_lang="ja", src_lang="en")


@pytest.mark.asyncio
async def test_translation_google_error_raises(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.translate_error = trans_google_cloud_module.GoogleAPIError("bad")
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    with pytest.raises(TranslateExceptionError):
        await engine.translation("hello", tgt_lang="ja", src_lang="en")


@pytest.mark.asyncio
async def test_get_quota_status_uses_engine_defaults(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_google_cloud_module.asyncio, "to_thread", fake_to_thread)
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    quota: CharacterQuota = await engine.get_quota_status()

    assert quota.count == 0
    assert quota.limit == 500000
    assert quota.is_quota_valid is False


@pytest.mark.asyncio
async def test_close_resets_instance(config: Any) -> None:
    engine = trans_google_cloud_module.GoogleCloudTranslation()
    engine.initialize(config)

    await engine.close()

    with pytest.raises(TranslateExceptionError):
        _ = engine._inst

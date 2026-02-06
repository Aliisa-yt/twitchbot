from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from core.trans.engines import trans_deepl as trans_deepl_module
from core.trans.interface import (
    NotSupportedLanguagesError,
    Result,
    TranslateExceptionError,
    TranslationQuotaExceededError,
)

if TYPE_CHECKING:
    from config.loader import Config
    from models.translation_models import CharacterQuota


class DummyLanguage:
    EN: str = "en"
    JA: str = "ja"
    ZH: str = "zh"
    EN_US: str = "en-US"


class DummyTextResult:
    def __init__(self, text: str, detected_source_lang: str) -> None:
        self.text: str = text
        self.detected_source_lang: str = detected_source_lang


class DummyUsage:
    def __init__(self, count: int = 0, limit: int = 500000, *, limit_reached: bool = False) -> None:
        self.character: SimpleNamespace = SimpleNamespace(count=count, limit=limit, limit_reached=limit_reached)


class DummyClient:
    usage: DummyUsage = DummyUsage(count=1, limit=100, limit_reached=False)
    translate_result: DummyTextResult | list[DummyTextResult] = DummyTextResult("ok", "EN")
    translate_error: Exception | None = None

    def __init__(self, auth_key: str) -> None:
        self.auth_key: str = auth_key
        self.calls: list[tuple[str, str | None, str]] = []

    def translate_text(self, content: str, source_lang: str | None, target_lang: str) -> DummyTextResult:
        self.calls.append((content, source_lang, target_lang))
        err: Exception | None = type(self).translate_error
        if err is not None:
            raise err
        result: DummyTextResult | list[DummyTextResult] = type(self).translate_result
        if isinstance(result, list):
            return result[0]
        return result

    def get_usage(self) -> DummyUsage:
        return type(self).usage


@pytest.fixture(autouse=True)
def setup_deepl_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trans_deepl_module, "Language", DummyLanguage)
    monkeypatch.setattr(trans_deepl_module, "TextResult", DummyTextResult)
    monkeypatch.setattr(trans_deepl_module, "Usage", DummyUsage)
    monkeypatch.setattr(trans_deepl_module, "DeepLClient", DummyClient)

    trans_deepl_module.DeeplTranslation._source_codes = {}
    trans_deepl_module.DeeplTranslation._target_codes = {}
    DummyClient.usage = DummyUsage(count=1, limit=100, limit_reached=False)
    DummyClient.translate_result = DummyTextResult("ok", "EN")
    DummyClient.translate_error = None


@pytest.fixture
def config() -> Config:
    return cast("Config", SimpleNamespace(TRANSLATION=SimpleNamespace()))


def test_inst_property_raises_when_uninitialized() -> None:
    engine = trans_deepl_module.DeeplTranslation()

    with pytest.raises(TranslateExceptionError):
        _ = engine._inst


def test_initialize_sets_attributes_and_instance(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    monkeypatch.setenv("DEEPL_API_OAUTH", "token")
    engine = trans_deepl_module.DeeplTranslation()

    engine.initialize(config)

    assert engine.engine_attributes.name == "deepl"
    assert engine.engine_attributes.supports_dedicated_detection_api is False
    assert engine.engine_attributes.supports_quota_api is True
    assert engine.isavailable is True

    inst: DummyClient = cast("DummyClient", engine._inst)
    assert inst.auth_key == "token"


@pytest.mark.asyncio
async def test_translation_returns_result(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_deepl_module.asyncio, "to_thread", fake_to_thread)
    engine = trans_deepl_module.DeeplTranslation()
    engine.initialize(config)

    result: Result = await engine.translation("hello", tgt_lang="ja", src_lang="en")

    assert result.text == "ok"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "deepl"}


@pytest.mark.asyncio
async def test_translation_raises_for_unsupported_language() -> None:
    engine = trans_deepl_module.DeeplTranslation()

    with pytest.raises(NotSupportedLanguagesError):
        await engine.translation("hello", tgt_lang="xx", src_lang="en")


@pytest.mark.asyncio
async def test_translation_handles_quota_exceeded(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_deepl_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.translate_error = trans_deepl_module.QuotaExceededException("quota")
    engine = trans_deepl_module.DeeplTranslation()
    engine.initialize(config)

    with pytest.raises(TranslationQuotaExceededError):
        await engine.translation("hello", tgt_lang="ja", src_lang="en")

    assert engine.isavailable is False


@pytest.mark.asyncio
async def test_get_quota_status_returns_character_quota(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(trans_deepl_module.asyncio, "to_thread", fake_to_thread)
    DummyClient.usage = DummyUsage(count=12, limit=1000, limit_reached=False)
    engine = trans_deepl_module.DeeplTranslation()
    engine.initialize(config)

    quota: CharacterQuota = await engine.get_quota_status()

    assert quota.count == 12
    assert quota.limit == 1000
    assert quota.is_quota_valid is True


@pytest.mark.asyncio
async def test_close_resets_instance_and_usage(config: Config) -> None:
    engine = trans_deepl_module.DeeplTranslation()
    engine.initialize(config)

    await engine.close()

    assert engine.isavailable is False
    with pytest.raises(TranslateExceptionError):
        _ = engine._inst
    with pytest.raises(TranslateExceptionError):
        _ = engine._usage

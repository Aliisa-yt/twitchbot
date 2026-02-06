from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from core.trans.engines import trans_google as trans_google_module
from core.trans.interface import Result, TranslateExceptionError
from models.translation_models import CharacterQuota


class DummyTranslator:
    def __init__(self, url_suffix: str) -> None:
        self.url_suffix: str = url_suffix
        self.closed = False
        self.calls: list[tuple[str, str, str | None]] = []

    async def translate(self, content: str, tgt_lang: str, src_lang: str | None) -> trans_google_module.TextResult:
        self.calls.append((content, tgt_lang, src_lang))
        return trans_google_module.TextResult("ok", "en", metadata={"source": "dummy"})

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def config() -> Any:
    return SimpleNamespace(TRANSLATION=SimpleNamespace(GOOGLE_SUFFIX="com"))


def test_inst_property_raises_when_uninitialized() -> None:
    engine = trans_google_module.GoogleTranslation()

    with pytest.raises(TranslateExceptionError):
        _ = engine._inst


def test_initialize_sets_attributes_and_instance(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setattr(trans_google_module, "AsyncTranslator", DummyTranslator)
    engine = trans_google_module.GoogleTranslation()

    engine.initialize(config)

    assert engine.engine_attributes.name == "google"
    assert engine.engine_attributes.supports_dedicated_detection_api is False
    assert engine.engine_attributes.supports_quota_api is False
    assert isinstance(engine._inst, DummyTranslator)
    assert engine._inst.url_suffix == "com"


@pytest.mark.asyncio
async def test_translation_returns_result(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setattr(trans_google_module, "AsyncTranslator", DummyTranslator)
    engine = trans_google_module.GoogleTranslation()
    engine.initialize(config)

    result: Result = await engine.translation("hello", tgt_lang="ja", src_lang="en")

    assert isinstance(result, Result)
    assert result.text == "ok"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"source": "dummy"}


@pytest.mark.asyncio
async def test_detect_language_delegates_to_translation(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setattr(trans_google_module, "AsyncTranslator", DummyTranslator)
    engine = trans_google_module.GoogleTranslation()
    engine.initialize(config)

    result: Result = await engine.detect_language("hello", tgt_lang="ja")

    assert result.text == "ok"
    assert result.detected_source_lang == "en"


@pytest.mark.asyncio
async def test_translation_raises_on_engine_error(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    class ErrorTranslator(DummyTranslator):
        async def translate(self, content: str, tgt_lang: str, src_lang: str | None) -> trans_google_module.TextResult:
            _ = content, tgt_lang, src_lang
            msg = "bad"
            raise trans_google_module.InvalidLanguageCodeError(msg)

    monkeypatch.setattr(trans_google_module, "AsyncTranslator", ErrorTranslator)
    engine = trans_google_module.GoogleTranslation()
    engine.initialize(config)

    with pytest.raises(TranslateExceptionError):
        await engine.translation("hello", tgt_lang="ja", src_lang="xx")


@pytest.mark.asyncio
async def test_get_quota_status_uses_engine_defaults(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setattr(trans_google_module, "AsyncTranslator", DummyTranslator)
    engine = trans_google_module.GoogleTranslation()
    engine.initialize(config)

    quota: CharacterQuota = await engine.get_quota_status()

    assert isinstance(quota, CharacterQuota)
    assert quota.count == 0
    assert quota.limit == 500000
    assert quota.is_quota_valid is False


@pytest.mark.asyncio
async def test_close_calls_translator_close(monkeypatch: pytest.MonkeyPatch, config: Any) -> None:
    monkeypatch.setattr(trans_google_module, "AsyncTranslator", DummyTranslator)
    engine = trans_google_module.GoogleTranslation()
    engine.initialize(config)

    await engine.close()

    inst: DummyTranslator = cast("DummyTranslator", engine._inst)
    assert inst.closed is True

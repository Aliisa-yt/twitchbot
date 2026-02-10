"""Unit tests for core.trans.manager module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, cast

import pytest

from core.trans.interface import (
    EngineAttributes,
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
)
from core.trans.manager import TransManager
from models.config_models import Config
from models.translation_models import CharacterQuota, TranslationInfo

if TYPE_CHECKING:
    from config.loader import Config


class DummyEngine(TransInterface):
    """Minimal translation engine for TransManager tests."""

    supports_detection_api: ClassVar[bool] = True
    detect_result: ClassVar[Result] = Result(detected_source_lang="en", text=None)
    translation_result: ClassVar[Result] = Result(text="translated")
    detect_error: ClassVar[Exception | None] = None
    translation_error: ClassVar[Exception | None] = None
    quota_error: ClassVar[Exception | None] = None
    available: ClassVar[bool] = True
    translation_called: ClassVar[bool] = False
    close_called: ClassVar[bool] = False
    quota: ClassVar[CharacterQuota] = CharacterQuota(count=1, limit=10, is_quota_valid=True)

    @property
    def count(self) -> int:
        return 0

    @property
    def limit(self) -> int:
        return 10

    @property
    def limit_reached(self) -> bool:
        return False

    @property
    def isavailable(self) -> bool:
        return type(self).available

    @staticmethod
    def fetch_engine_name() -> str:
        return "dummy"

    def initialize(self, config) -> None:
        _ = config
        self.engine_attributes = EngineAttributes(
            name=self.fetch_engine_name(),
            supports_dedicated_detection_api=type(self).supports_detection_api,
            supports_quota_api=True,
        )

    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        _ = content, tgt_lang
        err: Exception | None = type(self).detect_error
        if err is not None:
            raise err
        return type(self).detect_result

    async def translation(self, content: str, tgt_lang: str, src_lang: str | None = None) -> Result:
        _ = content, tgt_lang, src_lang
        type(self).translation_called = True
        err: Exception | None = type(self).translation_error
        if err is not None:
            raise err
        return type(self).translation_result

    async def get_quota_status(self) -> CharacterQuota:
        err: Exception | None = type(self).quota_error
        if err is not None:
            raise err
        return type(self).quota

    async def close(self) -> None:
        type(self).close_called = True


@pytest.fixture(autouse=True)
def reset_engine_state(monkeypatch: pytest.MonkeyPatch) -> None:
    DummyEngine.supports_detection_api = True
    DummyEngine.detect_result = Result(detected_source_lang="en", text=None)
    DummyEngine.translation_result = Result(text="translated")
    DummyEngine.detect_error = None
    DummyEngine.translation_error = None
    DummyEngine.quota_error = None
    DummyEngine.available = True
    DummyEngine.translation_called = False
    DummyEngine.close_called = False
    DummyEngine.quota = CharacterQuota(count=1, limit=10, is_quota_valid=True)

    monkeypatch.setattr(TransInterface, "registered", {"dummy": DummyEngine})
    monkeypatch.setattr(TransManager, "_trans_engine", [])


@pytest.fixture
def config() -> Config:
    return cast(
        "Config",
        SimpleNamespace(TRANSLATION=SimpleNamespace(ENGINE=["dummy"], SECOND_LANGUAGE="ja", NATIVE_LANGUAGE="en")),
    )


@pytest.mark.asyncio
async def test_init_registers_engine(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()

    assert TransManager.get_trans_engine_names() == ["dummy"]
    assert isinstance(manager.active_engine, DummyEngine)
    assert manager._current_trans_engine == ["dummy"]  # noqa: SLF001


@pytest.mark.asyncio
async def test_active_engine_raises_when_empty() -> None:
    config: Config = cast(
        "Config", SimpleNamespace(TRANSLATION=SimpleNamespace(ENGINE=[], SECOND_LANGUAGE="ja", NATIVE_LANGUAGE="en"))
    )
    manager = TransManager(config)
    await manager.initialize()

    with pytest.raises(TranslateExceptionError):
        _ = manager.active_engine


@pytest.mark.asyncio
async def test_refresh_active_engine_list_removes_unavailable(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    DummyEngine.available = False

    manager.refresh_active_engine_list()

    assert TransManager.get_trans_engine_names() == []
    assert manager._current_trans_engine == []  # noqa: SLF001


@pytest.mark.asyncio
async def test_detect_language_empty_returns_false(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="")

    result: bool = await manager.detect_language(trans_info)

    assert result is False
    assert trans_info.src_lang is None


@pytest.mark.asyncio
async def test_detect_language_und_sets_no_translation(config: Config) -> None:
    DummyEngine.detect_result = Result(detected_source_lang="und", text="ignored")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="test.py")

    result: bool = await manager.detect_language(trans_info)

    assert result is False
    assert trans_info.src_lang == "en"
    assert trans_info.tgt_lang == "en"
    assert trans_info.translated_text == "test.py"
    assert trans_info.is_translate is False


@pytest.mark.asyncio
async def test_detect_language_sets_translated_text_when_detection_returns_translation(config: Config) -> None:
    DummyEngine.supports_detection_api = False
    DummyEngine.detect_result = Result(detected_source_lang="fr", text="bonjour")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello")

    result: bool = await manager.detect_language(trans_info)

    assert result is True
    assert trans_info.src_lang == "fr"
    assert trans_info.translated_text == "bonjour"


@pytest.mark.asyncio
async def test_perform_translation_reuses_existing_translation(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", tgt_lang="ja", translated_text="pre")

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    assert DummyEngine.translation_called is False


@pytest.mark.asyncio
async def test_perform_translation_success_sets_text(config: Config) -> None:
    DummyEngine.translation_result = Result(text="konnichiwa")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja")

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    assert trans_info.translated_text == "konnichiwa"
    assert DummyEngine.translation_called is True


@pytest.mark.asyncio
async def test_perform_translation_handles_errors(config: Config) -> None:
    DummyEngine.translation_error = NotSupportedLanguagesError("bad")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="xx", tgt_lang="yy")

    result: bool = await manager.perform_translation(trans_info)

    assert result is False
    assert trans_info.translated_text == ""


def test_parse_language_prefix_two_codes() -> None:
    trans_info = TranslationInfo(content="en:ja:Hello")

    result: bool = TransManager.parse_language_prefix(trans_info)

    assert result is True
    assert trans_info.src_lang == "en"
    assert trans_info.tgt_lang == "ja"
    assert trans_info.content == "Hello"


def test_parse_language_prefix_one_code() -> None:
    trans_info = TranslationInfo(content="ja:Hello")

    result: bool = TransManager.parse_language_prefix(trans_info)

    assert result is True
    assert trans_info.tgt_lang == "ja"
    assert trans_info.content == "Hello"


def test_parse_language_prefix_invalid_returns_false() -> None:
    trans_info = TranslationInfo(content="zz:Hello")

    result: bool = TransManager.parse_language_prefix(trans_info)

    assert result is False
    assert trans_info.tgt_lang == ""
    assert trans_info.content == "zz:Hello"


def test_determine_target_language_prefers_native_when_src_diff(config: Config) -> None:
    manager = TransManager(config)
    trans_info = TranslationInfo(content="hello", src_lang="ja")

    result: bool = manager.determine_target_language(trans_info)

    assert result is True
    assert trans_info.tgt_lang == "en"


def test_determine_target_language_prefers_second_when_src_native(config: Config) -> None:
    manager = TransManager(config)
    trans_info = TranslationInfo(content="hello", src_lang="en")

    result: bool = manager.determine_target_language(trans_info)

    assert result is True
    assert trans_info.tgt_lang == "ja"


def test_determine_target_language_respects_existing_target(config: Config) -> None:
    manager = TransManager(config)
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="fr")

    result: bool = manager.determine_target_language(trans_info)

    assert result is True
    assert trans_info.tgt_lang == "fr"


@pytest.mark.asyncio
async def test_get_usage_returns_default_on_error(config: Config) -> None:
    DummyEngine.quota_error = TranslateExceptionError("quota failed")
    manager = TransManager(config)
    await manager.initialize()

    quota: CharacterQuota = await manager.get_usage()

    assert quota == CharacterQuota(count=0, limit=0, is_quota_valid=False)


@pytest.mark.asyncio
async def test_shutdown_engines_calls_close(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()

    await manager.shutdown_engines()

    assert DummyEngine.close_called is True

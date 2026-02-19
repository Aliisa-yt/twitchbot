"""Unit tests for core.trans.manager module."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.trans.interface import (
    EngineAttributes,
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
    TranslationQuotaExceededError,
    TranslationRateLimitError,
)
from core.trans.manager import TransManager
from models.cache_models import TranslationCacheEntry
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
    def is_available(self) -> bool:
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

    assert TransManager.fetch_engine_names() == ["dummy"]
    assert isinstance(manager.current_engine_instance, DummyEngine)


def test_update_engine_names_filters_unregistered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TransInterface, "registered", {"dummy": DummyEngine})

    TransManager.update_engine_names(["dummy", "unknown"])

    assert TransManager.fetch_engine_names() == ["dummy"]


@pytest.mark.asyncio
async def test_active_engine_raises_when_empty() -> None:
    config: Config = cast(
        "Config", SimpleNamespace(TRANSLATION=SimpleNamespace(ENGINE=[], SECOND_LANGUAGE="ja", NATIVE_LANGUAGE="en"))
    )
    manager = TransManager(config)
    await manager.initialize()

    with pytest.raises(TranslateExceptionError):
        _ = manager.current_engine_instance


@pytest.mark.asyncio
async def test_refresh_active_engine_list_removes_unavailable(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    DummyEngine.available = False

    manager.refresh_active_engine_list()

    assert TransManager.fetch_engine_names() == []


@pytest.mark.asyncio
async def test_detect_language_empty_returns_false(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.detect_language(trans_info)

    assert result is False
    assert trans_info.src_lang is None


@pytest.mark.asyncio
async def test_detect_language_uses_cache_hit(config: Config) -> None:
    cache_manager = MagicMock()
    cache_manager.search_language_detection_cache = AsyncMock(return_value=MagicMock(detected_lang="fr"))
    manager = TransManager(config, cache_manager=cache_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.detect_language(trans_info)

    assert result is True
    assert trans_info.src_lang == "fr"


@pytest.mark.asyncio
async def test_detect_language_returns_false_when_detected_source_is_none(config: Config) -> None:
    DummyEngine.detect_result = Result(detected_source_lang=None, text="ignored")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.detect_language(trans_info)

    assert result is False
    assert trans_info.src_lang is None


@pytest.mark.asyncio
async def test_detect_language_und_sets_no_translation(config: Config) -> None:
    DummyEngine.detect_result = Result(detected_source_lang="und", text="ignored")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="test.py")
    trans_info.engine = manager.current_engine_instance

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
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.detect_language(trans_info)

    assert result is True
    assert trans_info.src_lang == "fr"
    assert trans_info.translated_text == "bonjour"


@pytest.mark.asyncio
async def test_detect_language_handles_rate_limit_error(config: Config) -> None:
    DummyEngine.detect_error = TranslationRateLimitError("rate limit")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.detect_language(trans_info)

    assert result is False
    assert manager._rate_limit_until > 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_fetch_cached_translation_sets_translated_text(config: Config) -> None:
    now = datetime.now(tz=UTC)
    cache_entry = TranslationCacheEntry(
        cache_key="key",
        normalized_source="hello",
        source_lang="en",
        target_lang="ja",
        translation_text="こんにちは",
        translation_profile="",
        engine="dummy",
        created_at=now,
        last_used_at=now,
        hit_count=1,
    )
    cache_manager = MagicMock()
    cache_manager.search_translation_cache = AsyncMock(return_value=cache_entry)
    manager = TransManager(config, cache_manager=cache_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.fetch_cached_translation(trans_info)

    assert result is True
    assert trans_info.translated_text == "こんにちは"


@pytest.mark.asyncio
async def test_write_translation_cache_registers_engine_and_common(config: Config) -> None:
    cache_manager = MagicMock()
    cache_manager.register_translation_cache = AsyncMock(side_effect=[True, True])
    manager = TransManager(config, cache_manager=cache_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja", translated_text="こんにちは")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.write_translation_cache(trans_info)

    assert result is True
    assert cache_manager.register_translation_cache.await_count == 2


@pytest.mark.asyncio
async def test_write_translation_cache_returns_false_when_missing_languages(config: Config) -> None:
    cache_manager = MagicMock()
    cache_manager.register_translation_cache = AsyncMock(return_value=True)
    manager = TransManager(config, cache_manager=cache_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang=None, tgt_lang="", translated_text="こんにちは")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.write_translation_cache(trans_info)

    assert result is False
    cache_manager.register_translation_cache.assert_not_awaited()


def test_build_translation_hash_key_returns_none_without_languages() -> None:
    trans_info = TranslationInfo(content="hello", src_lang=None, tgt_lang="")

    hash_key: str | None = TransManager._build_translation_hash_key(trans_info)  # noqa: SLF001

    assert hash_key is None


@pytest.mark.asyncio
async def test_perform_translation_reuses_existing_translation(config: Config) -> None:
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", tgt_lang="ja", translated_text="pre")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    assert DummyEngine.translation_called is False


@pytest.mark.asyncio
async def test_perform_translation_uses_inflight_result(config: Config) -> None:
    inflight_manager = MagicMock()
    inflight_manager.mark_inflight_start = AsyncMock(return_value=Result(text="shared result"))
    manager = TransManager(config, inflight_manager=inflight_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    assert trans_info.translated_text == "shared result"
    assert DummyEngine.translation_called is False


@pytest.mark.asyncio
async def test_perform_translation_returns_false_on_inflight_timeout(config: Config) -> None:
    inflight_manager = MagicMock()
    inflight_manager.mark_inflight_start = AsyncMock(side_effect=TimeoutError("timeout"))
    manager = TransManager(config, inflight_manager=inflight_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja", translated_text="")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is False
    assert trans_info.translated_text == ""


@pytest.mark.asyncio
async def test_perform_translation_success_sets_text(config: Config) -> None:
    DummyEngine.translation_result = Result(text="konnichiwa")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    assert trans_info.translated_text == "konnichiwa"
    assert DummyEngine.translation_called is True


@pytest.mark.asyncio
async def test_perform_translation_success_stores_inflight_result(config: Config) -> None:
    inflight_manager = MagicMock()
    inflight_manager.mark_inflight_start = AsyncMock(return_value=None)
    inflight_manager.store_inflight_result = AsyncMock()
    manager = TransManager(config, inflight_manager=inflight_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="en", tgt_lang="ja")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is True
    inflight_manager.store_inflight_result.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_translation_handles_errors(config: Config) -> None:
    DummyEngine.translation_error = NotSupportedLanguagesError("bad")
    inflight_manager = MagicMock()
    inflight_manager.mark_inflight_start = AsyncMock(return_value=None)
    inflight_manager.store_inflight_exception = AsyncMock()
    manager = TransManager(config, inflight_manager=inflight_manager)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="xx", tgt_lang="yy")
    trans_info.engine = manager.current_engine_instance

    result: bool = await manager.perform_translation(trans_info)

    assert result is False
    assert trans_info.translated_text == ""
    inflight_manager.store_inflight_exception.assert_awaited_once()


@pytest.mark.asyncio
async def test_perform_translation_handles_quota_exceeded(config: Config) -> None:
    DummyEngine.translation_error = TranslationQuotaExceededError("quota")
    manager = TransManager(config)
    await manager.initialize()
    trans_info = TranslationInfo(content="hello", src_lang="xx", tgt_lang="yy")
    trans_info.engine = manager.current_engine_instance

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

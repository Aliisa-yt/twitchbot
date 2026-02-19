"""Tests for TranslationCacheManager.

Tests cache search, registration, in-flight management, TTL, and capacity limits.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from config.loader import Config
from core.cache.manager import TranslationCacheManager
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path
    from sqlite3 import Cursor

    from models.cache_models import CacheStatistics, LanguageDetectionCacheEntry, TranslationCacheEntry


@pytest.fixture
def mock_config() -> MagicMock:
    """Create a mock Config object."""
    return MagicMock(spec=Config)


@pytest.fixture
async def cache_manager(mock_config: MagicMock, tmp_path: Path) -> AsyncGenerator[TranslationCacheManager]:
    """Create a TranslationCacheManager instance with temporary database."""
    manager = TranslationCacheManager(mock_config)
    manager._db_path = tmp_path / "test_cache.db"
    await manager.component_load()
    yield manager
    await manager.component_teardown()


@pytest.mark.asyncio
async def test_cache_initialization(cache_manager: TranslationCacheManager) -> None:
    """Test cache manager initialization."""
    assert cache_manager._is_initialized is True
    assert cache_manager._db_conn is not None


@pytest.mark.asyncio
async def test_translation_cache_miss(cache_manager: TranslationCacheManager) -> None:
    """Test cache miss returns None."""
    result: TranslationCacheEntry | None = await cache_manager.search_translation_cache(
        source_text="Hello world",
        source_lang="en",
        target_lang="ja",
        engine="DeepL",
    )
    assert result is None


@pytest.mark.asyncio
async def test_translation_cache_registration(cache_manager: TranslationCacheManager) -> None:
    """Test cache registration."""
    success: bool = await cache_manager.register_translation_cache(
        source_text="Hello world",
        source_lang="en",
        target_lang="ja",
        translation_text="こんにちは世界",
        engine="DeepL",
    )
    assert success is True


@pytest.mark.asyncio
async def test_translation_cache_hit(cache_manager: TranslationCacheManager) -> None:
    """Test cache hit returns cached entry."""
    await cache_manager.register_translation_cache(
        source_text="Hello world",
        source_lang="en",
        target_lang="ja",
        translation_text="こんにちは世界",
        engine="DeepL",
    )

    result: TranslationCacheEntry | None = await cache_manager.search_translation_cache(
        source_text="Hello world",
        source_lang="en",
        target_lang="ja",
        engine="DeepL",
    )

    assert result is not None
    assert result.translation_text == "こんにちは世界"
    assert result.source_lang == "en"
    assert result.target_lang == "ja"
    assert result.engine == "DeepL"


@pytest.mark.asyncio
async def test_language_detection_cache(cache_manager: TranslationCacheManager) -> None:
    """Test language detection cache."""
    result: LanguageDetectionCacheEntry | None = await cache_manager.search_language_detection_cache("Hello world")
    assert result is None

    success: bool = await cache_manager.register_language_detection_cache("Hello world", "en", 0.95)
    assert success is True

    result = await cache_manager.search_language_detection_cache("Hello world")
    assert result is not None
    assert result.detected_lang == "en"
    assert result.confidence == 0.95


@pytest.mark.asyncio
async def test_cache_statistics(cache_manager: TranslationCacheManager) -> None:
    """Test cache statistics retrieval."""
    await cache_manager.register_translation_cache(
        source_text="Hello",
        source_lang="en",
        target_lang="ja",
        translation_text="こんにちは",
        engine="DeepL",
    )

    stats: CacheStatistics = await cache_manager.get_cache_statistics()
    assert stats.total_entries == 1
    assert "DeepL" in stats.engine_distribution


@pytest.mark.asyncio
async def test_cache_export(cache_manager: TranslationCacheManager, tmp_path: Path) -> None:
    """Test cache export functionality."""
    await cache_manager.register_translation_cache(
        source_text="Test",
        source_lang="en",
        target_lang="ja",
        translation_text="テスト",
        engine="DeepL",
    )

    output_path: Path = tmp_path / "cache_export.txt"
    success: bool = await cache_manager.export_cache_detailed(output_path)
    assert success is True
    assert output_path.exists()  # noqa: ASYNC240


@pytest.mark.asyncio
async def test_capacity_limit_enforcement(cache_manager: TranslationCacheManager) -> None:
    """Test capacity limit enforcement per engine."""
    original_limit: int = TranslationCacheManager.MAX_ENTRIES_PER_ENGINE
    TranslationCacheManager.MAX_ENTRIES_PER_ENGINE = 5

    for i in range(10):
        await cache_manager.register_translation_cache(
            source_text=f"Test {i}",
            source_lang="en",
            target_lang="ja",
            translation_text=f"テスト {i}",
            engine="DeepL",
        )

    stats: CacheStatistics = await cache_manager.get_cache_statistics()
    assert stats.engine_distribution["DeepL"] <= 5

    TranslationCacheManager.MAX_ENTRIES_PER_ENGINE = original_limit


@pytest.mark.asyncio
async def test_text_normalization(cache_manager: TranslationCacheManager) -> None:
    """Test Unicode normalization in cache keys."""
    await cache_manager.register_translation_cache(
        source_text="Café",  # Composed form
        source_lang="en",
        target_lang="ja",
        translation_text="カフェ",
        engine="DeepL",
    )

    result: TranslationCacheEntry | None = await cache_manager.search_translation_cache(
        source_text="Café",  # Should match even with different Unicode form
        source_lang="en",
        target_lang="ja",
        engine="DeepL",
    )

    assert result is not None
    assert result.translation_text == "カフェ"


@pytest.mark.asyncio
async def test_expired_translation_entry_is_deleted_on_lookup(cache_manager: TranslationCacheManager) -> None:
    """Expired translation cache entry should be deleted when accessed."""
    source_text = "Hello world"
    source_lang = "en"
    target_lang = "ja"
    engine = "DeepL"

    await cache_manager.register_translation_cache(
        source_text=source_text,
        source_lang=source_lang,
        target_lang=target_lang,
        translation_text="こんにちは世界",
        engine=engine,
    )

    normalized_source: str = StringUtils.normalize_text(source_text)
    cache_key: str = StringUtils.generate_hash_key(normalized_source, source_lang, target_lang, "", engine)
    assert cache_key is not None
    assert cache_manager._db_conn is not None

    expired_epoch = int(
        (datetime.now().astimezone() - timedelta(days=cache_manager.TTL_TRANSLATION_DAYS + 1)).timestamp()
    )
    cache_manager._db_conn.execute(
        "UPDATE translation_cache SET last_used_at = ? WHERE cache_key = ?",
        (expired_epoch, cache_key),
    )
    cache_manager._db_conn.commit()

    result: TranslationCacheEntry | None = await cache_manager.search_translation_cache(
        source_text=source_text,
        source_lang=source_lang,
        target_lang=target_lang,
        engine=engine,
    )

    assert result is None

    cursor: Cursor = cache_manager._db_conn.execute(
        "SELECT COUNT(*) FROM translation_cache WHERE cache_key = ?", (cache_key,)
    )
    assert cursor.fetchone()[0] == 0


@pytest.mark.asyncio
async def test_expired_language_detection_entry_is_deleted_on_lookup(cache_manager: TranslationCacheManager) -> None:
    """Expired language detection cache entry should be deleted when accessed."""
    source_text = "Hello world"
    normalized_source: str = StringUtils.normalize_text(source_text)

    await cache_manager.register_language_detection_cache(source_text, "en", 0.95)
    assert cache_manager._db_conn is not None

    expired_epoch = int(
        (datetime.now().astimezone() - timedelta(days=cache_manager.TTL_LANGUAGE_DETECTION_DAYS + 1)).timestamp()
    )
    cache_manager._db_conn.execute(
        "UPDATE language_detection_cache SET last_used_at = ? WHERE normalized_source = ?",
        (expired_epoch, normalized_source),
    )
    cache_manager._db_conn.commit()

    result: LanguageDetectionCacheEntry | None = await cache_manager.search_language_detection_cache(source_text)

    assert result is None

    cursor: Cursor = cache_manager._db_conn.execute(
        "SELECT COUNT(*) FROM language_detection_cache WHERE normalized_source = ?",
        (normalized_source,),
    )
    assert cursor.fetchone()[0] == 0

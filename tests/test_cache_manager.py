"""Tests for TranslationCacheManager.

Tests cache search, registration, in-flight management, TTL, and capacity limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from config.loader import Config
from core.cache.manager import TranslationCacheManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path


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
    result = await cache_manager.search_translation_cache(
        source_text="Hello world",
        source_lang="en",
        target_lang="ja",
        engine="DeepL",
    )
    assert result is None


@pytest.mark.asyncio
async def test_translation_cache_registration(cache_manager: TranslationCacheManager) -> None:
    """Test cache registration."""
    success = await cache_manager.register_translation_cache(
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

    result = await cache_manager.search_translation_cache(
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
    result = await cache_manager.search_language_detection_cache("Hello world")
    assert result is None

    success = await cache_manager.register_language_detection_cache("Hello world", "en", 0.95)
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

    stats = await cache_manager.get_cache_statistics()
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

    output_path = tmp_path / "cache_export.txt"
    success = await cache_manager.export_cache_detailed(output_path)
    assert success is True
    assert output_path.exists()


@pytest.mark.asyncio
async def test_capacity_limit_enforcement(cache_manager: TranslationCacheManager) -> None:
    """Test capacity limit enforcement per engine."""
    original_limit = TranslationCacheManager.MAX_ENTRIES_PER_ENGINE
    TranslationCacheManager.MAX_ENTRIES_PER_ENGINE = 5

    for i in range(10):
        await cache_manager.register_translation_cache(
            source_text=f"Test {i}",
            source_lang="en",
            target_lang="ja",
            translation_text=f"テスト {i}",
            engine="DeepL",
        )

    stats = await cache_manager.get_cache_statistics()
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

    result = await cache_manager.search_translation_cache(
        source_text="Café",  # Should match even with different Unicode form
        source_lang="en",
        target_lang="ja",
        engine="DeepL",
    )

    assert result is not None
    assert result.translation_text == "カフェ"


@pytest.mark.asyncio
async def test_cache_length_limit_blocks_operations(cache_manager: TranslationCacheManager) -> None:
    """Test cache operations are skipped when text exceeds length limit."""
    original_limit = TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT
    TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT = 5

    try:
        long_text = "Hello world"
        success = await cache_manager.register_translation_cache(
            source_text=long_text,
            source_lang="en",
            target_lang="ja",
            translation_text="こんにちは世界",
            engine="DeepL",
        )
        assert success is False

        result = await cache_manager.search_translation_cache(
            source_text=long_text,
            source_lang="en",
            target_lang="ja",
            engine="DeepL",
        )
        assert result is None

        detection = await cache_manager.search_language_detection_cache(long_text)
        assert detection is None
    finally:
        TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT = original_limit


@pytest.mark.asyncio
async def test_cache_length_limit_zero_is_unlimited(cache_manager: TranslationCacheManager) -> None:
    """Test zero length limit allows caching."""
    original_limit = TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT
    TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT = 0

    try:
        text = "Hello world"
        success = await cache_manager.register_translation_cache(
            source_text=text,
            source_lang="en",
            target_lang="ja",
            translation_text="こんにちは世界",
            engine="DeepL",
        )
        assert success is True

        result = await cache_manager.search_translation_cache(
            source_text=text,
            source_lang="en",
            target_lang="ja",
            engine="DeepL",
        )
        assert result is not None
        assert result.translation_text == "こんにちは世界"
    finally:
        TranslationCacheManager.CACHE_TEXT_LENGTH_LIMIT = original_limit

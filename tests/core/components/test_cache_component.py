"""Unit tests for core.components.cache_component module."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.components.cache_component import CacheServiceComponent
from models.cache_models import CacheStatistics

if TYPE_CHECKING:
    from pathlib import Path


def _make_context(*, broadcaster: bool = True) -> MagicMock:
    context = MagicMock()
    author = MagicMock()
    author.name = "tester"
    author.broadcaster = broadcaster
    context.author = author
    context.send = AsyncMock()
    context.bot = MagicMock()
    return context


@pytest.fixture
def cache_bundle() -> SimpleNamespace:
    cache_manager: MagicMock = MagicMock()
    cache_manager.is_initialized = False
    cache_manager.component_load = AsyncMock()
    cache_manager.get_cache_statistics = AsyncMock()
    cache_manager.export_cache_detailed = AsyncMock(return_value=True)
    cache_manager.register_language_detection_cache = AsyncMock(return_value=True)
    cache_manager.register_translation_cache = AsyncMock(return_value=True)

    shared: MagicMock = MagicMock()
    shared.config = MagicMock()
    shared.config.DICTIONARY.PATH = ""
    shared.trans_manager = MagicMock()
    shared.tts_manager = MagicMock()
    shared.cache_manager = cache_manager

    bot: MagicMock = MagicMock()
    bot.shared_data = shared
    bot.print_console_message = MagicMock()

    component = CacheServiceComponent(bot)

    return SimpleNamespace(component=component, cache_manager=cache_manager, bot=bot)


@pytest.mark.asyncio
async def test_load_predefined_translation_cache_registers_both_caches(
    cache_bundle: SimpleNamespace, tmp_path: Path
) -> None:
    dictionary_file: Path = tmp_path / "translation_cache.dic"
    await asyncio.to_thread(
        dictionary_file.write_text,
        "# source text, source language, translation text, target language\n"
        "Hi,en,こんにちは,ja\n"
        '"Hello, world",en,"こんにちは、世界",ja\n',
        encoding="utf-8",
    )
    cache_bundle.component.config.DICTIONARY.PATH = str(tmp_path)

    await cache_bundle.component._load_predefined_translation_cache()

    assert cache_bundle.cache_manager.register_language_detection_cache.await_args_list[0].args == ("Hi", "en")
    assert cache_bundle.cache_manager.register_language_detection_cache.await_args_list[1].args == (
        "Hello, world",
        "en",
    )
    assert cache_bundle.cache_manager.register_translation_cache.await_args_list[0].kwargs == {
        "source_text": "Hi",
        "source_lang": "en",
        "target_lang": "ja",
        "translation_text": "こんにちは",
        "engine": "",
    }
    assert cache_bundle.cache_manager.register_translation_cache.await_args_list[1].kwargs == {
        "source_text": "Hello, world",
        "source_lang": "en",
        "target_lang": "ja",
        "translation_text": "こんにちは、世界",
        "engine": "",
    }


@pytest.mark.asyncio
async def test_load_predefined_translation_cache_skips_invalid_rows(
    cache_bundle: SimpleNamespace, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dictionary_file: Path = tmp_path / "translation_cache.dic"
    await asyncio.to_thread(
        dictionary_file.write_text,
        "\n# comment\nHi,en,こんにちは\nHello,,こんにちは,ja\n",
        encoding="utf-8",
    )
    cache_bundle.component.config.DICTIONARY.PATH = str(tmp_path)

    await cache_bundle.component._load_predefined_translation_cache()

    cache_bundle.cache_manager.register_language_detection_cache.assert_not_awaited()
    cache_bundle.cache_manager.register_translation_cache.assert_not_awaited()
    assert "expected 4 columns" in caplog.text
    assert "empty column" in caplog.text


@pytest.mark.asyncio
async def test_component_load_preloads_dictionary_after_cache_initialization(cache_bundle: SimpleNamespace) -> None:
    cache_bundle.component._load_predefined_translation_cache = AsyncMock()
    cache_bundle.component.cache_maintenance.start = MagicMock()

    await cache_bundle.component.component_load()

    cache_bundle.cache_manager.component_load.assert_awaited_once()
    cache_bundle.component._load_predefined_translation_cache.assert_awaited_once()
    cache_bundle.component.cache_maintenance.start.assert_called_once()


@pytest.mark.asyncio
async def test_cache_stats_reports_not_initialized(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = False

    await cache_bundle.component.cache_stats.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Translation cache is not initialized.", header=None, footer=None
    )
    context.send.assert_called_once_with("Translation cache is not initialized.")


@pytest.mark.asyncio
async def test_cache_stats_prints_summary_lines(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = True
    cache_bundle.cache_manager.get_cache_statistics = AsyncMock(
        return_value=CacheStatistics(
            total_entries=3,
            total_hits=7,
            hit_distribution={5: 1, 1: 2, 0: 4},
            engine_distribution={"": 1, "deepl": 2},
        )
    )

    await cache_bundle.component.cache_stats.callback(cache_bundle.component, context)

    sent_lines: list[str] = [call.args[0] for call in cache_bundle.bot.print_console_message.call_args_list]
    assert "----- Translation Cache Statistics -----" in sent_lines
    assert "Total entries: 3" in sent_lines
    assert "Total hits: 7" in sent_lines
    assert "By engine: common: 1, deepl: 2" in sent_lines
    assert any("5 hits: 1 entries" in line for line in sent_lines)
    context.send.assert_called_once_with("Cache statistics displayed in console.")


@pytest.mark.asyncio
async def test_cache_export_reports_not_initialized(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = False

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Translation cache is not initialized.", header=None, footer=None
    )
    context.send.assert_called_once_with("Translation cache is not initialized.")


@pytest.mark.asyncio
async def test_cache_export_prints_success_message(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = True
    cache_bundle.cache_manager.export_cache_detailed = AsyncMock(return_value=True)

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    sent_lines: list[str] = [call.args[0] for call in cache_bundle.bot.print_console_message.call_args_list]
    assert any("Cache data exported to: " in line for line in sent_lines)
    context.send.assert_called_once_with("Cache data export completed successfully.")


@pytest.mark.asyncio
async def test_cache_export_prints_failure_message(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = True
    cache_bundle.cache_manager.export_cache_detailed = AsyncMock(return_value=False)

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Failed to export cache data.", header=None, footer=None
    )
    context.send.assert_called_once_with("Failed to export cache data.")

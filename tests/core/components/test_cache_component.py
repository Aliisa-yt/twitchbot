"""Unit tests for core.components.cache_component module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.components.cache_component import CacheServiceComponent
from models.cache_models import CacheStatistics


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
    cache_manager = MagicMock()
    cache_manager.is_initialized = False
    cache_manager.get_cache_statistics = AsyncMock()
    cache_manager.export_cache_detailed = AsyncMock(return_value=True)

    shared = MagicMock()
    shared.config = MagicMock()
    shared.trans_manager = MagicMock()
    shared.tts_manager = MagicMock()
    shared.cache_manager = cache_manager

    bot = MagicMock()
    bot.shared_data = shared
    bot.print_console_message = MagicMock()

    component = CacheServiceComponent(bot)

    return SimpleNamespace(component=component, cache_manager=cache_manager, bot=bot)


@pytest.mark.asyncio
async def test_cache_stats_reports_not_initialized(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = False

    await cache_bundle.component.cache_stats.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Translation cache is not initialized.", header=None, footer=None
    )


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


@pytest.mark.asyncio
async def test_cache_export_reports_not_initialized(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = False

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Translation cache is not initialized.", header=None, footer=None
    )


@pytest.mark.asyncio
async def test_cache_export_prints_success_message(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = True
    cache_bundle.cache_manager.export_cache_detailed = AsyncMock(return_value=True)

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Cache data exported to: cache_export.log", header=None, footer=None
    )


@pytest.mark.asyncio
async def test_cache_export_prints_failure_message(cache_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    cache_bundle.cache_manager.is_initialized = True
    cache_bundle.cache_manager.export_cache_detailed = AsyncMock(return_value=False)

    await cache_bundle.component.cache_export.callback(cache_bundle.component, context)

    cache_bundle.bot.print_console_message.assert_called_once_with(
        "Failed to export cache data.", header=None, footer=None
    )

"""Unit tests for core.components.trans_component module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.trans_component import TranslationServiceComponent
from models.translation_models import CharacterQuota


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
def trans_bundle() -> SimpleNamespace:
    trans_manager = MagicMock()
    trans_manager.get_usage = AsyncMock()

    shared = MagicMock()
    shared.config = MagicMock()
    shared.trans_manager = trans_manager
    shared.tts_manager = MagicMock()

    bot = MagicMock()
    bot.shared_data = shared

    component = TranslationServiceComponent(bot)

    return SimpleNamespace(component=component, trans_manager=trans_manager)


@pytest.mark.asyncio
async def test_change_translation_engine_reports_current(trans_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with patch("core.components.trans_component.TransManager.fetch_engine_names", return_value=["google", "deepl"]):
        await trans_bundle.component.change_translation_engine.callback(trans_bundle.component, context)

    context.send.assert_called_once_with("The current translation engine is 'google'.")


@pytest.mark.asyncio
async def test_change_translation_engine_switches_when_valid(trans_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with (
        patch("core.components.trans_component.TransManager.fetch_engine_names", return_value=["google", "deepl"]),
        patch("core.components.trans_component.TransManager.update_engine_names") as update_names,
    ):
        await trans_bundle.component.change_translation_engine.callback(trans_bundle.component, context, "deepl")

    update_names.assert_called_once_with(["deepl", "google"])
    context.send.assert_called_once_with("Translation engine switched to 'deepl'.")


@pytest.mark.asyncio
async def test_change_translation_engine_shows_usage_on_invalid(trans_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with patch("core.components.trans_component.TransManager.fetch_engine_names", return_value=["google", "deepl"]):
        await trans_bundle.component.change_translation_engine.callback(trans_bundle.component, context, "invalid")

    context.send.assert_called_once_with("Usage: !te [google|deepl]")


@pytest.mark.asyncio
async def test_trans_usage_reports_quota(trans_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    trans_bundle.trans_manager.get_usage = AsyncMock(
        return_value=CharacterQuota(count=5, limit=10, is_quota_valid=True)
    )

    await trans_bundle.component.trans_usage.callback(trans_bundle.component, context)

    context.send.assert_called_once_with("Character usage: 5/10 (50.00%)")


@pytest.mark.asyncio
async def test_trans_usage_handles_invalid_quota(trans_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    trans_bundle.trans_manager.get_usage = AsyncMock(
        return_value=CharacterQuota(count=0, limit=0, is_quota_valid=False)
    )

    await trans_bundle.component.trans_usage.callback(trans_bundle.component, context)

    context.send.assert_called_once_with(
        "The current translation engine is unable to use information about character usage."
    )

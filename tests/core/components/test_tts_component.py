"""Unit tests for core.components.tts_component module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.components.tts_component import TTSServiceComponent


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
def tts_bundle() -> SimpleNamespace:
    playback_manager = MagicMock()
    playback_manager.is_playing = False
    playback_manager.cancel_playback = AsyncMock()

    tts_manager = MagicMock()
    tts_manager.playback_manager = playback_manager

    shared = MagicMock()
    shared.config = MagicMock()
    shared.trans_manager = MagicMock()
    shared.tts_manager = tts_manager

    bot = MagicMock()
    bot.shared_data = shared

    component = TTSServiceComponent(bot)

    return SimpleNamespace(component=component, playback_manager=playback_manager)


@pytest.mark.asyncio
async def test_skip_cancels_playback_when_playing(tts_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    tts_bundle.playback_manager.is_playing = True

    await tts_bundle.component.skip.callback(tts_bundle.component, context)

    tts_bundle.playback_manager.cancel_playback.assert_called_once()
    context.send.assert_called_once_with("Current playback cancelled.")


@pytest.mark.asyncio
async def test_skip_does_nothing_when_not_playing(tts_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    tts_bundle.playback_manager.is_playing = False

    await tts_bundle.component.skip.callback(tts_bundle.component, context)

    tts_bundle.playback_manager.cancel_playback.assert_not_called()
    context.send.assert_not_called()

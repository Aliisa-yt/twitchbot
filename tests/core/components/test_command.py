"""Unit tests for core.components.command module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.command import BotCommandManager
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
def command_bundle() -> SimpleNamespace:
    config = MagicMock()
    config.GENERAL = MagicMock()
    config.GENERAL.SCRIPT_NAME = "twitchbot"
    config.GENERAL.VERSION = "1.2.3"

    trans_manager = MagicMock()
    trans_manager.get_usage = AsyncMock()

    playback_manager = MagicMock()
    playback_manager.is_playing = False
    playback_manager.cancel_playback = AsyncMock()

    tts_manager = MagicMock()
    tts_manager.playback_manager = playback_manager

    shared = MagicMock()
    shared.config = config
    shared.trans_manager = trans_manager
    shared.tts_manager = tts_manager

    bot = MagicMock()
    bot.shared_data = shared

    command = BotCommandManager(bot)

    return SimpleNamespace(command=command, trans_manager=trans_manager, playback_manager=playback_manager)


@pytest.mark.asyncio
async def test_skip_denied_for_non_broadcaster(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=False)
    command_bundle.playback_manager.is_playing = True

    await command_bundle.command.skip.callback(command_bundle.command, context)

    context.send.assert_called_once_with("This command is available to the broadcaster only.")
    command_bundle.playback_manager.cancel_playback.assert_not_called()


@pytest.mark.asyncio
async def test_skip_cancels_playback_when_playing(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    command_bundle.playback_manager.is_playing = True

    await command_bundle.command.skip.callback(command_bundle.command, context)

    command_bundle.playback_manager.cancel_playback.assert_called_once()
    context.send.assert_called_once_with("Current playback cancelled.")


@pytest.mark.asyncio
async def test_ver_sends_version(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    await command_bundle.command.ver.callback(command_bundle.command, context)

    context.send.assert_called_once_with("Current version is 'twitchbot ver.1.2.3'")


@pytest.mark.asyncio
async def test_change_translation_engine_reports_current(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with patch("core.components.command.TransManager.get_trans_engine_names", return_value=["google", "deepl"]):
        await command_bundle.command.change_translation_engine.callback(command_bundle.command, context)

    context.send.assert_called_once_with("The current translation engine is 'google'.")


@pytest.mark.asyncio
async def test_change_translation_engine_switches_when_valid(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with (
        patch("core.components.command.TransManager.get_trans_engine_names", return_value=["google", "deepl"]),
        patch("core.components.command.TransManager.set_trans_engine_names") as set_names,
    ):
        await command_bundle.command.change_translation_engine.callback(command_bundle.command, context, "deepl")

    set_names.assert_called_once_with(["deepl", "google"])
    context.send.assert_called_once_with("Translation engine switched to 'deepl'.")


@pytest.mark.asyncio
async def test_change_translation_engine_shows_usage_on_invalid(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with patch("core.components.command.TransManager.get_trans_engine_names", return_value=["google", "deepl"]):
        await command_bundle.command.change_translation_engine.callback(command_bundle.command, context, "invalid")

    context.send.assert_called_once_with("Usage: !te [google|deepl]")


@pytest.mark.asyncio
async def test_trans_usage_reports_quota(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    command_bundle.trans_manager.get_usage = AsyncMock(
        return_value=CharacterQuota(count=5, limit=10, is_quota_valid=True)
    )

    await command_bundle.command.trans_usage.callback(command_bundle.command, context)

    context.send.assert_called_once_with("Character usage: 5/10 (50.00%)")


@pytest.mark.asyncio
async def test_trans_usage_handles_invalid_quota(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    command_bundle.trans_manager.get_usage = AsyncMock(
        return_value=CharacterQuota(count=0, limit=0, is_quota_valid=False)
    )

    await command_bundle.command.trans_usage.callback(command_bundle.command, context)

    context.send.assert_called_once_with(
        "The current translation engine is unable to use information about character usage."
    )


def _make_command_obj(doc: str | None) -> MagicMock:
    def _callback() -> None:
        return None

    _callback.__doc__ = doc
    command = MagicMock()
    command.callback = _callback
    return command


@pytest.mark.asyncio
async def test_help_shows_command_list(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    context.bot.commands = {
        "skip": _make_command_obj("Skip the current playback."),
        "ver": _make_command_obj("Display the version."),
    }

    await command_bundle.command.help.callback(command_bundle.command, context)

    context.send.assert_called_once_with("Available commands: !skip, !ver")


@pytest.mark.asyncio
async def test_help_shows_specific_command(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    context.bot.commands = {
        "skip": _make_command_obj("Skip the current playback.\n\nArgs:\n  context: ..."),
        "ver": _make_command_obj("Display the version."),
    }

    await command_bundle.command.help.callback(command_bundle.command, context, "skip")

    context.send.assert_called_once_with("!skip: Skip the current playback.")


@pytest.mark.asyncio
async def test_help_shows_list_when_unknown(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    context.bot.commands = {
        "skip": _make_command_obj("Skip the current playback."),
        "ver": _make_command_obj("Display the version."),
    }

    await command_bundle.command.help.callback(command_bundle.command, context, "unknown")

    context.send.assert_called_once_with("Available commands: !skip, !ver")

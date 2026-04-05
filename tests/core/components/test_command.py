"""Unit tests for core.components.command module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.command import BotCommandManager


class DummyRemovableComponent:
    def __init__(self, bot: MagicMock) -> None:
        self.bot = bot


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

    shared = MagicMock()
    shared.config = config
    shared.trans_manager = MagicMock()
    shared.tts_manager = MagicMock()

    bot = MagicMock()
    bot.shared_data = shared

    command = BotCommandManager(bot)

    return SimpleNamespace(command=command)


@pytest.mark.asyncio
async def test_ver_sends_version(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    await command_bundle.command.ver.callback(command_bundle.command, context)

    context.send.assert_called_once_with("Current version is 'twitchbot ver.1.2.3'")


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


@pytest.mark.asyncio
async def test_attach_shows_usage_when_no_args(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)

    with patch.object(BotCommandManager, "_get_removable_component_classes", return_value=[]):
        await command_bundle.command.attach.callback(command_bundle.command, context)

    context.send.assert_called_once_with("Usage: !attach <component name>. Available: ")


@pytest.mark.asyncio
async def test_attach_adds_component_when_valid(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    command_bundle.command.bot.attached_components = []
    command_bundle.command.bot.attach_component = AsyncMock()

    with patch.object(BotCommandManager, "_get_removable_component_classes", return_value=[DummyRemovableComponent]):
        await command_bundle.command.attach.callback(command_bundle.command, context, "DummyRemovableComponent")

    command_bundle.command.bot.attach_component.assert_called_once()
    context.send.assert_called_once_with("Component 'DummyRemovableComponent' attached.")


@pytest.mark.asyncio
async def test_detach_reports_not_attached(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    command_bundle.command.bot.attached_components = []

    with patch.object(BotCommandManager, "_get_removable_component_classes", return_value=[DummyRemovableComponent]):
        await command_bundle.command.detach.callback(command_bundle.command, context, "DummyRemovableComponent")

    context.send.assert_called_once_with("Component 'DummyRemovableComponent' is not attached.")


@pytest.mark.asyncio
async def test_detach_removes_component_when_attached(command_bundle: SimpleNamespace) -> None:
    context: MagicMock = _make_context(broadcaster=True)
    attached_component = DummyRemovableComponent(command_bundle.command.bot)
    command_bundle.command.bot.attached_components = [attached_component]
    command_bundle.command.bot.detach_component = AsyncMock()

    with patch.object(BotCommandManager, "_get_removable_component_classes", return_value=[DummyRemovableComponent]):
        await command_bundle.command.detach.callback(command_bundle.command, context, "DummyRemovableComponent")

    command_bundle.command.bot.detach_component.assert_called_once_with(attached_component)
    context.send.assert_called_once_with("Component 'DummyRemovableComponent' detached.")

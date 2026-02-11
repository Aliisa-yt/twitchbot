"""Unit tests for core.bot module."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from twitchio.ext.commands import ComponentLoadError

from config.loader import Config
from core.bot import Bot
from core.components import ComponentBase, ComponentDescriptor
from core.token_manager import TwitchBotToken

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class DummyComponent(ComponentBase):
    """Minimal component for tests."""


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration object."""
    config = MagicMock(spec=Config)
    config.BOT = MagicMock()
    config.BOT.COLOR = "blue"
    config.BOT.LOGIN_MESSAGE = "Bot is ready"
    config.BOT.DONT_LOGIN_MESSAGE = False
    config.BOT.CONSOLE_OUTPUT = True
    return config


@pytest.fixture
def mock_token_data() -> TwitchBotToken:
    """Create a mock token data object."""
    return TwitchBotToken(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        bot_id="123456789",
        owner_id="987654321",
    )


@pytest.fixture
async def bot_instance(mock_config: Config, mock_token_data: TwitchBotToken) -> AsyncGenerator[Bot]:
    """Create a Bot instance for testing."""
    shared_data = MagicMock(spec_set=["async_init"])
    shared_data.async_init = AsyncMock()

    with (
        patch("core.bot.commands.Bot.__init__", return_value=None),
        patch("core.bot.LoggerUtils.get_logger"),
        patch("core.bot.SharedData", return_value=shared_data),
    ):
        bot = Bot(mock_config, mock_token_data)
        bot.add_component = AsyncMock()
        bot.remove_component = AsyncMock()
        bot.add_token = AsyncMock()
        bot.subscribe_websocket = AsyncMock()
        bot.create_partialuser = MagicMock()
        bot.shared_data = shared_data
        yield bot


class TestBotInitialization:
    """Test Bot initialization."""

    def test_bot_init_sets_properties(self, mock_config: Config, mock_token_data: TwitchBotToken) -> None:
        """Test that Bot initialization sets required properties."""
        shared_data = MagicMock()
        with (
            patch("core.bot.commands.Bot.__init__", return_value=None),
            patch("core.bot.LoggerUtils.get_logger"),
            patch("core.bot.SharedData", return_value=shared_data),
        ):
            bot = Bot(mock_config, mock_token_data)

        assert bot.config == mock_config
        assert bot._token_data == mock_token_data
        assert bot._closed is False
        assert bot.attached_components == []

    def test_bot_properties(self, bot_instance: Bot, mock_token_data: TwitchBotToken) -> None:
        """Test that Bot properties return correct values."""
        assert bot_instance.client_id == mock_token_data.client_id
        assert bot_instance.client_secret == mock_token_data.client_secret
        assert bot_instance.bot_id == mock_token_data.bot_id
        assert bot_instance.owner_id == mock_token_data.owner_id
        assert bot_instance.access_token == mock_token_data.access_token
        assert bot_instance.refresh_token == mock_token_data.refresh_token


class TestBotSetupHook:
    """Test setup hook behavior."""

    @pytest.mark.asyncio
    async def test_setup_hook_attaches_components(self, bot_instance: Bot) -> None:
        """Test that setup_hook attaches components from the priority list."""
        shared_data_async_init = AsyncMock()
        bot_instance.shared_data.async_init = shared_data_async_init
        attach_component = AsyncMock()
        bot_instance.attach_component = attach_component
        component_registry: dict[str, ComponentDescriptor] = {
            "DummyComponent": ComponentDescriptor(
                component=DummyComponent,
                depends=[],
                is_removable=False,
            )
        }
        with (
            patch.object(ComponentBase, "component_registry", component_registry),
        ):
            await bot_instance.setup_hook()

        shared_data_async_init.assert_called_once()
        assert attach_component.call_count == 1
        attached = [call_args.args[0].__class__ for call_args in attach_component.call_args_list]
        assert DummyComponent in attached

    @pytest.mark.asyncio
    async def test_setup_hook_validates_dependencies(self, bot_instance: Bot) -> None:
        """Test that setup_hook validates dependencies before attaching components."""
        shared_data_async_init = AsyncMock()
        bot_instance.shared_data.async_init = shared_data_async_init
        validate_dependencies = MagicMock()
        bot_instance.validate_dependencies = validate_dependencies

        component_registry: dict[str, ComponentDescriptor] = {
            "DummyComponent": ComponentDescriptor(
                component=DummyComponent,
                depends=[],
                is_removable=False,
            )
        }
        with (
            patch.object(ComponentBase, "component_registry", component_registry),
        ):
            await bot_instance.setup_hook()

        validate_dependencies.assert_called_once_with(component_registry)


class TestDependencyResolution:
    """Test component dependency validation and ordering."""

    def test_validate_dependencies_accepts_known(self, bot_instance: Bot) -> None:
        """Test validate_dependencies with known components."""
        deps: dict[str, ComponentDescriptor] = {
            "A": ComponentDescriptor(component=DummyComponent, depends=[], is_removable=False),
            "B": ComponentDescriptor(component=DummyComponent, depends=["A"], is_removable=False),
        }

        bot_instance.validate_dependencies(deps)

    def test_validate_dependencies_rejects_unknown(self, bot_instance: Bot) -> None:
        """Test validate_dependencies raises for missing components."""
        deps: dict[str, ComponentDescriptor] = {
            "A": ComponentDescriptor(component=DummyComponent, depends=["Missing"], is_removable=False)
        }

        with pytest.raises(RuntimeError, match="depends on unknown component"):
            bot_instance.validate_dependencies(deps)

    def test_resolve_dependencies_orders_components(self, bot_instance: Bot) -> None:
        """Test resolve_dependencies returns a valid topological order."""
        deps: dict[str, ComponentDescriptor] = {
            "A": ComponentDescriptor(component=DummyComponent, depends=[], is_removable=False),
            "B": ComponentDescriptor(component=DummyComponent, depends=["A"], is_removable=False),
            "C": ComponentDescriptor(component=DummyComponent, depends=["B"], is_removable=False),
        }

        order: list[str] = bot_instance.resolve_dependencies(deps)

        assert order == ["A", "B", "C"]

    def test_resolve_dependencies_detects_cycle(self, bot_instance: Bot) -> None:
        """Test resolve_dependencies raises for cycles."""
        deps: dict[str, ComponentDescriptor] = {
            "A": ComponentDescriptor(component=DummyComponent, depends=["B"], is_removable=False),
            "B": ComponentDescriptor(component=DummyComponent, depends=["A"], is_removable=False),
        }

        with pytest.raises(RuntimeError, match="Circular dependency detected"):
            bot_instance.resolve_dependencies(deps)


class TestComponentAttachDetach:
    """Test component attach and detach methods."""

    @pytest.mark.asyncio
    async def test_attach_component_success(self, bot_instance: Bot) -> None:
        """Test attaching a component successfully."""
        component = DummyComponent(bot_instance)
        add_component = AsyncMock()
        bot_instance.add_component = add_component

        await bot_instance.attach_component(component)

        add_component.assert_awaited_once_with(component)
        assert component in bot_instance.attached_components

    @pytest.mark.asyncio
    async def test_attach_component_failure(self, bot_instance: Bot) -> None:
        """Test attach_component handles load errors."""
        component = DummyComponent(bot_instance)
        add_component = AsyncMock()
        add_component.side_effect = ComponentLoadError("duplicate")
        bot_instance.add_component = add_component

        await bot_instance.attach_component(component)

        assert component not in bot_instance.attached_components

    @pytest.mark.asyncio
    async def test_detach_component_success(self, bot_instance: Bot) -> None:
        """Test detaching a component successfully."""
        component = DummyComponent(bot_instance)
        bot_instance.attached_components.append(component)
        remove_component = AsyncMock()
        bot_instance.remove_component = remove_component

        await bot_instance.detach_component(component)

        remove_component.assert_awaited_once_with(component.__class__.__name__)
        assert component not in bot_instance.attached_components

    @pytest.mark.asyncio
    async def test_detach_component_removes_on_error(self, bot_instance: Bot) -> None:
        """Test detaching a component removes it even when unregister fails."""
        component = DummyComponent(bot_instance)
        bot_instance.attached_components.append(component)
        remove_component = AsyncMock()
        remove_component.side_effect = ValueError("missing")
        bot_instance.remove_component = remove_component

        await bot_instance.detach_component(component)

        assert component not in bot_instance.attached_components


class TestEventHandlers:
    """Test event handler methods."""

    @pytest.mark.asyncio
    async def test_event_ready_sends_login_message(self, bot_instance: Bot) -> None:
        """Test event_ready sends login message when enabled."""
        bot_instance.config.BOT.DONT_LOGIN_MESSAGE = False
        mock_chatter = AsyncMock()
        mock_chatter.update_chatter_color = AsyncMock()
        create_partialuser = MagicMock(return_value=mock_chatter)
        subscribe_to_chat_events = AsyncMock()
        send_chat_message = AsyncMock()
        print_console_message = MagicMock()
        bot_instance.create_partialuser = create_partialuser
        bot_instance._subscribe_to_chat_events = subscribe_to_chat_events
        bot_instance.send_chat_message = send_chat_message
        bot_instance.print_console_message = print_console_message

        await bot_instance.event_ready()

        subscribe_to_chat_events.assert_called_once()
        mock_chatter.update_chatter_color.assert_called_once_with(bot_instance.config.BOT.COLOR)
        send_chat_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_event_ready_skips_login_message(self, bot_instance: Bot) -> None:
        """Test event_ready skips login message when disabled."""
        bot_instance.config.BOT.DONT_LOGIN_MESSAGE = True
        mock_chatter = AsyncMock()
        mock_chatter.update_chatter_color = AsyncMock()
        create_partialuser = MagicMock(return_value=mock_chatter)
        subscribe_to_chat_events = AsyncMock()
        send_chat_message = AsyncMock()
        print_console_message = MagicMock()
        bot_instance.create_partialuser = create_partialuser
        bot_instance._subscribe_to_chat_events = subscribe_to_chat_events
        bot_instance.send_chat_message = send_chat_message
        bot_instance.print_console_message = print_console_message

        await bot_instance.event_ready()

        send_chat_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_oauth_authorized_no_user_id(self, bot_instance: Bot) -> None:
        """Test event_oauth_authorized with missing user ID."""
        payload = MagicMock()
        payload.access_token = "new_access_token"
        payload.refresh_token = "new_refresh_token"
        payload.user_id = None
        add_token = AsyncMock()
        subscribe_websocket = AsyncMock()
        bot_instance.add_token = add_token
        bot_instance.subscribe_websocket = subscribe_websocket

        await bot_instance.event_oauth_authorized(payload)

        add_token.assert_called_once_with("new_access_token", "new_refresh_token")
        subscribe_websocket.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_oauth_authorized_bot_user_id(self, bot_instance: Bot) -> None:
        """Test event_oauth_authorized with bot user ID."""
        payload = MagicMock()
        payload.access_token = "new_access_token"
        payload.refresh_token = "new_refresh_token"
        payload.user_id = bot_instance.bot_id
        add_token = AsyncMock()
        subscribe_websocket = AsyncMock()
        bot_instance.add_token = add_token
        bot_instance.subscribe_websocket = subscribe_websocket

        await bot_instance.event_oauth_authorized(payload)

        add_token.assert_called_once_with("new_access_token", "new_refresh_token")
        subscribe_websocket.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_oauth_authorized_other_user_id(self, bot_instance: Bot) -> None:
        """Test event_oauth_authorized subscribes for other user IDs."""
        payload = MagicMock()
        payload.access_token = "new_access_token"
        payload.refresh_token = "new_refresh_token"
        payload.user_id = "555555"
        add_token = AsyncMock()
        subscribe_websocket = AsyncMock()
        bot_instance.add_token = add_token
        bot_instance.subscribe_websocket = subscribe_websocket

        await bot_instance.event_oauth_authorized(payload)

        add_token.assert_called_once_with("new_access_token", "new_refresh_token")
        subscribe_websocket.assert_awaited_once()


class TestSubscribeEvents:
    """Test chat event subscription."""

    @pytest.mark.asyncio
    async def test_subscribe_to_chat_events(self, bot_instance: Bot) -> None:
        """Test subscribing to chat events."""
        add_token = AsyncMock()
        subscribe_websocket = AsyncMock()
        bot_instance.add_token = add_token
        bot_instance.subscribe_websocket = subscribe_websocket

        await bot_instance._subscribe_to_chat_events()

        add_token.assert_called_once_with(bot_instance.access_token, bot_instance.refresh_token)
        assert subscribe_websocket.call_count == 4


class TestSendChatMessage:
    """Test send_chat_message method."""

    @pytest.mark.asyncio
    async def test_send_chat_message_with_chatter(self, bot_instance: Bot) -> None:
        """Test sending a message to a specific chatter."""
        mock_chatter = AsyncMock()
        mock_sent_message = MagicMock()
        mock_sent_message.sent = True
        mock_chatter.send_message = AsyncMock(return_value=mock_sent_message)

        await bot_instance.send_chat_message("Test message", chatter=mock_chatter)

        mock_chatter.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_chat_message_empty_content(self, bot_instance: Bot) -> None:
        """Test that empty content is not sent."""
        mock_chatter = AsyncMock()

        await bot_instance.send_chat_message(None, chatter=mock_chatter)

        mock_chatter.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_chat_message_no_chatter(self, bot_instance: Bot) -> None:
        """Test handling failure to create partial user."""
        create_partialuser = MagicMock(return_value=None)
        pause_exit = MagicMock()
        bot_instance.create_partialuser = create_partialuser
        bot_instance.pause_exit = pause_exit

        await bot_instance.send_chat_message("Test message")

        pause_exit.assert_called_once()


class TestPrintConsoleMessage:
    """Test print_console_message method."""

    def test_print_console_message_enabled(self, bot_instance: Bot, capsys) -> None:
        """Test printing when console output is enabled."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = True

        bot_instance.print_console_message("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_print_console_message_disabled(self, bot_instance: Bot, capsys) -> None:
        """Test that console output is suppressed when disabled."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = False

        bot_instance.print_console_message("Test message")

        captured = capsys.readouterr()
        assert captured.out == ""


class TestBotClose:
    """Test bot close behavior."""

    @pytest.mark.asyncio
    async def test_close_detaches_in_reverse_order(self, bot_instance: Bot) -> None:
        """Test that close detaches components in reverse order."""
        component_a = DummyComponent(bot_instance)
        component_b = DummyComponent(bot_instance)
        bot_instance.attached_components = [component_a, component_b]
        detach_component = AsyncMock()
        print_console_message = MagicMock()
        bot_instance.detach_component = detach_component
        bot_instance.print_console_message = print_console_message

        with patch("core.bot.commands.Bot.close", new_callable=AsyncMock) as close_mock:
            await bot_instance.close()

        assert detach_component.call_args_list == [call(component_b), call(component_a)]
        assert bot_instance._closed is True
        close_mock.assert_awaited_once()

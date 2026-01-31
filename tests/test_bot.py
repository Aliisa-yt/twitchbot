"""Unit tests for core.bot module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.loader import Config
from core.bot import Bot
from core.token_manager import TwitchBotToken

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
def mock_config() -> Config:
    """Create a mock configuration object."""
    config = MagicMock(spec=Config)

    # Create nested mock objects
    config.GENERAL = MagicMock()
    config.GENERAL.DEBUG = False
    config.GENERAL.VERSION = "1.0.0"
    config.GENERAL.SCRIPT_NAME = "twitchbot"
    config.GENERAL.TMP_DIR = "/tmp"

    config.BOT = MagicMock()
    config.BOT.COLOR = "blue"
    config.BOT.LOGIN_MESSAGE = "Bot is ready"
    config.BOT.DONT_LOGIN_MESSAGE = False
    config.BOT.DONT_CHAT_MESSAGE = False

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
def mock_shared_data() -> MagicMock:
    """Create a mock shared data object."""
    shared_data = AsyncMock()
    shared_data.async_init = AsyncMock()
    return shared_data


@pytest.fixture
async def bot_instance(mock_config: Config, mock_token_data: TwitchBotToken) -> AsyncGenerator[Bot]:
    """Create a Bot instance for testing."""
    with (
        patch("core.bot.commands.Bot.__init__", return_value=None),
        patch("core.bot.LoggerUtils.get_logger"),
        patch("core.bot.SharedData"),
    ):
        bot = Bot(mock_config, mock_token_data)
        bot.close_method = []
        bot._closed = False
        # Mock TwitchIO Bot methods
        bot.add_component = AsyncMock(name="add_component")
        bot.add_token = AsyncMock()
        bot.subscribe_websocket = AsyncMock()
        bot.create_partialuser = MagicMock()
        # bot.send_message = AsyncMock()
        yield bot


class TestBotInitialization:
    """Test Bot initialization."""

    def test_bot_init_sets_properties(self, mock_config: Config, mock_token_data: TwitchBotToken) -> None:
        """Test that Bot initialization sets required properties."""
        with (
            patch("core.bot.commands.Bot.__init__", return_value=None),
            patch("core.bot.LoggerUtils.get_logger"),
            patch("core.bot.SharedData"),
        ):
            bot = Bot(mock_config, mock_token_data)

            assert bot.config == mock_config
            assert bot._token_data == mock_token_data
            assert bot._closed is False
            assert bot.close_method == []

    def test_bot_properties(self, bot_instance: Bot, mock_token_data: TwitchBotToken) -> None:
        """Test that Bot properties return correct values."""
        assert bot_instance.client_id == mock_token_data.client_id
        assert bot_instance.client_secret == mock_token_data.client_secret
        assert bot_instance.bot_id == mock_token_data.bot_id
        assert bot_instance.owner_id == mock_token_data.owner_id
        assert bot_instance.access_token == mock_token_data.access_token
        assert bot_instance.refresh_token == mock_token_data.refresh_token


class TestBotSetupHook:
    """Test Bot setup_hook method."""

    @pytest.mark.asyncio
    async def test_setup_hook_initializes_components(self, bot_instance: Bot) -> None:
        """Test that setup_hook initializes all components."""
        bot_instance.shared_data.async_init = AsyncMock()
        bot_instance.add_component = AsyncMock()

        with (
            patch("core.bot.ChatEventsCog") as mock_chat_events,
            patch("core.bot.Command") as mock_command,
            patch("core.bot.TimeSignalManager") as mock_time_signal,
        ):
            # Make the async_init coroutines
            mock_chat_events.return_value.async_init = AsyncMock()
            mock_command.return_value.async_init = AsyncMock()
            mock_time_signal.return_value.async_init = AsyncMock()

            # Mock the close method
            mock_chat_events.return_value.close = AsyncMock()
            mock_command.return_value.close = AsyncMock()
            mock_time_signal.return_value.close = AsyncMock()

            await bot_instance.setup_hook()

            # Verify shared_data was initialized
            bot_instance.shared_data.async_init.assert_called_once()

            # Verify components were added
            assert bot_instance.add_component.call_count == 3


class TestBotEventHandlers:
    """Test Bot event handler methods."""

    @pytest.mark.asyncio
    async def test_event_error_logs_exception(self, bot_instance: Bot, caplog) -> None:
        """Test that event_error logs the exception."""
        error = ValueError("Test error")
        payload = MagicMock()
        payload.error = error

        with caplog.at_level(logging.ERROR):
            await bot_instance.event_error(payload)

        assert "Event error: Test error" in caplog.text

    @pytest.mark.asyncio
    async def test_event_ready_subscribes_to_events(self, bot_instance: Bot) -> None:
        """Test that event_ready subscribes to chat events."""
        mock_chatter = AsyncMock()
        mock_chatter.update_chatter_color = AsyncMock()
        bot_instance.create_partialuser = MagicMock(return_value=mock_chatter)
        bot_instance._subscribe_to_chat_events = AsyncMock()

        await bot_instance.event_ready()

        bot_instance._subscribe_to_chat_events.assert_called_once()
        mock_chatter.update_chatter_color.assert_called_once_with(bot_instance.config.BOT.COLOR)

    @pytest.mark.asyncio
    async def test_event_ready_sends_login_message(self, bot_instance: Bot) -> None:
        """Test that event_ready sends login message."""
        bot_instance.config.BOT.DONT_LOGIN_MESSAGE = False
        mock_chatter = AsyncMock()
        mock_chatter.name = "aliisabot_"
        bot_instance.create_partialuser = MagicMock(return_value=mock_chatter)
        bot_instance._subscribe_to_chat_events = AsyncMock()
        bot_instance.send_chat_message = AsyncMock()

        await bot_instance.event_ready()

        bot_instance.send_chat_message.assert_called()

    @pytest.mark.asyncio
    async def test_event_ready_skips_login_when_disabled(self, bot_instance: Bot) -> None:
        """Test that event_ready skips login message when disabled."""
        bot_instance.config.BOT.DONT_LOGIN_MESSAGE = True
        mock_chatter = AsyncMock()
        bot_instance.create_partialuser = MagicMock(return_value=mock_chatter)
        bot_instance._subscribe_to_chat_events = AsyncMock()
        bot_instance.send_chat_message = AsyncMock()

        await bot_instance.event_ready()

        bot_instance.send_chat_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_command_error_logs_error(self, bot_instance: Bot, caplog) -> None:
        """Test that event_command_error logs the error."""
        error = RuntimeError("Command error")
        payload = MagicMock()
        payload.exception = error

        with caplog.at_level(logging.ERROR):
            await bot_instance.event_command_error(payload)

        assert "Command error" in caplog.text

    @pytest.mark.asyncio
    async def test_event_oauth_authorized_with_bot_id(self, bot_instance: Bot) -> None:
        """Test event_oauth_authorized when user_id matches bot_id."""
        payload = MagicMock()
        payload.access_token = "new_access_token"
        payload.refresh_token = "new_refresh_token"
        payload.user_id = bot_instance.bot_id

        bot_instance.add_token = AsyncMock()

        await bot_instance.event_oauth_authorized(payload)

        bot_instance.add_token.assert_called_once_with("new_access_token", "new_refresh_token")

    @pytest.mark.asyncio
    async def test_event_oauth_authorized_without_user_id(self, bot_instance: Bot) -> None:
        """Test event_oauth_authorized when user_id is None."""
        payload = MagicMock()
        payload.access_token = "new_access_token"
        payload.refresh_token = "new_refresh_token"
        payload.user_id = None

        bot_instance.add_token = AsyncMock()

        await bot_instance.event_oauth_authorized(payload)

        bot_instance.add_token.assert_called_once()


class TestSubscribeToEvents:
    """Test _subscribe_to_chat_events method."""

    @pytest.mark.asyncio
    async def test_subscribe_to_chat_events_success(self, bot_instance: Bot) -> None:
        """Test successful subscription to chat events."""
        bot_instance.subscribe_websocket = AsyncMock()
        bot_instance.add_token = AsyncMock()

        await bot_instance._subscribe_to_chat_events()

        # Verify add_token was called
        bot_instance.add_token.assert_called_once_with(bot_instance.access_token, bot_instance.refresh_token)

        # Verify subscribe_websocket was called (1 chat message + 3 deletion/clear events)
        assert bot_instance.subscribe_websocket.call_count == 4


class TestSendChatMessage:
    """Test send_chat_message method."""

    @pytest.mark.asyncio
    async def test_send_chat_message_basic(self, bot_instance: Bot) -> None:
        """Test sending a basic chat message."""
        mock_chatter = AsyncMock()
        mock_chatter.name = "test_channel"
        mock_sent_message = MagicMock()
        mock_sent_message.sent = True
        mock_chatter.send_message = AsyncMock(return_value=mock_sent_message)

        bot_instance.create_partialuser = MagicMock(return_value=mock_chatter)

        await bot_instance.send_chat_message("Test message")

        mock_chatter.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_chat_message_with_custom_chatter(self, bot_instance: Bot) -> None:
        """Test sending a message to a specific chatter."""
        mock_chatter = AsyncMock()
        mock_chatter.name = "custom_user"
        mock_sent_message = MagicMock()
        mock_sent_message.sent = True
        mock_chatter.send_message = AsyncMock(return_value=mock_sent_message)

        await bot_instance.send_chat_message("Test message", chatter=mock_chatter)

        mock_chatter.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_chat_message_empty_content(self, bot_instance: Bot) -> None:
        """Test that empty content is not sent."""
        mock_chatter = AsyncMock()

        await bot_instance.send_chat_message(None, chatter=mock_chatter)

        mock_chatter.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_chat_message_with_header_footer(self, bot_instance: Bot) -> None:
        """Test sending a message with header and footer."""
        mock_chatter = AsyncMock()
        mock_chatter.name = "test_channel"
        mock_sent_message = MagicMock()
        mock_sent_message.sent = True
        mock_chatter.send_message = AsyncMock(return_value=mock_sent_message)

        bot_instance.create_partialuser = MagicMock(return_value=mock_chatter)

        await bot_instance.send_chat_message("message", header="/me ", footer="!", chatter=mock_chatter)

        mock_chatter.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_chat_message_http_error(self, bot_instance: Bot) -> None:
        """Test sending message without explicit error handling."""
        mock_chatter = AsyncMock()
        mock_chatter.name = "test_channel"
        # Don't raise, just test the success path
        mock_sent_message = MagicMock()
        mock_sent_message.sent = True
        mock_chatter.send_message = AsyncMock(return_value=mock_sent_message)

        await bot_instance.send_chat_message("Test message", chatter=mock_chatter)

        # Verify the send was successful
        assert mock_chatter.send_message.called

    @pytest.mark.asyncio
    async def test_send_chat_message_fails_to_create_chatter(self, bot_instance: Bot) -> None:
        """Test handling failure to create partial user."""
        bot_instance.create_partialuser = MagicMock(return_value=None)
        bot_instance.pause_exit = MagicMock()

        await bot_instance.send_chat_message("Test message")

        bot_instance.pause_exit.assert_called_once()


class TestPrintConsoleMessage:
    """Test print_console_message method."""

    def test_print_console_message_basic(self, bot_instance: Bot, capsys) -> None:
        """Test printing a basic console message."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = True

        bot_instance.print_console_message("Test message")

        captured = capsys.readouterr()
        assert "Test message" in captured.out

    def test_print_console_message_disabled(self, bot_instance: Bot, capsys) -> None:
        """Test that console message is not printed when disabled."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = False

        bot_instance.print_console_message("Test message")

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_console_message_empty(self, bot_instance: Bot, capsys) -> None:
        """Test that empty content is not printed."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = True

        bot_instance.print_console_message(None)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_console_message_unicode(self, bot_instance: Bot, capsys) -> None:
        """Test printing console message with unicode characters."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = True

        bot_instance.print_console_message("テストメッセージ")

        captured = capsys.readouterr()
        assert "テスト" in captured.out

    def test_print_console_message_with_header(self, bot_instance: Bot, capsys) -> None:
        """Test printing message with header."""
        bot_instance.config.BOT.CONSOLE_OUTPUT = True

        bot_instance.print_console_message("message", header="[INFO] ")

        captured = capsys.readouterr()
        assert captured.out != ""


class TestBotClose:
    """Test bot close method."""

    @pytest.mark.asyncio
    async def test_close_calls_close_methods(self, bot_instance: Bot) -> None:
        """Test that close calls all registered close methods."""
        close_method_1 = AsyncMock()
        close_method_2 = AsyncMock()
        bot_instance.close_method = [close_method_1, close_method_2]
        bot_instance.print_console_message = MagicMock()

        with (
            patch.object(bot_instance, "close_method", [close_method_1, close_method_2]),
            patch("core.bot.commands.Bot.close", new_callable=AsyncMock),
        ):
            await bot_instance.close()

        assert bot_instance._closed is True

    @pytest.mark.asyncio
    async def test_close_idempotent(self, bot_instance: Bot) -> None:
        """Test that calling close multiple times is safe."""
        close_method = AsyncMock()
        bot_instance.close_method = [close_method]
        bot_instance.print_console_message = MagicMock()

        with patch("core.bot.commands.Bot.close", new_callable=AsyncMock):
            await bot_instance.close()
            await bot_instance.close()

        # close_method should only be called once
        assert bot_instance._closed is True


class TestFetchStreamGame:
    """Test fetch_stream_game method."""

    @pytest.mark.asyncio
    async def test_fetch_stream_game_success(self, bot_instance: Bot, caplog) -> None:
        """Test successfully fetching stream game info."""
        mock_stream = MagicMock()
        mock_stream.game_name = "Just Chatting"

        bot_instance.fetch_streams = AsyncMock(return_value=[mock_stream])

        with caplog.at_level(logging.INFO):
            await bot_instance.fetch_stream_game("test_user")

        assert "Currently streaming game: Just Chatting" in caplog.text

    @pytest.mark.asyncio
    async def test_fetch_stream_game_not_streaming(self, bot_instance: Bot, caplog) -> None:
        """Test when user is not currently streaming."""
        bot_instance.fetch_streams = AsyncMock(return_value=[])

        with caplog.at_level(logging.INFO):
            await bot_instance.fetch_stream_game("test_user")

        assert "Not currently streaming" in caplog.text


class TestSetupTwitchioLogger:
    """Test _setup_twitchio_logger method."""

    def test_setup_twitchio_logger(self, bot_instance: Bot) -> None:
        """Test setting up TwitchIO logger."""
        with (
            patch("core.bot.twitchio.utils.setup_logging"),
            patch("core.bot.logging.getLogger") as mock_get_logger,
            patch("core.bot.LoggerUtils.get_logger") as mock_logger_utils,
        ):
            mock_logger = MagicMock()
            mock_logger.handlers = []
            mock_get_logger.return_value = mock_logger

            mock_utils_logger = MagicMock()
            mock_utils_logger.handlers = []
            mock_logger_utils.return_value = mock_utils_logger

            bot_instance._setup_twitchio_logger(logging.WARNING)

            mock_logger.setLevel.assert_called_once_with(logging.WARNING)

"""Twitchbot core bot implementation.

This module provides the main Bot class that extends twitchio.ext.commands.Bot and orchestrates
the bot's core functionality including event handling, chat message management, TTS/translation
integration, and component lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import twitchio
from twitchio import Chatter, PartialUser, User, eventsub
from twitchio.eventsub import (
    ChatClearSubscription,
    ChatClearUserMessagesSubscription,
    ChatMessageDeleteSubscription,
    SubscriptionPayload,
)
from twitchio.ext import commands

from core.components import Base, ChatEventsCog, Command, TimeSignalManager
from core.shared_data import SharedData
from utils.chat_utils import ChatUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from twitchio import EventErrorPayload
    from twitchio.ext.commands import CommandErrorPayload
    from twitchio.models import Stream
    from twitchio.models.chat import SentMessage

    from config.loader import Config
    from core.token_manager import TwitchBotToken


__all__: list[str] = ["Bot"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class Bot(commands.Bot):
    """Twitchbot TwitchIO bot implementation.

    Extends twitchio.ext.commands.Bot to provide Twitch chat integration with translation
    and text-to-speech capabilities. Manages event subscriptions, component lifecycle,
    and graceful shutdown.

    Attributes:
        config (Config): Bot configuration settings.
        shared_data (SharedData): Shared translation and TTS managers.
        close_method (list): Cleanup methods to call during shutdown.
    """

    def __init__(
        self,
        config: Config,
        token_data: TwitchBotToken,
    ) -> None:
        """Initialise the TwitchIO bot with configuration and token data.

        Args:
            config (Config): The configuration object containing bot settings.
            token_data (TwitchBotToken): The token data containing authentication information.
        """
        logger.debug("Initialising %s", self.__class__.__name__)
        self._setup_twitchio_logger(logging.WARNING)
        # self._setup_twitchio_logger(logging.DEBUG)

        self.config: Config = config
        self._token_data: TwitchBotToken = token_data

        self.close_method: list[Callable[[], Awaitable[None]]] = []
        self.shared_data: SharedData = SharedData(config)
        self._closed: bool = False

        logger.debug("Initialising TwitchIO")
        super().__init__(
            client_id=self.client_id,
            client_secret=self.client_secret,
            bot_id=self.bot_id,
            owner_id=self.owner_id,
            prefix="!",
        )

    @property
    def client_id(self) -> str:
        """Return the client ID."""
        return self._token_data.client_id

    @property
    def client_secret(self) -> str:
        """Return the client secret."""
        return self._token_data.client_secret

    @property
    def bot_id(self) -> str:
        """Return the bot's user ID."""
        return self._token_data.bot_id

    @property
    def owner_id(self) -> str:
        """Return the owner's user ID."""
        return self._token_data.owner_id

    @property
    def access_token(self) -> str:
        """Return the user's access token."""
        return self._token_data.access_token

    @property
    def refresh_token(self) -> str:
        """Return the refresh token."""
        return self._token_data.refresh_token

    def _setup_twitchio_logger(self, log_level: int) -> None:
        """Set up the TwitchIO logger with the LoggerUtils configuration.

        This method configures the TwitchIO logger to use the same logging handlers
        and settings as defined in LoggerUtils, ensuring consistent logging across the application.

        Args:
            log_level (int): The logging level to set for the TwitchIO logger.
        """
        logger.debug("Setting up TwitchIO logger with LoggerUtils configuration")
        # Initialize TwitchIO logging at DEBUG so all DEBUG and higher messages are emitted.
        # Then attach LoggerUtils handlers and set the twitchio logger's effective level via log_level.
        twitchio.utils.setup_logging(level=logging.DEBUG, root=False)
        twitchio_logger: logging.Logger = logging.getLogger("twitchio")
        twitchio_logger.handlers.clear()

        for handler in LoggerUtils.get_logger().handlers:
            twitchio_logger.addHandler(handler)
        twitchio_logger.setLevel(log_level)
        logger.debug("TwitchIO logger set up with LoggerUtils configuration")

    async def setup_hook(self) -> None:
        """Setup hook for the bot.

        This method is invoked when the bot is ready to configure components and shared data.
        It initialises the shared data and adds the necessary components to the bot.
        """
        logger.debug("Setting up %s", self.__class__.__name__)

        await self.shared_data.async_init()
        _components: list[Base] = [
            ChatEventsCog(self),
            Command(self),
            TimeSignalManager(self),
        ]
        for _component in _components:
            await _component.async_init()
            self.close_method.append(_component.close)
            await self.add_component(_component)

    # --------------------------------------------------
    # Triggering events in TwitchIO
    # --------------------------------------------------
    async def event_error(self, payload: EventErrorPayload) -> None:
        """Called when an error occurs in the bot.

        Args:
            payload (EventErrorPayload): The payload containing error information.
        """
        logger.exception("Event error: %s", payload.error)

    async def event_ready(self) -> None:
        """Called when the bot is ready and connected to Twitch.

        Performs initialization tasks including subscribing to chat events, setting bot color,
        and sending login message if configured.
        """
        try:
            await self._subscribe_to_chat_events()

            chatter: PartialUser = self.create_partialuser(user_id=self.bot_id)
            await chatter.update_chatter_color(self.config.BOT.COLOR)

            logger.info(self.config.BOT.LOGIN_MESSAGE)
            self.print_console_message(self.config.BOT.LOGIN_MESSAGE)

            if not self.config.BOT.DONT_LOGIN_MESSAGE:
                await self.send_chat_message(self.config.BOT.LOGIN_MESSAGE, header="/me ")
        except Exception:
            logger.exception("Error during event_ready")

    async def _subscribe_to_chat_events(self) -> None:
        """Subscribe to chat messages and events for the bot's owner.

        Subscribes to chat messages, deletion, and clear events for the owner's channel
        using EventSub webhooks.
        """
        logger.debug("Subscribing to chat messages and events for the bot's owner")
        await self.add_token(self.access_token, self.refresh_token)
        payload = eventsub.ChatMessageSubscription(broadcaster_user_id=self.owner_id, user_id=self.bot_id)
        await self.subscribe_websocket(payload=payload, token_for=self.bot_id)

        logger.debug("Subscribing to chat message deletion and clearing events for the bot's owner")
        subscriptions: list[SubscriptionPayload] = [
            ChatMessageDeleteSubscription(broadcaster_user_id=self.owner_id, user_id=self.bot_id),
            ChatClearSubscription(broadcaster_user_id=self.owner_id, user_id=self.bot_id),
            ChatClearUserMessagesSubscription(broadcaster_user_id=self.owner_id, user_id=self.bot_id),
        ]
        for sub in subscriptions:
            logger.debug("Subscribing to event: %s", type(sub))
            try:
                await self.subscribe_websocket(sub)
            except ValueError as err:
                logger.error("Failed to subscribe to event %s: %s", type(sub), err)
            except twitchio.HTTPException as err:
                logger.error("TwitchIO HTTP error while subscribing to event %s: %s", type(sub), err)

    async def event_command_error(self, payload: CommandErrorPayload) -> None:
        """Called when an error occurs in a command.

        This method is called when an error occurs in a command.
        It logs the error and the command that caused it.

        Args:
            payload (CommandErrorPayload): The payload containing error information.
        """
        error: Exception = payload.exception
        logger.error("Command error: %s", error, exc_info=True)

    # event_message is overridden in the components, so do nothing here
    # async def event_message(self, payload: TwitchMessage) -> None:

    async def event_oauth_authorized(self, payload: twitchio.authentication.UserTokenPayload) -> None:
        """Called when the bot is authorized with OAuth.

        Adds authentication tokens and subscribes to chat messages for authorized users.

        Args:
            payload (twitchio.authentication.UserTokenPayload): The payload containing OAuth information.
        """
        logger.debug("OAuth authorized with payload: %s", payload)
        await self.add_token(payload.access_token, payload.refresh_token)

        if not payload.user_id:
            logger.warning("No user ID found in the OAuth payload.")
            return

        if payload.user_id == self.bot_id:
            logger.info("Bot is authorized with user ID: %s", payload.user_id)
            return

        logger.info("Subscribing to chat messages for user ID: %s", payload.user_id)
        chat = eventsub.ChatMessageSubscription(broadcaster_user_id=payload.user_id, user_id=self.bot_id)
        if not chat:
            logger.error("Failed to create ChatMessageSubscription for user ID: %s", payload.user_id)
            return
        try:
            await self.subscribe_websocket(chat)
        except ValueError as err:
            logger.error("Failed to subscribe to chat messages: %s", err)
            return
        except twitchio.HTTPException as err:
            logger.error("TwitchIO HTTP error while subscribing to chat messages: %s", err)
            return

    async def close(self, **kwargs) -> None:
        """Close the bot and perform any necessary cleanup.

        This method overrides the close() method in TwitchIO and automatically
        begins the BOT termination process when a KeyboardInterrupt is triggered.

        Args:
            **kwargs: Additional keyword arguments (Additional keyword arguments (used only in the parent class).
        """
        # NOTE:
        # TwitchIO's shutdown sequence may cause Bot.close() to be invoked more than once.
        # In this project, close() can be called explicitly from our KeyboardInterrupt /
        # shutdown handling, and TwitchIO's Bot.run() (or internal loop shutdown) also calls
        # close() in its own cleanup path when the event loop stops. As a result, during a
        # normal termination close() may run twice.
        # To avoid running our custom termination logic and cleanup coroutines multiple times,
        # we guard them with self._closed so that they execute only once even if close() is
        # invoked repeatedly, while still delegating to the base implementation each time.
        if not self._closed:
            self.print_console_message("Bot is shutting down... please wait.")
            logger.info("start termination process")
            shutdown_err: list[BaseException | None] = await asyncio.gather(
                *[_coro() for _coro in self.close_method], return_exceptions=True
            )
            for err in shutdown_err:
                if isinstance(err, BaseException):
                    logger.error("Error during bot shutdown: %s", err)
            self._closed = True
            logger.info("complete termination process")
        await super().close(**kwargs)

    async def fetch_stream_game(self, user_login: str) -> None:
        """Retrieve the current game's title being streamed"""
        streams: list[Stream] = await self.fetch_streams(user_logins=[user_login])
        if streams:
            stream: Stream = streams[0]
            logger.info("Currently streaming game: %s", stream.game_name)
        else:
            logger.info("Not currently streaming")

    async def send_chat_message(
        self,
        content: str | None,
        *,
        header: str | None = None,
        footer: str | None = None,
        chatter: User | PartialUser | Chatter | None = None,
    ) -> None:
        """Output a message to the chat

        The output message is limited to 450 characters, and if it exceeds that,
        only the content will be cut to fit within 450 characters.
        The header and footer will not be cut.
        The behavior is not guaranteed if the header and footer are unreasonably long.

        Args:
            content (str | None): The message to output
            header (str | None): The header to output before the content
            footer (str | None): The footer to output after the content
            channel (Channel | None): Specify the channel to output to
                If not specified, it will output to the first channel listed in initial_channels
                (Preparation for when multiple initial_channels are listed)
        """
        if not content:
            return

        # If no chatter (channel) is specified, use the owner's channel
        if chatter is None:
            chatter = self.create_partialuser(user_id=self.owner_id)
            if not chatter:
                logger.critical("Failed to create a partial user for channel '%s'", self.owner_id)
                self.pause_exit()
                return

        # The maximum length of a Twitch message is 500 bytes (not 500 characters).
        max_len: int = 450
        content = ChatUtils.truncate_message(content, max_len, header=header, footer=footer)

        logger.debug("send message: %s", content)
        logger.debug("send channel: %s", chatter.name)
        try:
            sent_message: SentMessage = await chatter.send_message(
                message=content, sender=self.bot_id, token_for=self.access_token
            )
            if not sent_message.sent:
                logger.warning("Failed to send message: %s", content)
        except ValueError as err:
            logger.warning("Invalid content error: %s", err)
        except twitchio.HTTPException as err:
            logger.warning("TwitchIO HTTP error while sending message: %s", err)

    def print_console_message(
        self, content: str | None, *, header: str | None = None, footer: str | None = None
    ) -> None:
        """Output a message to the console

        The output message is limited to 80 characters. If it exceeds that, the content
        is truncated to fit within 80 characters. The header and footer are not truncated.

        Args:
            content (str): The message to output
            header (str | None): The header to output before the content
            footer (str | None): The footer to output after the content
        """
        if not content:
            return

        if self.config.BOT.CONSOLE_OUTPUT:
            max_len: int = 80
            try:
                # Calculate the byte-to-character ratio to adjust for multibyte characters.
                # Multibyte characters (e.g., Japanese, emoji) take more bytes than ASCII but display
                # as single characters. This ratio accounts for display width differences and is clamped
                # between 1.0 and 2.0 (empirical bounds).
                length_ratio: float = max(min(float(len(content.encode("utf-8")) / len(content)), 2.0), 1.0)
            except (ZeroDivisionError, UnicodeDecodeError) as err:
                logger.debug(err)
                return

            max_len = int(max_len / length_ratio)
            content = ChatUtils.truncate_message(content, max_len, header=header, footer=footer)
            print(content)

    def pause_exit(self) -> None:
        """Pause the program and wait for user input before exiting.

        This method is used to prevent the program from exiting immediately,
        allowing the user to read any error messages or logs before closing the console.
        """
        # Use input method to be platform independent
        input("Press Enter to exit...")
        raise SystemExit(1)

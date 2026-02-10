"""Twitchbot core bot implementation.

This module provides the main Bot class that extends twitchio.ext.commands.Bot and orchestrates
the bot's core functionality including event handling, chat message management, TTS/translation
integration, and component lifecycle management.
"""

from __future__ import annotations

import logging
from contextlib import suppress
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
from twitchio.ext.commands import ComponentLoadError

from core.components import (
    BotCommandManager,  # noqa: F401
    ChatEventsManager,  # noqa: F401
    ComponentBase,
    TranslationServiceComponent,  # noqa: F401
    TTSServiceComponent,  # noqa: F401
)
from core.components.removable import TimeSignalManager  # noqa: F401
from core.shared_data import SharedData
from utils.chat_utils import ChatUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
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
        attached_components (list[ComponentBase]): List of attached bot components.
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

        self.shared_data: SharedData = SharedData(config)
        self._closed: bool = False

        self.attached_components: list[ComponentBase] = []

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
        """Asynchronous setup hook called during bot initialization.

        This method initializes shared data and attaches registered components.
        """
        logger.debug("Setting up %s", self.__class__.__name__)

        await self.shared_data.async_init()

        for _priority, _component_class, _is_removable in ComponentBase.component_priority_list:
            _component: ComponentBase = _component_class(self)
            await self.attach_component(_component)

    async def attach_component(self, component: ComponentBase) -> None:
        """Attach a component to the bot.

        Args:
            component (Base): The component to attach.
        """
        logger.debug("Attaching component: %s", component.__class__.__name__)
        try:
            await self.add_component(component)
        except ComponentLoadError as err:
            logger.error("Failed to load component %s: %s", component.__class__.__name__, err)
            return

        self.attached_components.append(component)
        logger.debug("Successfully attached component: %s", component.__class__.__name__)

    async def detach_component(self, component: ComponentBase) -> None:
        """Detach a component from the bot.

        Args:
            component (Base): The component to detach.
        """
        logger.debug("Detaching component: %s", component.__class__.__name__)
        try:
            await self.remove_component(component.__class__.__name__)
        except ValueError as err:
            logger.error("Failed to detach component %s: %s", component.__class__.__name__, err)
        except Exception as err:  # noqa: BLE001
            logger.error("Unexpected error while detaching component %s: %s", component.__class__.__name__, err)
        else:
            logger.debug("Successfully detached component: %s", component.__class__.__name__)
        finally:
            with suppress(ValueError):
                self.attached_components.remove(component)

    # --------------------------------------------------
    # Triggering events in TwitchIO
    # --------------------------------------------------
    async def event_error(self, payload: EventErrorPayload) -> None:
        """Called when an error occurs in the bot.

        Args:
            payload (EventErrorPayload): The payload containing error information.
        """
        logger.error("Event error: %s", payload.error)

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
        except Exception:  # noqa: BLE001
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

        Args:
            payload (CommandErrorPayload): The payload containing error information.
        """
        error: Exception = payload.exception
        logger.error("Command error: %s", error)

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

        Args:
            **kwargs: Additional keyword arguments passed to parent class.

        Note:
            TwitchIO's shutdown sequence may invoke close() multiple times. We guard cleanup
            logic with self._closed to ensure it executes only once, while still delegating
            to the base implementation each time.
        """
        if not self._closed:
            self.print_console_message("Bot is shutting down... please wait.")
            logger.info("Start shutdown sequence")
            for _component in reversed(self.attached_components):
                await self.detach_component(_component)

            self._closed = True
            logger.info("Shutdown sequence complete")
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
        """Send a message to Twitch chat.

        The output message is limited to 450 characters. If exceeded, only the content
        is truncated to fit. The header and footer are not truncated.

        Args:
            content (str | None): The message to send.
            header (str | None): Optional header prefix (e.g., '/me ').
            footer (str | None): Optional footer suffix.
            chatter (User | PartialUser | Chatter | None): Target channel. If None, uses owner's channel.
        """
        if not content:
            return

        if chatter is None:
            chatter = self.create_partialuser(user_id=self.owner_id)
            if not chatter:
                logger.critical("Failed to create a partial user for channel '%s'", self.owner_id)
                self.pause_exit()
                return

        max_len: int = 450
        content = ChatUtils.truncate_message(content, max_len, header=header, footer=footer)

        logger.debug("Send message: %s", content)
        logger.debug("Send channel: %s", chatter.name)
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
        """Print a message to the console.

        The output message is limited to 80 characters. If exceeded, only the content
        is truncated to fit. The header and footer are not truncated.

        Args:
            content (str | None): The message to print.
            header (str | None): Optional header prefix.
            footer (str | None): Optional footer suffix.
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

        Allows the user to read error messages before the console closes.
        In GUI mode with --noconsole build, stdin is unavailable and EOFError is suppressed.
        """
        with suppress(KeyboardInterrupt, EOFError):
            input("Press Enter to exit...")
        raise KeyboardInterrupt

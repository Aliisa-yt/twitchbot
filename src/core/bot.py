"""Twitchbot core bot implementation.

This module provides the main Bot class that extends twitchio.ext.commands.Bot and orchestrates
the bot's core functionality including event handling, chat message management, TTS/translation
integration, and component lifecycle management.
"""

import logging
from collections import defaultdict, deque
from contextlib import suppress
from typing import TYPE_CHECKING, Any, override

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

from core.components import (  # noqa: F401
    BotCommandManager,
    CacheServiceComponent,
    ChatEventsManager,
    ComponentBase,
    ComponentDescriptor,
    InFlightServiceComponent,
    STTServiceComponent,
    TranslationServiceComponent,
    TTSServiceComponent,
)
from core.components.removable import TimeSignalManager  # noqa: F401
from core.shared_data import SharedData
from utils.chat_utils import ChatUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    from twitchio import EventErrorPayload
    from twitchio.authentication import ValidateTokenPayload
    from twitchio.eventsub.subscriptions import ChatMessageSubscription
    from twitchio.ext.commands import CommandErrorPayload
    from twitchio.models import Stream
    from twitchio.models.chat import SentMessage

    from core.stt.recorder import LevelEventCallback
    from core.stt.stt_manager import STTManager
    from core.token_manager import TokenManager
    from models.config_models import Config


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
        send_message_cache (set[str]): Cache of recently sent message IDs to prevent echo handling.

    Properties:
        client_id (str): Twitch application client ID.
        client_secret (str): Twitch application client secret.
        bot_id (str): Twitch user ID of the bot account.
        owner_id (str): Twitch user ID of the bot owner.
        access_token (str): OAuth access token for Twitch API authentication.
        refresh_token (str): OAuth refresh token for Twitch API authentication.
        last_validated (str): Timestamp of when the token was last validated.
    """

    def __init__(
        self,
        config: Config,
        token_manager: TokenManager,
    ) -> None:
        """Initialise the TwitchIO bot with configuration and token data.

        Args:
            config (Config): The configuration object containing bot settings.
            token_manager (TokenManager): The token manager for handling token operations.

        Note:
            The contents of 'token_data' and 'token_manager.load_tokens()' differ, so they cannot be combined.
        """
        logger.info("Initializing Twitchbot")
        self._setup_twitchio_logger(logging.WARNING)

        self.config: Config = config
        self._token_manager: TokenManager = token_manager

        self.shared_data: SharedData = SharedData(config)
        self._closed: bool = False
        self._pending_stt_level_callback: LevelEventCallback | None = None

        self.attached_components: list[ComponentBase] = []

        self.send_message_cache: set[str] = set()

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
        return self._token_manager.client_id

    @property
    def client_secret(self) -> str:
        """Return the client secret."""
        return self._token_manager.client_secret

    @property
    @override
    def bot_id(self) -> str:
        """Return the bot's user ID."""
        return self._token_manager.bot_id

    @property
    @override
    def owner_id(self) -> str:
        """Return the owner's user ID."""
        return self._token_manager.owner_id

    @property
    def access_token(self) -> str:
        """Return the user's access token."""
        return self._token_manager.user_access_token

    @property
    def refresh_token(self) -> str:
        """Return the refresh token."""
        return self._token_manager.refresh_token

    @property
    def last_validated(self) -> str:
        """Return the timestamp of when the token was last validated."""
        return self._token_manager.last_validated

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

    @override
    async def setup_hook(self) -> None:
        """Asynchronous setup hook called during bot initialization.

        This method initializes shared data and attaches registered components.
        """
        logger.info("SETUP HOOK: Initializing shared data and attaching components")

        await self.shared_data.async_init()
        self.shared_data.stt_manager.set_level_event_callback(self._pending_stt_level_callback)

        self.validate_dependencies(ComponentBase.component_registry)
        attach_order: list[str] = self.resolve_dependencies(ComponentBase.component_registry)
        logger.debug("Component attach order: %s", attach_order)

        for component_name in attach_order:
            await self.attach_component(ComponentBase.component_registry[component_name].component(self))

    def set_stt_level_callback(self, callback: LevelEventCallback | None) -> None:
        """Register callback for STT input level events.

        Args:
            callback: Callback invoked when STT recorder emits input-level events.
        """
        self._pending_stt_level_callback = callback
        stt_manager: STTManager | None = getattr(self.shared_data, "stt_manager", None)
        if stt_manager is not None:
            stt_manager.set_level_event_callback(callback)

    def validate_dependencies(self, deps: dict[str, ComponentDescriptor]) -> None:
        """Validate component dependencies.

        Args:
            deps (dict[str, ComponentDescriptor]): A dictionary mapping component names to their metadata.
        """
        components: set[str] = set(deps.keys())

        for comp, descriptor in deps.items():
            for dep in descriptor.depends:
                if dep not in components:
                    msg: str = f"{comp} depends on unknown component '{dep}'"
                    raise RuntimeError(msg)

    def resolve_dependencies(self, deps: dict[str, ComponentDescriptor]) -> list[str]:
        """Resolve component dependencies using topological sorting.

        Args:
            deps (dict[str, ComponentDescriptor]): A dictionary mapping component names to their metadata.

        Returns:
            list[str]: A list of component names in the order they should be attached.
        """
        graph: defaultdict[str, list[str]] = defaultdict(list)
        indegree: defaultdict[str, int] = defaultdict(int)

        # Build the dependency graph.
        for comp, descriptor in deps.items():
            indegree.setdefault(comp, 0)

            for dep in descriptor.depends:
                graph[dep].append(comp)
                indegree[comp] += 1

        # Start with nodes that have no dependencies.
        queue: deque[str] = deque([n for n in indegree if indegree[n] == 0])
        order: list[str] = []

        while queue:
            node: str = queue.popleft()
            order.append(node)

            for nxt in graph[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        # Detect cycles.
        if len(order) != len(indegree):
            msg: str = "Circular dependency detected"
            raise RuntimeError(msg)

        return order

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
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error while detaching component %s", component.__class__.__name__)
        else:
            logger.debug("Successfully detached component: %s", component.__class__.__name__)
        finally:
            with suppress(ValueError):
                self.attached_components.remove(component)

    @override
    async def event_error(self, payload: EventErrorPayload) -> None:
        """Called when an error occurs in the bot.

        Args:
            payload (EventErrorPayload): The payload containing error information.
        """
        # As the error messages within `payload.error` may contain tokens, the error messages themselves are not logged.
        # Instead, the log records which listener caused the error.
        listener_name: str = getattr(payload.listener, "__name__", str(payload.listener))
        logger.error("Error occurred in listener: %s", listener_name)

    async def event_ready(self) -> None:
        """Called when the bot is ready and connected to Twitch.

        Performs initialization tasks including subscribing to chat events, setting bot color,
        and sending login message if configured.
        """
        logger.info("Bot is ready. Performing post-connection setup.")
        try:
            await self._subscribe_to_chat_events()

            chatter: PartialUser = self.create_partialuser(user_id=self.bot_id)
            await chatter.update_chatter_color(self.config.BOT.COLOR)

            logger.info(self.config.BOT.LOGIN_MESSAGE)
            self.print_console_message(self.config.BOT.LOGIN_MESSAGE)

            if not self.config.BOT.DONT_LOGIN_MESSAGE:
                await self.send_chat_message(self.config.BOT.LOGIN_MESSAGE, header="/me ")
        except twitchio.HTTPException as err:
            logger.error("TwitchIO HTTP error during event_ready: %s", err)

    async def _subscribe_to_chat_events(self) -> None:
        """Subscribe to chat messages and events for the bot's owner.

        Subscribes to chat messages, deletion, and clear events for the owner's channel
        using EventSub webhooks.
        """
        logger.debug("Subscribing to chat messages and events for the bot's owner")
        await self.add_token(self.access_token, self.refresh_token)
        payload: ChatMessageSubscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=self.owner_id, user_id=self.bot_id
        )
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

    @override
    async def event_command_error(self, payload: CommandErrorPayload) -> None:
        """Called when an error occurs in a command.

        Args:
            payload (CommandErrorPayload): The payload containing error information.
        """
        error: Exception = payload.exception
        user_name: str | None = payload.context.author.name
        logger.error("Command error: %s, by user: %s", error, user_name)

    # event_message is overridden in the components, so do nothing here
    # async def event_message(self, payload: TwitchMessage) -> None:

    @override
    async def event_oauth_authorized(self, payload: twitchio.authentication.UserTokenPayload) -> None:
        """Called when the bot is authorized with OAuth.

        Adds authentication tokens and subscribes to chat messages for authorized users.

        Args:
            payload (twitchio.authentication.UserTokenPayload): The payload containing OAuth information.

        Note:
            The Twitchio built-in adapter triggers this event when OAuth authentication is successful.
            As this app does not use the built-in adapter, this event will not occur.
        """
        logger.info("OAuth authorization successful")
        await self.add_token(payload.access_token, payload.refresh_token)

        if not payload.user_id:
            logger.warning("No user ID found in the OAuth payload.")
            return

        if payload.user_id == self.bot_id:
            logger.info("Bot is authorized with user ID: %s", payload.user_id)
            return

        logger.info("Subscribing to chat messages for user ID: %s", payload.user_id)
        chat: ChatMessageSubscription = eventsub.ChatMessageSubscription(
            broadcaster_user_id=payload.user_id, user_id=self.bot_id
        )
        if not chat:
            logger.error("Failed to create ChatMessageSubscription for user ID: %s", payload.user_id)
            return
        try:
            await self.subscribe_websocket(chat)
            logger.info("Successfully subscribed to chat messages for user ID: %s", payload.user_id)
        except ValueError as err:
            logger.error("Failed to subscribe to chat messages: %s", err)
            return
        except twitchio.HTTPException as err:
            logger.error("TwitchIO HTTP error while subscribing to chat messages: %s", err)
            return

    async def event_token_refreshed(self, payload: twitchio.TokenRefreshedPayload) -> None:
        """Called when the bot's OAuth token is refreshed.

        Updates the stored tokens with the new access and refresh tokens.

        Args:
            payload (twitchio.TokenRefreshedPayload): The payload containing new token information.
        """
        logger.info("OAuth token refresh detected, updating stored tokens")
        validation_payload: ValidateTokenPayload = await self.add_token(payload.token, payload.refresh_token)

        # Only update the token database for the bot account.
        # Owner tokens are managed by TwitchIO internally and must not overwrite the bot's stored token.
        if validation_payload.user_id != self.bot_id:
            logger.debug(
                "Skipping token DB update: token belongs to user %s, expected bot %s",
                validation_payload.user_id,
                self.bot_id,
            )
            return

        # After super().add_token(), the token may have been refreshed internally by TwitchIO.
        # Retrieve the latest token from TwitchIO's internal storage to ensure the current value is saved.
        bot_token_data: Any = self.tokens.get(self.bot_id)
        try:
            actual_token: str = bot_token_data["token"] if bot_token_data else payload.token
            actual_refresh: str = bot_token_data["refresh"] if bot_token_data else payload.refresh_token

            _bot_tokens: dict[str, dict[str, Any]] = {}
            _bot_tokens[self.bot_id] = {
                "token": actual_token,
                "refresh": actual_refresh,
                "expires_in": validation_payload.expires_in,
                "last_validated": bot_token_data["last_validated"],
                "scopes": validation_payload.scopes,
            }
        except KeyError as err:
            logger.error("Failed to retrieve token information for bot ID %s: %s", self.bot_id, err)
            return
        else:
            self._token_manager.converted_save_tokens(_bot_tokens)
            logger.debug("Token validated and saved successfully for bot user ID: %s", validation_payload.user_id)
            logger.info("OAuth token refreshed successfully")

    @override
    async def load_tokens(self, path: str | None = None, /) -> None:
        """Load tokens from the token manager.

        Args:
            path (str | None): Optional path to load tokens from. If None, uses default path.

        Raises:
            RuntimeError: If no tokens are found or if the token data structure is invalid.
        """
        _ = path
        logger.debug("Loading tokens from TokenManager")
        token_data: dict[str, dict[str, Any]] = self._token_manager.converted_load_tokens()
        if not token_data:
            msg = "No tokens found in TokenManager"
            logger.error(msg)
            raise RuntimeError(msg)

        bot_token_data: dict[str, Any] | None = token_data.get(self.bot_id)

        if bot_token_data is None:
            msg = f"No token found for bot ID {self.bot_id} in TokenManager"
            logger.error(msg)
            raise RuntimeError(msg)

        try:
            if bot_token_data["user_id"] != self.bot_id:
                msg = f"Loaded token bot_id {bot_token_data['user_id']} does not match expected bot_id {self.bot_id}"
                logger.error(msg)
                raise RuntimeError(msg)

            # Since calling 'add_token()' saves the token information to the 'tokens' dictionary,
            # there is no need to reflect the token information read from the 'TokenManager' in
            # the 'tokens' dictionary.
            await self.add_token(bot_token_data["token"], bot_token_data["refresh"])
        except KeyError as err:
            logger.error("Failed to load tokens for bot ID %s from TokenManager: missing key %s", self.bot_id, err)
            msg = "Invalid token data structure in TokenManager"
            raise RuntimeError(msg) from err
        except RuntimeError:
            raise
        logger.info("Tokens loaded successfully for bot user ID: %s", self.bot_id)

    @override
    async def save_tokens(self, path: str | None = None, /) -> None:
        """Save tokens to the token manager.

        Args:
            path (str | None): Optional path to save tokens to. If None, uses default path.
        """
        # Override the method to skip the save process.
        # This simply lays the groundwork for adding a custom save process in the future.
        _ = path
        logger.debug("Saving tokens to TokenManager")

    @override
    async def close(self, **kwargs: Any) -> None:
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
        sender: str | int | PartialUser | None = None,
    ) -> None:
        """Send a message to Twitch chat.

        The output message is limited to 450 characters. If exceeded, only the content
        is truncated to fit. The header and footer are not truncated.

        Args:
            content (str | None): The message to send.
            header (str | None): Optional header prefix (e.g., '/me ').
            footer (str | None): Optional footer suffix.
            chatter (User | PartialUser | Chatter | None): Target channel. If None, uses owner's channel.
            sender (str | int | PartialUser | None): The sender of the message. If None, uses the bot's ID.
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
        try:
            content = ChatUtils.truncate_message(content, max_len, header=header, footer=footer)
        except ValueError as err:
            logger.warning("Failed to truncate message: %s", err)
            return

        logger.debug("Send message: %s", content)
        logger.debug("Send channel: %s", chatter.name)
        try:
            sent_message: SentMessage = await chatter.send_message(
                message=content, sender=sender or self.bot_id, token_for=self.access_token
            )
            if not sent_message.sent:
                logger.warning("Failed to send message: %s", content)

            self.send_message_cache.add(sent_message.id)
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
            max_len: int = 80  # Console width is 80 ASCII characters.
            try:
                # Calculate the byte-to-character ratio to adjust for multibyte characters.
                # Multibyte characters (e.g., Japanese, emoji) take more bytes than ASCII but display
                # as single characters. This ratio accounts for display width differences and is clamped
                # between 1.0 and 2.0 (empirical bounds).
                _tmp: str = content
                if header:
                    _tmp += header
                if footer:
                    _tmp += footer
                length_ratio: float = max(min(float(len(_tmp.encode("utf-8")) / len(_tmp)), 2.0), 1.0)
            except (ZeroDivisionError, UnicodeDecodeError) as err:
                logger.debug(err)
                return

            try:
                content = ChatUtils.truncate_message(content, int(max_len / length_ratio), header=header, footer=footer)
            except ValueError as err:
                logger.warning("Failed to truncate message for console output: %s", err)
                return
            print(content)

    def pause_exit(self) -> None:
        """Pause the program and wait for user input before exiting.

        Allows the user to read error messages before the console closes.
        In GUI mode with --noconsole build, stdin is unavailable and EOFError is suppressed.
        """
        with suppress(KeyboardInterrupt, EOFError):
            input("Press Enter to exit...")
        raise KeyboardInterrupt

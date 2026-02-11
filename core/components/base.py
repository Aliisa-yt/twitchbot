"""Base component for Twitch chat event handlers.

This module provides the Base class that all bot components inherit from,
offering common functionality for message processing, translation, and TTS operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, NamedTuple

from twitchio.ext.commands import Component

from models.translation_models import TranslationInfo
from models.voice_models import TTSParam
from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config
    from core.bot import Bot
    from core.shared_data import SharedData
    from core.trans.manager import TransManager
    from core.tts.manager import TTSManager
    from handlers.chat_message import ChatMessageHandler


__all__: list[str] = ["ComponentBase"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class ComponentDescriptor(NamedTuple):
    """Descriptor for bot components, including the component class, its dependencies, and removability."""

    component: type[ComponentBase]
    depends: list[str]
    is_removable: bool


class ComponentBase(Component):
    """Base class for Twitch chat event handlers.

    This class provides common functionality for message processing, translation, and TTS operations.
    All bot components should inherit from this base class to ensure consistent access to shared data, configuration,
    and utility methods.

    Attributes:
        bot (Bot): The bot instance with shared data and configuration.
        shared (SharedData): Shared data accessible to all components.
        config (Config): The application configuration.
        trans_manager (TransManager): The translation manager.
        tts_manager (TTSManager): The TTS manager.
        component_registry (ClassVar[dict[str, ComponentDescriptor]]): Registry of all components and their descriptors.
    """

    component_registry: ClassVar[dict[str, ComponentDescriptor]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        """Register subclass in the component registry and dependency mapping.

        Args:
            **kwargs: Additional keyword arguments.
        """
        super().__init_subclass__(**kwargs)
        depends: list[str] = list(getattr(cls, "depends", []))
        is_removable: bool = False
        if "core.components.removable" in cls.__module__:
            is_removable = True

        cls.component_registry[cls.__name__] = ComponentDescriptor(
            component=cls,
            depends=depends,
            is_removable=is_removable,
        )

    def __init__(self, bot: Bot) -> None:
        """Initialize the Base component.

        Args:
            bot (Bot): The bot instance with shared data.

        Raises:
            RuntimeError: If shared data is not initialized.

        Note:
            Due to the implementation of Components, you shouldn't make a call to `super().__init__()`
            if you implement an `__init__` on this component.
            https://twitchio.dev/en/latest/exts/commands/components.html
        """
        self.bot: Bot = bot
        if bot.shared_data is None:
            msg = "Shared data is not initialized."
            raise RuntimeError(msg)
        self.shared: SharedData = bot.shared_data

    @property
    def config(self) -> Config:
        """Get the application configuration."""
        return self.shared.config

    @property
    def trans_manager(self) -> TransManager:
        """Get the translation manager."""
        return self.shared.trans_manager

    @property
    def tts_manager(self) -> TTSManager:
        """Get the TTS manager."""
        return self.shared.tts_manager

    def prepare_original_text(self, message: ChatMessageHandler, tts_param: TTSParam) -> TTSParam:
        """Prepare TTS parameters for original (non-translated) text.

        Removes URLs, compresses whitespace, and formats the message for TTS output.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            tts_param (TTSParam): TTS parameters to be configured.

        Returns:
            TTSParam: Configured TTS parameters ready for synthesis.
        """
        tts_param.content = StringUtils.compress_blanks(StringUtils.remove_url(tts_param.content))

        if message.is_replying:
            tts_param.content = StringUtils.compress_blanks(message.mention.strip_mention_at(tts_param.content, 0))

        tts_param.content = message.formatting_messages(
            content=tts_param.content, language=tts_param.content_lang, is_speak=True
        )
        tts_param.tts_info = self.tts_manager.get_voice_param(tts_param.content_lang)
        return tts_param

    def prepare_translated_text(self, message: ChatMessageHandler, trans_info: TranslationInfo) -> TTSParam:
        """Prepare TTS parameters for translated text.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            trans_info (TranslationInfo): Translation information containing translated text and target language.

        Returns:
            TTSParam: Configured TTS parameters for translated text.
        """
        return TTSParam(
            content=message.formatting_messages(
                content=trans_info.translated_text,
                language=trans_info.tgt_lang,
                is_speak=True,
                is_translated=True,
            ),
            content_lang=trans_info.tgt_lang,
            tts_info=self.tts_manager.get_voice_param(trans_info.tgt_lang),
        )

    async def store_tts_queue(self, tts_param: TTSParam) -> None:
        """Prepare TTS content and enqueue for synthesis.

        Args:
            tts_param (TTSParam): TTS parameters to be synthesized.
        """
        queue_data: TTSParam | None = self.tts_manager.prepare_tts_content(tts_param)
        if queue_data is not None:
            await self.tts_manager.enqueue_tts_synthesis(queue_data)

    def prepare_translate_parameters(self, message: ChatMessageHandler) -> TranslationInfo:
        """Prepare translation parameters from a chat message.

        Removes mentions and emotes from content for translation processing.
        If the message is a reply, inherits the target language from the parent message.

        Args:
            message (ChatMessageHandler): The chat message handler instance.

        Returns:
            TranslationInfo: Translation information with cleaned content and language settings.
        """
        trans_info = TranslationInfo(content=message.content)
        if message.is_replying:
            trans_info.tgt_lang = message.reply_tgt_lang

        trans_info.content = StringUtils.compress_blanks(
            message.mention.strip_mentions(message.emote.remove_all(trans_info.content))
        )
        return trans_info

    def prepare_tts_voice_parameters(self, message: ChatMessageHandler) -> None:
        """Configure TTS voice parameters based on message metadata.

        Selects appropriate voice for user type and optionally applies voice parameter changes.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
        """
        self.tts_manager.select_voice_usertype(message)
        if self.config.TTS.ALLOW_TTS_TWEAK:
            self.tts_manager.command_voiceparameters(message)

    def print_console_message(
        self, message: str | None, *, header: str | None = None, footer: str | None = None
    ) -> None:
        """Print a message to console with optional header and footer.

        Args:
            message (str | None): Message content to print.
            header (str | None): Optional header prefix.
            footer (str | None): Optional footer suffix.
        """
        self.bot.print_console_message(message, header=header, footer=footer)

    async def send_chat_message(
        self, content: str | None, *, header: str | None = None, footer: str | None = None
    ) -> None:
        """Send a message to Twitch chat with optional header and footer.

        Args:
            content (str | None): Message content to send.
            header (str | None): Optional header prefix (e.g., '/me ' for action messages).
            footer (str | None): Optional footer suffix.
        """
        await self.bot.send_chat_message(content, header=header, footer=footer)

"""Handler for chat messages, providing access to message content, author, and formatting utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from handlers.message_formatter import MessageFormatter
from models.message_models import ChatMessage
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from twitchio import ChatMessage as TwitchMessage
    from twitchio import Chatter

    from handlers.fragment_handler import EmoteHandler, MentionHandler
    from models.config_models import Config


__all__: list[str] = ["ChatMessageHandler"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class ChatMessageHandler:
    def __init__(self, twitch_message: TwitchMessage, config: Config) -> None:
        """Initialize ChatMessageHandler with a Twitch message and configuration.

        Args:
            twitch_message (TwitchMessage): The Twitch chat message object.
            config (Config): Configuration settings.
        """
        self._chat_message: ChatMessage = ChatMessage(twitch_message, config)
        self._formatter: MessageFormatter = MessageFormatter(self)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({', '.join(f"{key[1:]}='{value}'" for key, value in self.__dict__.items())})"

    @property
    def content(self) -> str:
        return self._chat_message.content

    @content.setter
    def content(self, value: str) -> None:
        self._chat_message.content = value

    @property
    def author(self) -> Chatter:
        return self._chat_message.author

    @property
    def id(self) -> str:
        return self._chat_message.id

    @property
    def timestamps(self) -> float:
        if self._chat_message.timestamps is None:
            return 0.0
        return self._chat_message.timestamps.timestamp()

    @property
    def display_name(self) -> str:
        return self._chat_message.display_name

    def reply_name(self, *, is_speak: bool = False) -> str:
        name: str = self._chat_message.reply_name

        if not self.is_replying:
            return ""

        if name == "":
            logger.warning("Unknown user name to which you are replying")
            return ""

        if not is_speak:
            # The display characters are prefixed with ‘@’.
            name = "@" + name
        return name

    @property
    def reply_src_lang(self) -> str:
        return self._chat_message.reply_src_lang

    @property
    def reply_tgt_lang(self) -> str:
        return self._chat_message.reply_tgt_lang

    @property
    def is_replying(self) -> bool:
        return self._chat_message.is_replying

    @property
    def emote(self) -> EmoteHandler:
        return self._chat_message.emote

    @property
    def mention(self) -> MentionHandler:
        return self._chat_message.mention

    @property
    def waiting_period(self) -> dict[str, str]:
        return self._chat_message.tts_format.WAITING_PERIOD

    @property
    def waiting_comma(self) -> dict[str, str]:
        return self._chat_message.tts_format.WAITING_COMMA

    @property
    def message_templates(self) -> dict[str, str]:
        return self._chat_message.tts_format.ORIGINAL_MESSAGE

    @property
    def translated_message_templates(self) -> dict[str, str]:
        return self._chat_message.tts_format.TRANSLATED_MESSAGE

    @property
    def reply_message_templates(self) -> dict[str, str]:
        return self._chat_message.tts_format.REPLY_MESSAGE

    def formatting_messages(
        self,
        content: str | None,
        language: str | None,
        *,
        is_speak: bool = False,
        is_translated: bool = False,
    ) -> str:
        """Format the message for output based on TTS and template settings.

        Delegates all formatting logic to MessageFormatter to keep concerns separated.

        Args:
            content (str | None): The message content to format.
            language (str | None): The language code for formatting.
            is_speak (bool, optional): Whether the message is to be spoken. Defaults to False.
            is_translated (bool, optional): Whether the message is translated. Defaults to False.

        Returns:
            str: The formatted message.
        """
        return self._formatter.format_message(content, language, is_speak=is_speak, is_translated=is_translated)

"""Utility functions for chat message processing, including footer generation,
restricted word handling, user ignoring, and message truncation.

This module provides the ChatUtils class with static methods to assist in processing
chat messages. It includes functionality to generate message footers based on configuration,
handle restricted words, determine if messages from certain users should be ignored,
and truncate messages to fit within specified length limits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from handlers.chat_message import ChatMessageHandler
    from models.config_models import Config
    from models.translation_models import TranslationInfo

__all__: list[str] = ["ChatUtils"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)
# logger.addHandler(logging.NullHandler())

SHORTEST_MESSAGE_LENGTH: Final[int] = 20


class ChatUtils:
    """Chat message processing utilities for Twitch bot functionality.

    Provides utility methods for formatting chat messages, filtering restricted content,
    ignoring specific users, and truncating messages to fit within length constraints.
    """

    @staticmethod
    def generate_footer(config: Config, message: ChatMessageHandler, trans_info: TranslationInfo) -> str:
        """Generate a footer string for a chat message with optional author and language info.

        Args:
            config (Config): The configuration object containing footer display options.
            message (ChatMessageHandler): The chat message containing author information.
            trans_info (TranslationInfo): Translation information containing source and target languages.

        Returns:
            str: A formatted footer string based on configuration settings.
        """

        def _get_display_name() -> str:
            """Get the display name of the message author based on configuration.

            If SHOW_EXTENDEDFORMAT is enabled, format as "DisplayName (UserName)".
            Otherwise, return the "UserName".

            Returns:
                str: The display name formatted according to configuration.
            """
            if config.BOT.SHOW_EXTENDEDFORMAT:
                dsp_name: str = message.display_name
                if dsp_name:
                    if dsp_name.lower() == message.author.name:
                        return dsp_name
                    return f"{dsp_name} ({message.author.name})"
            return str(message.author.name)

        footer: str = ""
        if config.BOT.SHOW_BYNAME:
            footer += f" [by {_get_display_name()}]"
        if config.BOT.SHOW_BYLANG:
            footer += f" ({trans_info.src_lang} > {trans_info.tgt_lang})"
        return footer

    @staticmethod
    def is_ignore_users(config: Config, author_name: str | None) -> bool:
        """Determine if a message should be ignored based on the author.

        Checks if the author is in the configured ignore list. Primarily used to ignore
        messages from chat management bots.

        Args:
            config (Config): The configuration object containing the ignore users list.
            author_name (str | None): The name of the message author.

        Returns:
            bool: True if the author should be ignored, False otherwise.
        """
        if author_name in config.BOT.IGNORE_USERS:
            logger.debug("Ignoring user: %s", author_name)
            return True
        return False

    @staticmethod
    def truncate_message(
        content: str | None, limit_length: int, *, header: str | None = None, footer: str | None = None
    ) -> str:
        """Truncate a message to fit within a specified byte length limit.

        Combines content with optional header and footer, truncating the content if needed
        to stay within the byte limit. If truncation is impossible even with minimum length,
        logs a warning and uses the minimum length.

        Args:
            content (str | None): The message content to potentially truncate.
            limit_length (int): The maximum allowed byte length for the combined message.
            header (str | None): Optional prefix to prepend to the message. Defaults to None.
            footer (str | None): Optional suffix to append to the message. Defaults to None.

        Returns:
            str: The formatted and potentially truncated message.
        """
        _content: str = StringUtils.ensure_str(content)
        _header: str = StringUtils.ensure_str(header)
        _footer: str = StringUtils.ensure_str(footer)
        _ellipsis: str = " ..."

        message_length: int = len(_content) + len(_header) + len(_footer)

        if message_length > limit_length:
            limit: int = len(_content) - len(_header) - len(_footer) - len(_ellipsis)
            if limit < SHORTEST_MESSAGE_LENGTH:
                logger.warning(
                    "The message cannot be truncated to the specified length. "
                    "Either increase the length limit or shorten the header/footer."
                )
                limit = SHORTEST_MESSAGE_LENGTH

            _content = f"{_header}{_content[:limit]}{_ellipsis}{_footer}"
        else:
            _content = f"{_header}{_content}{_footer}"

        return _content

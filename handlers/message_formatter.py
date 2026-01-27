"""Message formatter for generating formatted output with variable substitution.

This module provides the MessageFormatter class, which handles the generation of
formatted messages with proper variable substitution based on message type, language,
and translation status. It centralizes all logic related to constructing format variables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from handlers.chat_message import ChatMessageHandler


__all__: list[str] = ["MessageFormatter"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


@dataclass
class FormatVariables:
    """Container for all variables used in message template formatting.

    Attributes:
        user_name (str): The name of the message author.
        reply_name (str): The name of the user being replied to (if applicable).
        mention (str): Space-separated string of mentioned users.
        message (str): The main message content.
        emote (str): Space-separated string of emotes.
        period (str): Period character for language-specific formatting.
        comma (str): Comma character for language-specific formatting.
    """

    user_name: str = ""
    reply_name: str = ""
    mention: str = ""
    message: str = ""
    emote: str = ""
    period: str = ""
    comma: str = ""

    def to_dict(self) -> dict[str, str]:
        """Convert to a dictionary for use with str.format().

        Returns:
            dict[str, str]: Dictionary of all format variables.
        """
        return {
            "user_name": self.user_name,
            "reply_name": self.reply_name,
            "mention": self.mention,
            "message": self.message,
            "emote": self.emote,
            "period": self.period,
            "comma": self.comma,
        }


class MessageFormatter:
    """Handles formatting of chat messages with template-based variable substitution.

    This class encapsulates all logic for preparing format variables based on
    message context (reply status, speech vs text, translation status) and applying
    templates to generate the final formatted output.
    """

    def __init__(self, message_handler: ChatMessageHandler) -> None:
        """Initialize the MessageFormatter with a message handler.

        Args:
            message_handler (ChatMessageHandler): The message handler providing access to
                message data and handlers (emote, mention, etc.).
        """
        self._message_handler: ChatMessageHandler = message_handler
        logger.debug("Initialized MessageFormatter")

    def format_message(
        self,
        content: str | None,
        language: str | None,
        *,
        is_speak: bool = False,
        is_translated: bool = False,
    ) -> str:
        """Format a message using template-based variable substitution.

        Args:
            content (str | None): The message content to format.
            language (str | None): The language code for template selection and variable generation.
            is_speak (bool, optional): Whether the message is for speech synthesis. Defaults to False.
            is_translated (bool, optional): Whether the message is translated. Defaults to False.

        Returns:
            str: The formatted message with variables substituted.

        Raises:
            ValueError: If language code is not specified or template not found.
        """
        if language is None:
            logger.error("Language code is not specified")
            msg = "Language code is not specified"
            raise ValueError(msg)

        # Get the appropriate template based on context
        template: str = self._get_message_template(language, is_translated=is_translated)
        logger.debug("Message template: %s", template)

        # Build all format variables
        variables: FormatVariables = self._build_format_variables(content, language, is_speak=is_speak)
        logger.debug("Format variables: %s", variables.to_dict())

        # Apply template formatting
        formatted_message: str = template.format(**variables.to_dict())
        # Normalize whitespace
        formatted_message = " ".join(formatted_message.split())

        logger.debug("Formatted message: %s", formatted_message)
        return formatted_message

    def _get_message_template(self, language: str, *, is_translated: bool = False) -> str:
        """Retrieve the appropriate message template based on context.

        Args:
            language (str): The language code for template selection.
            is_translated (bool): Whether to use the translated template.

        Returns:
            str: The selected message template.

        Raises:
            ValueError: If the language code is not found in templates and no 'all' fallback exists.
        """
        # Select template source based on reply status
        if not self._message_handler.is_replying:
            templates = (
                self._message_handler.translated_message_templates
                if is_translated
                else self._message_handler.message_templates
            )
        else:
            # Use reply template for reply messages
            templates: dict[str, str] = self._message_handler.reply_message_templates

        return self._find_template_for_language(templates, language)

    def _build_format_variables(
        self,
        content: str | None,
        language: str,
        *,
        is_speak: bool = False,
    ) -> FormatVariables:
        """Build all format variables based on message context.

        Determines which variables should be populated based on whether the message
        is for speech synthesis, translation, or display, and handles the reply context.

        Args:
            content (str | None): The message content to include.
            language (str): The language code for language-specific formatting.
            is_speak (bool): Whether the message is for speech synthesis.

        Returns:
            FormatVariables: Container with all prepared format variables.
        """
        variables = FormatVariables(message=content or "")

        if is_speak:
            # For speech synthesis, include linguistic separators and author information
            variables.period = self._find_template_for_language(self._message_handler.waiting_period, language)
            variables.comma = self._find_template_for_language(self._message_handler.waiting_comma, language)
            variables.user_name = str(self._message_handler.author.name)

            # Handle emotes and mentions differently based on reply status
            if self._message_handler.is_replying:
                # For replies: exclude first emote and first mention (reply target)
                variables.emote = self._get_limited_emotes(exclude_first=True)
                variables.reply_name = self._message_handler.reply_name(is_speak=True)
                variables.mention = self._message_handler.mention.get_mentions_strings(is_speak=True)
            else:
                # For non-replies: include all emotes and mentions
                variables.emote = self._message_handler.emote.get_emote_strings()
                variables.mention = self._message_handler.mention.get_mentions_strings(is_speak=True)
        # For text translation: only include mentions (excluding reply target if replying)
        elif self._message_handler.is_replying:
            # Add reply target with '@' prefix
            variables.reply_name = self._message_handler.reply_name(is_speak=False)
            # Exclude first mention (reply target indicator)
            variables.mention = self._message_handler.mention.get_mentions_strings(is_speak=False)
        else:
            # Include all mentions for non-reply messages
            variables.mention = self._message_handler.mention.get_mentions_strings(is_speak=False)

        return variables

    def _get_limited_emotes(self, *, exclude_first: bool = False) -> str:
        """Get emotes with optional exclusion of the first one.

        This is used for reply messages where the first emote should be excluded.

        Args:
            exclude_first (bool): If True, exclude the first emote.

        Returns:
            str: Space-separated string of emotes.
        """
        all_emotes: str = self._message_handler.emote.get_emote_strings()
        if not exclude_first or not all_emotes:
            return all_emotes

        emote_list: list[str] = all_emotes.split()
        if emote_list:
            emote_list.pop(0)
        return " ".join(emote_list)

    @staticmethod
    def _find_template_for_language(templates: dict[str, str], language: str) -> str:
        """Retrieve a template value using language code with fallback to 'all'.

        Args:
            templates (dict[str, str]): Dictionary of templates with language codes as keys.
            language (str): The language code to look up.

        Returns:
            str: The template for the specified language or the 'all' fallback.

        Raises:
            ValueError: If neither the language code nor 'all' key exists in templates.
        """
        template: str | None = templates.get(language) or templates.get("all")
        if template is None:
            logger.error("Language code '%s' not found in templates and no 'all' fallback available", language)
            msg: str = f"Language code '{language}' not present in templates and no 'all' fallback"
            raise ValueError(msg)
        return template

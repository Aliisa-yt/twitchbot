"""
Prior to version 2.14.1, the emoji module defined emoji-related data as variables.
From version 2.14.1 onwards, this data is stored in a separate data file and loaded as needed.
Therefore, when creating an executable with PyInstaller, you must ensure that this data file
is included in the packaged executable.

twitchbot.spec example:
    from PyInstaller.utils.hooks import collect_data_files
    emoji_datas = collect_data_files('emoji.unicode_codes', includes=['*.json'])
    a = Analysis(
        ...
        datas=emoji_datas,
        ...
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import emoji
from packaging.version import Version

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["EmojiHandler"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

if Version(emoji.__version__) < Version("2.14.1"):
    logger.warning(
        "The version of the emoji module currently in use is %s. Version 2.14.1 or later is required.",
        emoji.__version__,
    )


class EmojiHandler:
    """Handles emoji detection, conversion, and text replacement.

    This class provides functionality to detect emojis in text and convert them
    to their textual descriptions in specified languages with fallback support.
    """

    def __init__(self, native_lang: str, second_lang: str) -> None:
        """Initialize the EmojiHandler with language preferences.

        Loads emoji language data for all supported languages to enable
        emoji-to-text conversion.

        Args:
            native_lang (str): The primary language code for emoji conversion (e.g., 'ja', 'en').
            second_lang (str): The secondary language code used as fallback (e.g., 'en', 'es').
        """
        self.native_language: str = native_lang
        self.second_language: str = second_lang

        # Load dictionaries for all languages to enable emoji conversion.
        logger.debug("Loading emoji language data...")
        emoji.config.load_language()
        logger.debug("Emoji language data loaded.")

    def is_purely_emoji(self, text: str) -> bool:
        """Determine if the text consists only of emojis.

        Whitespace characters are ignored during the check.

        Args:
            text (str): The text to be evaluated.

        Returns:
            bool: True if the text consists only of emojis (excluding whitespace), False otherwise.
        """
        return emoji.purely_emoji("".join(text.split()))

    def _single_emoji_to_text(self, emoji_char: str, emj_data: dict[str, str], lang: str) -> str:
        """Convert a single emoji to text in the specified language.

        Attempts to convert the emoji using the following fallback hierarchy:
        1. Specified language (lang)
        2. Native language (self.native_language)
        3. Second language (self.second_language)
        4. English ('en')
        5. Original emoji character (if no conversion is available)

        Args:
            emoji_char (str): The emoji character to convert.
            emj_data (dict[str, str]): A dictionary mapping language codes to emoji descriptions
                in the corresponding language, enclosed in colons (e.g., {"en": ":smile:", "es": ":sonrisa:"}).
            lang (str): The target language code for conversion.

        Returns:
            str: The emoji description in the specified language, a fallback language, or the original emoji.
        """
        logger.debug("'language': '%s'", lang)
        logger.debug(emj_data)

        # Converts emoji in the specified language.
        if lang in emj_data:
            return emj_data[lang][1:-1].replace("_", " ")

        # Falls back to native language.
        if self.native_language in emj_data:
            logger.info("Fallback to native language: '%s'", self.native_language)
            return emj_data[self.native_language][1:-1].replace("_", " ")

        # Falls back to second language.
        if self.second_language in emj_data:
            logger.info("Fallback to second language: '%s'", self.second_language)
            return emj_data[self.second_language][1:-1].replace("_", " ")

        # Falls back to English.
        if "en" in emj_data:
            logger.info("Fallback to English")
            return emj_data["en"][1:-1].replace("_", " ")

        # If conversion is not possible, returns the original emoji.
        return emoji_char

    def emojize_to_text(self, text: str, lang: str = "en") -> str:
        """Convert all emojis in the text to their textual descriptions.

        Replaces each emoji in the input text with its description in the specified language.
        If the specified language is not available, the method falls back to the native language,
        then the second language, then English, and finally returns the original emoji if no
        description is available.

        Args:
            text (str): The text containing emojis to convert.
            lang (str): The target language code for emoji descriptions. Defaults to 'en'.

        Returns:
            str: The text with all emojis replaced by their textual descriptions.
        """
        # Passing lang values using lambda functions.
        return emoji.replace_emoji(
            text, replace=lambda emoji_char, emj_data: self._single_emoji_to_text(emoji_char, emj_data, lang)
        )

"""TTS text preprocessing module.

Applies emoji-to-text conversion, alphabet-to-katakana transliteration,
and character-count limiting to text before passing it to a TTS engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from handlers.emoji import EmojiHandler
from handlers.katakana import E2KConverter
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config
    from models.voice_models import TTSParam


__all__: list[str] = ["TextPreprocessor"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TextPreprocessor:
    """Preprocesses TTS content before synthesis.

    Applies emoji-to-text conversion, alphabet-to-katakana transliteration
    (for Japanese), and character-count limiting.
    """

    def __init__(self, config: Config) -> None:
        """Initialise TextPreprocessor.

        Args:
            config (Config): Configuration object containing TTS and translation settings.
        """
        self.config: Config = config
        self.emoji: EmojiHandler = EmojiHandler(config.TRANSLATION.NATIVE_LANGUAGE, config.TRANSLATION.SECOND_LANGUAGE)

    def process(self, tts_param: TTSParam) -> TTSParam | None:
        """Preprocess TTS content.

        Applies emoji conversion, katakana transliteration, character limiting,
        and language filtering. Returns None when the content should be skipped.

        Args:
            tts_param (TTSParam): TTS parameters containing content and language code.

        Returns:
            TTSParam | None: Processed TTS parameters, or None if the content should be skipped.
        """
        logger.debug("Convert content: %s", tts_param)
        if tts_param.content_lang is None:
            logger.error("No content language code specified")
            return None

        # Skip if ENABLED_LANGUAGES is set and the content language is not in the list.
        if self.config.TTS.ENABLED_LANGUAGES and tts_param.content_lang not in self.config.TTS.ENABLED_LANGUAGES:
            logger.debug("Language '%s' is not enabled for TTS", tts_param.content_lang)
            return None

        # Convert emojis to text.
        tts_param.content = self.emoji.emojize_to_text(tts_param.content, tts_param.content_lang)
        logger.debug("Converted emojis to text: '%s'", tts_param.content)

        # Transliterate alphabet characters to katakana (Japanese only).
        if self.config.TTS.KATAKANAISE and tts_param.content_lang == "ja":
            tts_param.content = E2KConverter.katakanaize(tts_param.content)

        # Apply the character count limit.
        if self.config.TTS.LIMIT_CHARACTERS:
            tts_param.content = tts_param.content[: self.config.TTS.LIMIT_CHARACTERS]

        if not tts_param.content:
            logger.warning("TTS content is empty after conversion")
            return None
        return tts_param

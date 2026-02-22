from __future__ import annotations

import hashlib
from typing import Final

from utils.string_utils import StringUtils

__all__: list[str] = ["CacheUtils"]

HASH_TEXT_LENGTH_LIMIT: Final[int] = 50  # Number of UTF-8 characters. Set to 0 or negative for no limit.


class CacheUtils:
    """Utility class for cache-related operations."""

    @staticmethod
    def generate_translation_hash_key(
        source_text: str,
        source_lang: str,
        target_lang: str,
        translation_profile: str = "",
        engine: str | None = None,
    ) -> str | None:

        if not CacheUtils.is_hash_eligible(source_text):
            return None

        normalized_source: str = StringUtils.unicode_normalize(source_text)
        engine_norm: str = engine or ""
        return CacheUtils.generate_hash_key(
            normalized_source, source_lang, target_lang, translation_profile, engine_norm
        )

    @staticmethod
    def generate_hash_key(
        normalized_source: str,
        source_lang: str,
        target_lang: str,
        translation_profile: str,
        engine: str | None = None,
    ) -> str:
        """Generate a SHA-256 hash key for translation caching based on input parameters.

        Args:
            normalized_source (str): The normalized source text for translation.
            source_lang (str): The source language code.
            target_lang (str): The target language code.
            translation_profile (str): The translation profile identifier.
            engine (str | None): The translation engine identifier, or None for common cache.

        Returns:
            str: A SHA-256 hash key representing the translation request parameters.
        """
        # Normalize engine representation: treat None as empty string for common cache.
        if engine is None:
            engine = ""

        key_data: str = f"{normalized_source}|{source_lang}|{target_lang}|{translation_profile}|{engine}"
        return hashlib.sha256(key_data.encode("utf-8")).hexdigest()

    @staticmethod
    def is_hash_eligible(source_text: str) -> bool:
        """Check if the source text is eligible for caching based on length.

        Args:
            source_text (str): Source text to check.

        Returns:
            bool: True if eligible for caching, False otherwise.
        """
        if HASH_TEXT_LENGTH_LIMIT <= 0:
            return True
        return len(source_text) <= HASH_TEXT_LENGTH_LIMIT

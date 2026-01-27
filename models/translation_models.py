"""Models for translation-related data.

This module defines data models used for translation tasks, including
- TranslationInfo: Information about the text to be translated.
- CharacterQuota: Information about character limits and usage.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__: list[str] = ["CharacterQuota", "TranslationInfo"]


@dataclass
class TranslationInfo:
    """Stores translation information.

    Attributes:
        content (str): The original text to be translated.
        src_lang (str | None): Source language code for translation.
            If None, the source language is detected automatically.
        tgt_lang (str): Target language code for translation.
        translated_text (str): The result of the translation.
        _is_translate (bool): Whether translation is required. False skips translation, True performs it.
    """

    content: str = ""
    src_lang: str | None = None
    tgt_lang: str = ""
    translated_text: str = ""
    _is_translate: bool = True

    @property
    def is_translate(self) -> bool:
        """Indicates whether translation is needed.

        Returns:
            bool: True if translation is needed, False otherwise.
        """
        return self._is_translate

    @is_translate.setter
    def is_translate(self, value: bool) -> None:
        self._is_translate = value


@dataclass
class CharacterQuota:
    """Stores the number of characters used and the character limit.

    Attributes:
        count (int): The number of characters used.
        limit (int): The maximum number of characters allowed.
        is_quota_valid (bool): Indicates whether the quota information is valid.
    """

    count: int = 0
    limit: int = 0
    is_quota_valid: bool = True

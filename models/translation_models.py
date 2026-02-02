"""Models for translation-related data.

Defines TranslationInfo and CharacterQuota dataclasses for translation tasks.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__: list[str] = ["CharacterQuota", "TranslationInfo"]


@dataclass
class TranslationInfo:
    """Translation request and result information.

    Attributes:
        content (str): Original text to be translated.
        src_lang (str | None): Source language code (None for auto-detection).
        tgt_lang (str): Target language code for translation.
        translated_text (str): Translation result.
        _is_translate (bool): Whether translation is needed (False skips translation).
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
    """Translation service character quota status.

    Attributes:
        count (int): Characters used in current billing period.
        limit (int): Maximum characters allowed in billing period.
        is_quota_valid (bool): Whether quota information is available and valid.
    """

    count: int = 0
    limit: int = 0
    is_quota_valid: bool = True

"""Models for translation-related data.

Defines TranslationInfo and CharacterQuota dataclasses for translation tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.trans.interface import Result, TransInterface

__all__: list[str] = ["CharacterQuota", "TranslationInfo"]


@dataclass
class TranslationInfo:
    """Translation request and result information.

    Attributes:
        content (str): Original text to be translated.
        src_lang (str | None): Source language code (None for auto-detection).
        tgt_lang (str): Target language code for translation.
        translated_text (str): Translation result.
        is_translate (bool): Whether translation is needed (False skips translation).
        engine (TransInterface): Instance of the translation engine used.
    """

    class NullTranslation(TransInterface):
        """Null translation engine that performs no translation and returns empty results."""

        @property
        def count(self) -> int:
            return 0

        @property
        def limit(self) -> int:
            return 0

        @property
        def limit_reached(self) -> bool:
            return False

        @property
        def is_available(self) -> bool:
            return False

        @staticmethod
        def fetch_engine_name() -> str:
            return ""

        def initialize(self, config) -> None:
            _ = config

        async def detect_language(self, content: str, tgt_lang: str) -> Result:
            _ = content, tgt_lang
            return Result()

        async def translation(self, content: str, tgt_lang: str, src_lang: str | None = None) -> Result:
            _ = content, tgt_lang, src_lang
            return Result()

        async def get_quota_status(self) -> CharacterQuota:
            return CharacterQuota()

        async def close(self) -> None:
            pass

    content: str = ""
    src_lang: str | None = None
    tgt_lang: str = ""
    translated_text: str = ""
    is_translate: bool = True  # Must be True.
    engine: TransInterface = field(default_factory=NullTranslation)


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

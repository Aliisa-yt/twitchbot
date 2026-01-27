"""Translation engine management and interfaces.

This package provides translation functionality through pluggable engine implementations,
including Google Translate and DeepL, with quota management and language detection.
"""

from core.trans.interface import (
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
    TranslationQuotaExceededError,
)
from core.trans.manager import TransManager

__all__: list[str] = [
    "NotSupportedLanguagesError",
    "Result",
    "TransInterface",
    "TransManager",
    "TranslateExceptionError",
    "TranslationQuotaExceededError",
]

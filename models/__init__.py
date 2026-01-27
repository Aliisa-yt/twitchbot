"""Data models for Twitchbot.

This package contains dataclass definitions for configuration, translation, voice/TTS parameters,
and regular expression patterns used throughout the application.
"""

from models.config_models import Config, TTSEngine
from models.re_models import (
    CLEARCHAT_PATTERN,
    CLEARMSG_PATTERN,
    COMMAND_PATTERN,
    MENTION_PATTERN,
    ONE_LANGUAGE_DESIGNATION_PATTERN,
    REPLY_PATTERN,
    SERVER_CONFIG_PATTERN,
    TWO_LANGUAGE_DESIGNATIONS_PATTERN,
    URL_PATTERN,
)
from models.translation_models import TranslationInfo
from models.voice_models import (
    TTSInfo,
    TTSInfoPerLanguage,
    TTSParam,
    UserTypeInfo,
    Voice,
)

__all__: list[str] = [
    "CLEARCHAT_PATTERN",
    "CLEARMSG_PATTERN",
    "COMMAND_PATTERN",
    "MENTION_PATTERN",
    "ONE_LANGUAGE_DESIGNATION_PATTERN",
    "REPLY_PATTERN",
    "SERVER_CONFIG_PATTERN",
    "TWO_LANGUAGE_DESIGNATIONS_PATTERN",
    "URL_PATTERN",
    "Config",
    "TTSEngine",
    "TTSInfo",
    "TTSInfoPerLanguage",
    "TTSParam",
    "TranslationInfo",
    "UserTypeInfo",
    "Voice",
]

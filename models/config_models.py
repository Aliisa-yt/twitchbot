"""Configuration data models for Twitch bot settings, including TTS, bot behavior, and voice engine parameters.

This module defines data classes representing various configuration sections for the Twitch bot,
such as TTS settings, bot options, translation preferences, and voice engine parameters.
Each data class encapsulates related configuration options, providing a structured way to manage
and access settings throughout the application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from models.voice_models import UserTypeInfo

if TYPE_CHECKING:
    from pathlib import Path

__all__: list[str] = [
    # "TTS",
    # "Bot",
    # "Cast",
    "Config",
    # "Dictionary",
    # "General",
    "TTSEngine",
    # "TTSFormat",
    # "TimeSignal",
    # "Translation",
    # "Twitch",
]


@dataclass
class General:
    DEBUG: bool = False
    VERSION: str = ""
    TMP_DIR: Path | None = None
    SCRIPT_NAME: str = ""


@dataclass
class Twitch:
    OWNER_NAME: str = ""


@dataclass
class Bot:
    BOT_NAME: str = ""
    COLOR: str = ""
    LOGIN_MESSAGE: str = ""
    DONT_LOGIN_MESSAGE: bool = False
    SHOW_BYNAME: bool = False
    SHOW_EXTENDEDFORMAT: bool = False
    SHOW_BYLANG: bool = False
    CONSOLE_OUTPUT: bool = False
    IGNORE_USERS: list[str] = field(default_factory=list)
    # INTEGRATED_CHAT: bool = False
    # AWAITING_CLEARMSG: float = 0.0


@dataclass
class Translation:
    ENGINE: list[str] = field(default_factory=list)
    GOOGLE_SUFFIX: str = ""
    NATIVE_LANGUAGE: str = ""
    SECOND_LANGUAGE: str = ""


@dataclass
class Dictionary:
    PATH: str = ""
    KATAKANA_DIC: list[str] = field(default_factory=list)
    ROMAJI_DIC: str = ""


@dataclass
class TTS:
    ORIGINAL_TEXT: bool = False
    TRANSLATED_TEXT: bool = False
    ENABLED_LANGUAGES: list[str] = field(default_factory=list)
    KATAKANAISE: bool = False
    EMOTE_TEXT: bool = False
    MENTION: bool = False
    REPLYING_USERNAME: bool = False
    USERNAME: bool = False
    EMOJI_TEXT: bool = False
    LIMIT_SAME_EMOTE: int = 0
    LIMIT_TOTAL_EMOTES: int = 0
    LIMIT_CHARACTERS: int = 0
    LIMIT_TIME: float = 0.0
    ALLOW_TTS_TWEAK: bool = False


@dataclass
class TTSFormat:
    ORIGINAL_MESSAGE: dict[str, str] = field(default_factory=dict)
    TRANSLATED_MESSAGE: dict[str, str] = field(default_factory=dict)
    REPLY_MESSAGE: dict[str, str] = field(default_factory=dict)
    WAITING_COMMA: dict[str, str] = field(default_factory=dict)
    WAITING_PERIOD: dict[str, str] = field(default_factory=dict)


@dataclass
class Cast:
    DEFAULT: list[dict[str, str]] = field(default_factory=list)
    STREAMER: list[dict[str, str]] = field(default_factory=list)
    MODERATOR: list[dict[str, str]] = field(default_factory=list)
    VIP: list[dict[str, str]] = field(default_factory=list)
    SUBSCRIBER: list[dict[str, str]] = field(default_factory=list)
    OTHERS: list[dict[str, str]] = field(default_factory=list)
    SYSTEM: list[dict[str, str]] = field(default_factory=list)


@dataclass
class TTSEngine:
    SERVER: str = ""
    TIMEOUT: float = 10.0
    EARLY_SPEECH: bool = False
    AUTO_STARTUP: bool = False
    EXECUTE_PATH: str = ""


@dataclass
class TimeSignal:
    TEXT: bool = False
    VOICE: bool = False
    CLOCK12: bool = False
    AM_NAME: str = ""
    PM_NAME: str = ""


@dataclass
class Config:
    GENERAL: General = field(default_factory=General)
    TWITCH: Twitch = field(default_factory=Twitch)
    BOT: Bot = field(default_factory=Bot)
    TRANSLATION: Translation = field(default_factory=Translation)
    TTS: TTS = field(default_factory=TTS)
    TTS_FORMAT: TTSFormat = field(default_factory=TTSFormat)
    DICTIONARY: Dictionary = field(default_factory=Dictionary)
    CAST: Cast = field(default_factory=Cast)
    CEVIO_AI: TTSEngine = field(default_factory=TTSEngine)
    CEVIO_CS7: TTSEngine = field(default_factory=TTSEngine)
    BOUYOMICHAN: TTSEngine = field(default_factory=TTSEngine)
    VOICEVOX: TTSEngine = field(default_factory=TTSEngine)
    COEIROINK: TTSEngine = field(default_factory=TTSEngine)
    COEIROINK2: TTSEngine = field(default_factory=TTSEngine)
    TIME_SIGNAL: TimeSignal = field(default_factory=TimeSignal)
    VOICE_PARAMETERS: UserTypeInfo = field(default_factory=UserTypeInfo)

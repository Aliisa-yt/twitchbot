"""Configuration data models for Twitch bot settings.

Defines dataclasses for TTS, bot behavior, translation preferences, and voice engine parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from models.voice_models import UserTypeInfo

if TYPE_CHECKING:
    from pathlib import Path

__all__: list[str] = [
    "GUI",
    "STT",
    "TTS",
    "VAD",
    "Bot",
    "Cache",
    "Cast",
    "Config",
    "Dictionary",
    "General",
    "LevelsVAD",
    "SileroVAD",
    "TTSEngine",
    "TTSFormat",
    "TimeSignal",
    "Translation",
    "Twitch",
]


@dataclass
class General:
    DEBUG: bool = False
    VERSION: str = ""  # Hidden settings that are not published in the INI file.
    TMP_DIR: Path | None = None  # Hidden settings that are not published in the INI file.
    SCRIPT_NAME: str = ""  # Hidden settings that are not published in the INI file.


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
    MENTION: bool = False  # Unused configuration items.
    REPLYING_USERNAME: bool = False  # Unused configuration items.
    USERNAME: bool = False  # Unused configuration items.
    EMOJI_TEXT: bool = False  # Unused configuration items.
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
    SERVER: str = ""  # Not used in CEVIO_CS7/AI
    TIMEOUT: float = 10.0  # Not used in CEVIO_CS7/AI
    EARLY_SPEECH: bool = False
    AUTO_STARTUP: bool = False
    EXECUTE_PATH: str = ""  # Not used in CEVIO_CS7/AI


@dataclass
class TimeSignal:
    ENABLED: bool = False
    LANGUAGE: str = ""
    TEXT: bool = False
    VOICE: bool = False
    CLOCK12: bool = True
    EARLY_MORNING: str = ""
    MORNING: str = ""
    LATE_MORNING: str = ""
    AFTERNOON: str = ""
    LATE_AFTERNOON: str = ""
    EVENING: str = ""
    NIGHT: str = ""
    LATE_NIGHT: str = ""
    TIME_ANNOUNCEMENT: str = ""


@dataclass
class Cache:
    TTL_TRANSLATION_DAYS: int = 7
    TTL_LANGUAGE_DETECTION_DAYS: int = 30
    MAX_ENTRIES_PER_ENGINE: int = 200
    EXPORT_PATH: str = ""


@dataclass
class LevelsVAD:
    START: float = -20.0
    STOP: float = -40.0


@dataclass
class SileroVAD:
    MODEL_PATH: str = "data/stt/silero/silero_vad.onnx"
    THRESHOLD: float = 0.5
    ONNX_THREADS: int = 1  # Hidden setting: ONNX Runtime thread count for Silero VAD.


@dataclass
class VAD:
    MODE: str = "level"
    PRE_BUFFER_MS: int = 300
    POST_BUFFER_MS: int = 500
    MAX_SEGMENT_SEC: int = 20


@dataclass
class STT:
    DEBUG: bool = False  # Hidden settings that are not published in the INI file.
    ENABLED: bool = False
    ENGINE: str = "google_cloud_stt"
    INPUT_DEVICE: str = "default"
    SAMPLE_RATE: int = 16000  # Unused configuration items.
    CHANNELS: int = 1  # Unused configuration items.
    MUTE: bool = False
    LANGUAGE: str = "ja-JP"
    INTERIM_RESULT: bool = False  # Unused configuration items.
    FORWARD_TO_TTS: bool | None = None
    RETRY_MAX: int = 3
    RETRY_BACKOFF_MS: int = 500
    GOOGLE_CLOUD_STT_V2_LOCATION: str = ""
    GOOGLE_CLOUD_STT_V2_MODEL: str = ""
    GOOGLE_CLOUD_STT_V2_RECOGNIZER: str = ""
    CONFIDENCE_THRESHOLD: float | None = None


@dataclass
class GUI:
    LEVEL_METER_REFRESH_RATE: int = 10  # fps


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
    CACHE: Cache = field(default_factory=Cache)
    STT: STT = field(default_factory=STT)
    VAD: VAD = field(default_factory=VAD)
    LEVELS_VAD: LevelsVAD = field(default_factory=LevelsVAD)
    SILERO_VAD: SileroVAD = field(default_factory=SileroVAD)
    GUI: GUI = field(default_factory=GUI)
    VOICE_PARAMETERS: UserTypeInfo = field(default_factory=UserTypeInfo)

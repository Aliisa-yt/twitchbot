"""Data models for Text-to-Speech (TTS) functionality.

Defines Voice, TTSInfo, TTSParam, and UserTypeInfo dataclasses for TTS operations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

__all__: list[str] = [
    "TTSInfo",
    "TTSInfoPerLanguage",
    "TTSParam",
    "UserTypeInfo",
    "Voice",
    "VoiceParamType",
]

# Type alias: int value or None if not applicable to the engine.
VoiceParamType = int | None


@dataclass
class Voice:
    """Voice parameters used for TTS synthesis.

    Attributes:
        cast (str): Voice cast name or ID (engine-specific format).
        volume (VoiceParamType): Volume for voice synthesis (None if not supported).
        speed (VoiceParamType): Speaking speed (None if not supported).
        tone (VoiceParamType): Pitch/tone (None if not supported).
        alpha (VoiceParamType): Voice quality (None if not supported).
        intonation (VoiceParamType): Intonation level (None if not supported).

    Notes:
        VOICEVOX stores floating-point values as integers multiplied by 100.
        Engine support varies: CeVIO/VOICEVOX support all parameters, Google TTS uses None for all.
    """

    cast: str = ""
    volume: VoiceParamType = None
    speed: VoiceParamType = None
    tone: VoiceParamType = None
    alpha: VoiceParamType = None
    intonation: VoiceParamType = None

    def __str__(self) -> str:
        return (
            f"<{self.__class__.__name__} cast: {self.cast}, volume: {self.volume}, speed: {self.speed}, "
            f"tone: {self.tone}, alpha: {self.alpha}, intonation: {self.intonation}>"
        )

    def __repr__(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    def copy(self) -> Voice:
        """Create a copy of this Voice instance.

        Returns:
            Voice: A copy of the Voice instance.
        """
        return replace(self)

    def get(self, name: str, default: Any = None) -> Any:
        """Get parameter value, returning default if None or not found.

        Args:
            name (str): Parameter name.
            default (Any): Default value if parameter is None.

        Returns:
            Any: Parameter value or default.
        """
        value: Any = getattr(self, name, default)
        return default if value is None else value


@dataclass
class TTSInfo:
    """TTS engine and voice configuration for a specific language.

    Attributes:
        supported_lang (str | None): Language code (e.g., 'ja', 'en').
        engine (str | None): TTS engine name.
        voice (Voice): Voice parameters for synthesis.
    """

    supported_lang: str | None = None
    engine: str | None = None
    voice: Voice = field(default_factory=Voice)

    def __str__(self) -> str:
        return (
            f"<{self.__class__.__name__} supported_lang: {self.supported_lang}, "
            f"engine: {self.engine}, voice: {self.voice}>"
        )

    def __repr__(self) -> str:
        return f'{{"supported_lang": "{self.supported_lang}", "engine": "{self.engine}", "voice": {self.voice!r}}}'

    def copy(self) -> TTSInfo:
        """Create a copy of this TTSInfo instance.

        Returns:
            TTSInfo: A copy of the TTSInfo instance.
        """
        return TTSInfo(supported_lang=self.supported_lang, engine=self.engine, voice=self.voice.copy())


# Type alias: Maps language codes to TTS engine information.
# Must be defined after TTSInfo class to avoid undefined type error.
TTSInfoPerLanguage = dict[str, TTSInfo]


@dataclass
class TTSParam:
    """Parameters for TTS synthesis requests.

    Attributes:
        content (str): Text to be synthesized.
        content_lang (str | None): Language code. If None, automatically detected.
        tts_info (TTSInfo): Engine and voice configuration for synthesis.
        filepath (Path | None): Output audio file path (set by TTS engine).
        message_id (str | None): Associated message ID.
        author_name (str | None): Message author name.
    """

    content: str = ""
    content_lang: str | None = None
    tts_info: TTSInfo = field(default_factory=TTSInfo)
    filepath: Path | None = None
    message_id: str | None = None
    author_name: str | None = None


@dataclass
class UserTypeInfo:
    """Voice configurations organized by user type and language.

    Each attribute maps language codes to TTS settings, supporting per-user-type voice customization.

    Attributes:
        streamer (TTSInfoPerLanguage): Voice settings for broadcaster.
        moderator (TTSInfoPerLanguage): Voice settings for moderators.
        vip (TTSInfoPerLanguage): Voice settings for VIP users.
        subscriber (TTSInfoPerLanguage): Voice settings for subscribers.
        others (TTSInfoPerLanguage): Voice settings for all other users.
        system (TTSInfoPerLanguage): Voice settings for system messages.
    """

    streamer: TTSInfoPerLanguage = field(default_factory=dict)
    moderator: TTSInfoPerLanguage = field(default_factory=dict)
    vip: TTSInfoPerLanguage = field(default_factory=dict)
    subscriber: TTSInfoPerLanguage = field(default_factory=dict)
    others: TTSInfoPerLanguage = field(default_factory=dict)
    system: TTSInfoPerLanguage = field(default_factory=dict)

    def get_tts_engine_list(self) -> list[str]:
        """Get unique TTS engine names.

        Returns:
            list[str]: List of unique engine names across all user types and languages.
        """
        tts_engine_names: set[str] = set()
        for _field in fields(type(self)):
            lang_map: TTSInfoPerLanguage = getattr(self, _field.name)
            for tts_info in lang_map.values():
                if tts_info.engine:
                    tts_engine_names.add(tts_info.engine)

        return list(tts_engine_names)

    def get_cast_list(self, engine_name: str) -> list[str]:
        """Get cast names for specified TTS engine.

        Args:
            engine_name (str): Name of the TTS engine.

        Returns:
            list[str]: List of cast names used by the specified engine.
        """
        cast_list: set[str] = set()
        for _field in fields(type(self)):
            lang_map: TTSInfoPerLanguage = getattr(self, _field.name)
            for tts_info in lang_map.values():
                if tts_info.engine == engine_name:
                    cast_list.add(tts_info.voice.cast)

        return list(cast_list)

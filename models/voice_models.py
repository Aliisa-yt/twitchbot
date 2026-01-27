"""Data models for Text-to-Speech (TTS) functionality.

This module defines:
- Voice: Parameters for voice synthesis.
- TTSInfo: Information for each TTS engine.
- TTSParam: Parameters for TTS synthesis requests.
- UserTypeInfo: TTS settings per user type.
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

# Type alias for voice parameters: int value or None if not applicable to the engine
VoiceParamType = int | None


@dataclass
class Voice:
    """Voice parameters used for TTS synthesis.

    Attributes:
        cast (str): Name or ID of the voice cast.
            For CeVIO, this is the cast name; for Bouyomi-chan, the ID; for VOICEVOX, the speaker name.
            For Google TTS, this is dummy data and has no effect.
        volume (VoiceParamType): Volume for voice synthesis. May be None if unused by the engine.
        speed (VoiceParamType): Speaking speed. May be None if unused by the engine.
        tone (VoiceParamType): Pitch. May be None if unused by the engine.
        alpha (VoiceParamType): Voice quality. May be None if unused by the engine.
        intonation (VoiceParamType): Intonation. May be None if unused by the engine.

    Notes:
        The availability and type of each parameter depend on the TTS engine.
        For VOICEVOX, floating-point values are stored as integers multiplied by 100.
        For Google TTS, all values are set to None and engine defaults are used.
    """

    cast: str = ""
    volume: VoiceParamType = None
    speed: VoiceParamType = None
    tone: VoiceParamType = None
    alpha: VoiceParamType = None
    intonation: VoiceParamType = None

    def __str__(self) -> str:
        """Return a human-readable string representation of the Voice instance."""
        return (
            f"<{self.__class__.__name__} cast: {self.cast}, volume: {self.volume}, speed: {self.speed}, "
            f"tone: {self.tone}, alpha: {self.alpha}, intonation: {self.intonation}>"
        )

    def __repr__(self) -> str:
        """Return a JSON representation of the Voice instance for debugging."""
        return json.dumps(asdict(self), ensure_ascii=False)

    def copy(self) -> Voice:
        """Create a copy of this Voice instance.

        Returns:
            Voice: A copy of this Voice instance.
        """
        return replace(self)

    def get(self, name: str, default: Any = None) -> Any:
        """Get the value of a voice parameter attribute.

        This method is useful for safely retrieving voice parameters when the parameter
        may not be set or may be None (indicating the TTS engine doesn't support it).

        Args:
            name (str): The name of the voice parameter attribute (e.g., 'volume', 'speed').
            default (Any): The default value to return if the attribute doesn't exist or is None.

        Returns:
            Any: The attribute value if it exists and is not None, otherwise the default value.

        Example:
            >>> voice = Voice(cast="Speaker", volume=50, speed=None)
            >>> voice.get("volume", 100)  # Returns 50
            >>> voice.get("speed", 100)  # Returns 100 (speed is None)
            >>> voice.get("invalid", 0)  # Returns 0 (attribute doesn't exist)
        """
        value: Any = getattr(self, name, default)
        return default if value is None else value


@dataclass
class TTSInfo:
    """Information about the TTS engine used for synthesis.

    Attributes:
        supported_lang (str | None): Supported language code (e.g., 'ja', 'en').
        engine (str | None): Name of the TTS engine.
        voice (Voice): Voice parameters for synthesis.
    """

    supported_lang: str | None = None
    engine: str | None = None
    voice: Voice = field(default_factory=Voice)

    def __str__(self) -> str:
        """Return a human-readable string representation of the TTSInfo instance."""
        return (
            f"<{self.__class__.__name__} supported_lang: {self.supported_lang}, "
            f"engine: {self.engine}, voice: {self.voice}>"
        )

    def __repr__(self) -> str:
        """Return a JSON representation of the TTSInfo instance for debugging."""
        return f'{{"supported_lang": "{self.supported_lang}", "engine": "{self.engine}", "voice": {self.voice!r}}}'

    def copy(self) -> TTSInfo:
        """Create a copy of this TTSInfo instance.

        Returns:
            TTSInfo: A copy of this TTSInfo instance.
        """
        return TTSInfo(supported_lang=self.supported_lang, engine=self.engine, voice=self.voice.copy())


# Type alias: Maps language codes to TTS engine information
# Note: Must be defined after TTSInfo class to avoid undefined type error
TTSInfoPerLanguage = dict[str, TTSInfo]


@dataclass
class TTSParam:
    """Parameters for TTS synthesis requests.

    filepath is set by the TTS engine after successful synthesis.
    It is used by the audio playback manager to retrieve and play the file.

    Attributes:
        content (str): The text to be synthesized.
        content_lang (str | None): Language code of the text. If None, language is detected automatically.
        tts_info (TTSInfo): TTS engine information to use for synthesis.
        filepath (Path | None): File path to save the synthesized audio.
        message_id (str | None): ID of the associated message.
        author_name (str | None): Name of the message author.
    """

    content: str = ""
    content_lang: str | None = None
    tts_info: TTSInfo = field(default_factory=TTSInfo)
    filepath: Path | None = None
    message_id: str | None = None
    author_name: str | None = None


@dataclass
class UserTypeInfo:
    """TTS settings for each user type.

    Each attribute maps language codes to TTS engine information, allowing different
    voice configurations per language and user type.

    Attributes:
        streamer (TTSInfoPerLanguage): TTS settings for streamers (broadcaster).
        moderator (TTSInfoPerLanguage): TTS settings for channel moderators.
        vip (TTSInfoPerLanguage): TTS settings for VIP users.
        subscriber (TTSInfoPerLanguage): TTS settings for channel subscribers.
        others (TTSInfoPerLanguage): TTS settings for all other users.
        system (TTSInfoPerLanguage): TTS settings for system-generated messages.
    """

    streamer: TTSInfoPerLanguage = field(default_factory=dict)
    moderator: TTSInfoPerLanguage = field(default_factory=dict)
    vip: TTSInfoPerLanguage = field(default_factory=dict)
    subscriber: TTSInfoPerLanguage = field(default_factory=dict)
    others: TTSInfoPerLanguage = field(default_factory=dict)
    system: TTSInfoPerLanguage = field(default_factory=dict)

    def get_tts_engine_list(self) -> list[str]:
        """Get a list of unique TTS engine names used in the TTS settings.

        Returns:
            list[str]: List of unique TTS engine names.
        """
        tts_engine_names: set[str] = set()
        for _field in fields(self):
            lang_map: TTSInfoPerLanguage = getattr(self, _field.name)
            for tts_info in lang_map.values():
                if tts_info.engine:
                    tts_engine_names.add(tts_info.engine)

        return list(tts_engine_names)

    def get_cast_list(self, engine_name: str) -> list[str]:
        """Get a list of cast names for a specific TTS engine.

        Args:
            engine_name (str): Name of the TTS engine to filter by.

        Returns:
            list[str]: List of cast names associated with the specified TTS engine.
        """
        cast_list: set[str] = set()
        for _field in fields(self):
            lang_map: TTSInfoPerLanguage = getattr(self, _field.name)
            for tts_info in lang_map.values():
                if tts_info.engine == engine_name:
                    cast_list.add(tts_info.voice.cast)

        return list(cast_list)

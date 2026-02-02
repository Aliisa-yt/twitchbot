"""VOICEVOX API data models.

Dataclass models for VOICEVOX API responses including audio queries and speaker information.
Some camelCase fields use noqa: N815 annotations due to snake_case conversion conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass

from dataclasses_json import DataClassJsonMixin, dataclass_json

__all__: list[str] = ["AudioQueryType", "Speaker"]


@dataclass_json
@dataclass
class _MoraType(DataClassJsonMixin):
    """Phonetic mora (sound unit) information for Japanese text.

    Attributes:
        text (str): Character text of the mora.
        consonant (str | None): Consonant sound if present.
        consonant_length (float | None): Duration of consonant in seconds.
        vowel (str): Vowel sound.
        vowel_length (float): Duration of vowel in seconds.
        pitch (float): Pitch value for the mora.
    """

    text: str
    consonant: str | None
    consonant_length: float | None
    vowel: str
    vowel_length: float
    pitch: float


@dataclass_json
@dataclass
class _AccentPhraseType(DataClassJsonMixin):
    """Accent phrase information for prosody control.

    Represents a unit of speech with consistent pitch accent for proper intonation.

    Attributes:
        moras (list[_MoraType]): Constituent mora units.
        accent (int): Accent position (0-based index).
        pause_mora (_MoraType | None): Pause/silence unit if present.
        is_interrogative (bool): Whether the phrase ends with question intonation.
    """

    moras: list[_MoraType]
    accent: int
    pause_mora: _MoraType | None
    is_interrogative: bool


@dataclass_json
@dataclass
class AudioQueryType(DataClassJsonMixin):
    """Audio synthesis query parameters for VOICEVOX API.

    Contains all phonetic and prosodic information needed for speech synthesis.
    Some fields (pauseLength, pauseLengthScale) are optional for COEIROINK v1 compatibility.

    Attributes:
        accent_phrases (list[_AccentPhraseType]): Accent phrase units for prosody.
        speedScale (float): Speech speed multiplier (0.5-2.0).
        pitchScale (float): Pitch shift in semitones (-0.15 to 0.15).
        intonationScale (float): Intonation emphasis (0.0-2.0).
        volumeScale (float): Volume multiplier (0.0-2.0).
        prePhonemeLength (float): Silence duration before phoneme in seconds.
        postPhonemeLength (float): Silence duration after phoneme in seconds.
        pauseLength (float | None): Pause duration between phrases (VOICEVOX 0.20.0+).
        pauseLengthScale (float | None): Pause length multiplier (VOICEVOX 0.20.0+).
        outputSamplingRate (int): Audio sampling rate in Hz.
        outputStereo (bool): Stereo output flag.
        kana (str): Kana representation of the input text.
    """

    accent_phrases: list[_AccentPhraseType]
    speedScale: float  # noqa: N815
    pitchScale: float  # noqa: N815
    intonationScale: float  # noqa: N815
    volumeScale: float  # noqa: N815
    prePhonemeLength: float  # noqa: N815
    postPhonemeLength: float  # noqa: N815
    pauseLength: float | None  # noqa: N815
    pauseLengthScale: float | None  # noqa: N815
    outputSamplingRate: int  # noqa: N815
    outputStereo: bool  # noqa: N815
    kana: str


@dataclass_json
@dataclass
class _SpeakerStyle(DataClassJsonMixin):
    """Represents a voice style for a VOICEVOX speaker.

    Attributes:
        name (str): Display name of the style (e.g., "ノーマル").
        id (int): Numeric style identifier.
        type (str | None): Style type classification (optional for COEIROINK v1).
    """

    name: str
    id: int
    type: str | None  # Optional field for COEIROINK v1 compatibility


@dataclass_json
@dataclass
class _SpeakerSupportedFeature(DataClassJsonMixin):
    """Supported synthesis features for a VOICEVOX speaker.

    Attributes:
        permitted_synthesis_morphing (str): Morphing synthesis capability status.
    """

    permitted_synthesis_morphing: str


@dataclass_json
@dataclass
class Speaker(DataClassJsonMixin):
    """Complete speaker information from VOICEVOX API.

    Attributes:
        name (str): Speaker name.
        speaker_uuid (str): Unique identifier for the speaker.
        styles (list[_SpeakerStyle]): Available voice styles.
        version (str): Speaker model version.
        supported_features (_SpeakerSupportedFeature): Feature support information.
    """

    name: str
    speaker_uuid: str
    styles: list[_SpeakerStyle]
    version: str
    supported_features: _SpeakerSupportedFeature

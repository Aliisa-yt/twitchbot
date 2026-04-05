"""Data models for CoeiroInk v2 TTS API payloads."""

from __future__ import annotations

from dataclasses import dataclass

from dataclasses_json import DataClassJsonMixin, LetterCase, dataclass_json

__all__: list[str] = ["Prosody", "SpeakerMeta", "WavMakingParam", "WavProcessingParam", "WavWithDuration"]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _Styles(DataClassJsonMixin):
    """Style metadata for a CoeiroInk speaker."""

    style_name: str
    style_id: int
    base64_icon: str
    base64_portrait: str | None

    def __repr__(self) -> str:
        # base64 fields can be very large, so exclude them from the representation
        return f"_Styles(style_name={self.style_name}, style_id={self.style_id})"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class SpeakerMeta(DataClassJsonMixin):
    """Speaker metadata returned by the CoeiroInk API."""

    speaker_name: str
    speaker_uuid: str
    styles: list[_Styles]
    version: str
    base64_portrait: str

    def __repr__(self) -> str:
        # base64 fields can be very large, so exclude them from the representation
        return (
            f"SpeakerMeta(speaker_name={self.speaker_name}, speaker_uuid={self.speaker_uuid}, "
            f"styles={self.styles}, version={self.version})"
        )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _Phoneme(DataClassJsonMixin):
    """Phoneme and accent information for prosody."""

    phoneme: str
    hira: str
    accent: int


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _WavRange(DataClassJsonMixin):
    """Start and end positions of a waveform segment."""

    start: int
    end: int


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _PhonemePitches(DataClassJsonMixin):
    """Phoneme pitch data with waveform range."""

    phoneme: str
    wav_range: _WavRange


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _MoraDurations(DataClassJsonMixin):
    """Mora duration details with pitch and waveform range."""

    mora: str
    hira: str
    phoneme_pitches: list[_PhonemePitches]
    wav_range: _WavRange


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Prosody(DataClassJsonMixin):
    """Prosody output for text-to-speech synthesis."""

    plain: list[str]
    detail: list[list[_Phoneme]]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class WavMakingParam(DataClassJsonMixin):
    """Parameters for generating the base waveform."""

    speaker_uuid: str
    style_id: int
    text: str
    prosody_detail: list[list[_Phoneme]]
    speed_scale: float


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class WavWithDuration(DataClassJsonMixin):
    """Waveform output with timing information."""

    wav_base64: str
    mora_durations: list[_MoraDurations]
    start_trim_buffer: float
    end_trim_buffer: float

    def __repr__(self) -> str:
        # base64 fields can be very large, so exclude them from the representation
        return (
            f"WavWithDuration(wav_base64=<base64 string>, mora_durations={self.mora_durations}, "
            f"start_trim_buffer={self.start_trim_buffer}, end_trim_buffer={self.end_trim_buffer})"
        )


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class WavProcessingParam(DataClassJsonMixin):
    """Parameters for post-processing the waveform."""

    volume_scale: float
    pitch_scale: float
    intonation_scale: float
    pre_phoneme_length: float
    post_phoneme_length: float
    output_sampling_rate: int
    sampled_interval_value: int
    adjusted_f0: list[float]
    processing_algorithm: str
    start_trim_buffer: float
    end_trim_buffer: float
    pause_length: float
    pause_start_trim_buffer: float
    pause_end_trim_buffer: float
    wav_base64: str
    mora_durations: list[_MoraDurations]

    def __repr__(self) -> str:
        # base64 fields can be very large, so exclude them from the representation
        return (
            f"WavProcessingParam(volume_scale={self.volume_scale}, pitch_scale={self.pitch_scale}, "
            f"intonation_scale={self.intonation_scale}, pre_phoneme_length={self.pre_phoneme_length}, "
            f"post_phoneme_length={self.post_phoneme_length}, "
            f"output_sampling_rate={self.output_sampling_rate}, "
            f"sampled_interval_value={self.sampled_interval_value}, adjusted_f0={self.adjusted_f0}, "
            f"processing_algorithm={self.processing_algorithm}, "
            f"start_trim_buffer={self.start_trim_buffer}, "
            f"end_trim_buffer={self.end_trim_buffer}, pause_length={self.pause_length}, "
            f"pause_start_trim_buffer={self.pause_start_trim_buffer}, "
            f"pause_end_trim_buffer={self.pause_end_trim_buffer}, "
            f"wav_base64=<base64 string>, mora_durations={self.mora_durations})"
        )

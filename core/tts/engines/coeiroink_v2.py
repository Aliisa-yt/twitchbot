"""
This is an implementation of the CoeiroInk (v2) engine, which is currently in an experimental phase.

- An Internal Server Error has occurred due to changes in pitch and intonation values,
  so this feature is currently unavailable.
- The styleID cannot be changed at this time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from dataclasses_json import DataClassJsonMixin, LetterCase, dataclass_json

from core.tts.engines.vv_core import VVCore
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["CoeiroInk2"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

DEFAULT_UUID: Final[str] = "3c37646f-3881-5374-2a83-149267990abc"  # Default UUID for CoeiroInk2


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _Styles(DataClassJsonMixin):
    style_name: str
    style_id: int
    base64_icon: str
    base64_portrait: str | None


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _SpeakerMeta(DataClassJsonMixin):
    speaker_name: str
    speaker_uuid: str
    styles: list[_Styles]
    version: str
    base64_portrait: str


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _Phoneme(DataClassJsonMixin):
    phoneme: str
    hira: str
    accent: int


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _WavRange(DataClassJsonMixin):
    start: int
    end: int


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _PhonemePitches(DataClassJsonMixin):
    phoneme: str
    wav_range: _WavRange


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _MoraDurations(DataClassJsonMixin):
    mora: str
    hira: str
    phoneme_pitches: list[_PhonemePitches]
    wav_range: _WavRange


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _Prosody(DataClassJsonMixin):
    plain: list[str]
    detail: list[list[_Phoneme]]


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _WavMakingParam(DataClassJsonMixin):
    speaker_uuid: str
    style_id: int
    text: str
    prosody_detail: list[list[_Phoneme]]
    speed_scale: float


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _WavWithDuration(DataClassJsonMixin):
    wav_base64: str
    mora_durations: list[_MoraDurations]
    start_trim_buffer: float
    end_trim_buffer: float


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class _WavProcessingParam(DataClassJsonMixin):
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


class CoeiroInk2(VVCore):
    speakers: ClassVar[list[_SpeakerMeta]] = []

    def __init__(self) -> None:
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        return "coeiroink2"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        super().initialize_engine(tts_engine)
        # Output a message to the console
        print("Loaded speech synthesis engine: CoeiroInk2")
        return True

    async def async_init(self, param: UserTypeInfo) -> None:
        await super().async_init(param)

        # Get a list of available speakers
        CoeiroInk2.speakers = await self._api_request(
            method="get",
            url=f"{self.url}/v1/speakers",
            model=_SpeakerMeta,
            is_list=True,
            log_action="GET speakers",
        )
        speakers_list: str = "Available speakers: " + ", ".join(
            f"{speaker.speaker_name} ({speaker.speaker_uuid})" for speaker in CoeiroInk2.speakers
        )
        logger.debug(speakers_list)
        logger.info("%s process initialised", self.__class__.__name__)

    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        """This method processes the TTS parameters and synthesizes speech using the CoeiroInk2 engine.

        As exception handling is performed in the superclass, exceptions are not caught in this method.

        Args:
            ttsparam (TTSParam): TTSParam object containing the text and voice parameters.
        Returns:
            bytes: The synthesized speech audio data in bytes format.
        """
        _prosody: _Prosody = await self._api_request(
            method="post",
            url=f"{self.url}/v1/estimate_prosody",
            model=_Prosody,
            data={"text": ttsparam.content},
            log_action="POST estimate_prosody",
        )

        _wav_making_param: _WavMakingParam = self._set_wav_making_param(ttsparam, _prosody)
        _wav_with_duration: _WavWithDuration = await self._api_request(
            method="post",
            url=f"{self.url}/v1/predict_with_duration",
            model=_WavWithDuration,
            data=_wav_making_param.to_dict(),
            log_action="POST predict_with_duration",
        )

        _wav_processing_param: _WavProcessingParam = self._set_wav_processing_param(ttsparam, _wav_with_duration)
        synthesis_response: bytes = await self._api_request(
            method="post",
            url=f"{self.url}/v1/process",
            model=None,
            data=_wav_processing_param.to_dict(),
            log_action="POST process",
        )

        return synthesis_response

    def _set_wav_making_param(self, ttsparam: TTSParam, prosody: _Prosody) -> _WavMakingParam:
        """Set the parameters for wav making based on the TTS parameters and prosody."""
        return _WavMakingParam(
            speaker_uuid=self._get_speaker_uuid(ttsparam),
            style_id=0,  # Default style ID
            text=ttsparam.content,
            prosody_detail=prosody.detail,
            speed_scale=self._adjust_reading_speed(
                self._convert_parameters(ttsparam.tts_info.voice.speed, self.PARAMETER_RANGE["speedScale"]),
                len(ttsparam.content),
            ),
        )

    def _set_wav_processing_param(self, ttsparam: TTSParam, wav_with_duration: _WavWithDuration) -> _WavProcessingParam:
        """Set the parameters for wav processing based on the TTS parameters and wav with duration."""
        return _WavProcessingParam(
            volume_scale=self._convert_parameters(ttsparam.tts_info.voice.volume, self.PARAMETER_RANGE["volumeScale"]),
            # pitch_scale=self._convert_parameters(
            #     ttsparam.tts_info.voice.tone, self.PARAMETER_RANGE["pitchScale"]
            # ),
            pitch_scale=0.0,  # CoeiroInk(v2) does not support pitchScale
            # intonation_scale=self._convert_parameters(
            #     ttsparam.tts_info.voice.intonation, self.PARAMETER_RANGE["intonationScale"]
            # ),
            intonation_scale=1.0,  # CoeiroInk(v2) does not support intonationScale
            pre_phoneme_length=0.05,
            post_phoneme_length=0.05,
            output_sampling_rate=44100,  # Resampling is performed on values other than 44100.
            sampled_interval_value=0,
            adjusted_f0=[],
            processing_algorithm="coeiroink",
            start_trim_buffer=wav_with_duration.start_trim_buffer,
            end_trim_buffer=wav_with_duration.end_trim_buffer,
            pause_length=0.25,
            pause_start_trim_buffer=0.0,
            pause_end_trim_buffer=0.0,
            wav_base64=wav_with_duration.wav_base64,
            mora_durations=wav_with_duration.mora_durations,
        )

    def _get_speaker_uuid(self, ttsparam: TTSParam) -> str:
        """Get the UUID of the speaker based on the TTS parameters.

        If the speaker name is invalid, the default UUID will be used.
        """
        for speaker_meta in CoeiroInk2.speakers:
            if speaker_meta.speaker_name == ttsparam.tts_info.voice.cast:
                return speaker_meta.speaker_uuid

        logger.warning("As the specified speaker name is invalid, the default value will be used instead.")
        return DEFAULT_UUID

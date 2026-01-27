"""
This is an implementation of the CoeiroInk (v2) engine, which is currently in an experimental phase.

- An Internal Server Error has occurred due to changes in pitch and intonation values,
  so this feature is currently unavailable.
- The styleID cannot be changed at this time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Final

from dataclasses_json import DataClassJsonMixin, dataclass_json

from core.tts.engines.vv_core import VVCore
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["CoeiroInk2"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 50032
DEFAULT_TIMEOUT: Final[float] = 10.0
DEFAULT_UUID: Final[str] = "3c37646f-3881-5374-2a83-149267990abc"  # Default UUID for CoeiroInk2


@dataclass_json
@dataclass
class _Styles(DataClassJsonMixin):
    styleName: str  # noqa: N815
    styleId: int  # noqa: N815
    base64Icon: str  # noqa: N815
    base64Portrait: str | None  # noqa: N815


@dataclass_json
@dataclass
class _SpeakerMeta(DataClassJsonMixin):
    speakerName: str  # noqa: N815
    speakerUuid: str  # noqa: N815
    styles: list[_Styles]  # noqa: N815
    version: str  # noqa: N815
    base64Portrait: str  # noqa: N815


@dataclass_json
@dataclass
class _Phoneme(DataClassJsonMixin):
    phoneme: str
    hira: str
    accent: int


@dataclass_json
@dataclass
class _WavRange(DataClassJsonMixin):
    start: int
    end: int


@dataclass_json
@dataclass
class _PhonemePitches(DataClassJsonMixin):
    phoneme: str
    wavRange: _WavRange  # noqa: N815


@dataclass_json
@dataclass
class _MoraDurations(DataClassJsonMixin):
    mora: str
    hira: str
    phonemePitches: list[_PhonemePitches]  # noqa: N815
    wavRange: _WavRange  # noqa: N815


@dataclass_json
@dataclass
class _Prosody(DataClassJsonMixin):
    plain: list[str]
    detail: list[list[_Phoneme]]


@dataclass_json
@dataclass
class _WavMakingParam(DataClassJsonMixin):
    speakerUuid: str  # noqa: N815
    styleId: int  # noqa: N815
    text: str  # noqa: N815
    prosodyDetail: list[list[_Phoneme]]  # noqa: N815
    speedScale: float  # noqa: N815


@dataclass_json
@dataclass
class _WavWithDuration(DataClassJsonMixin):
    wavBase64: str  # noqa: N815
    moraDurations: list[_MoraDurations]  # noqa: N815
    startTrimBuffer: float  # noqa: N815
    endTrimBuffer: float  # noqa: N815


@dataclass_json
@dataclass
class _WavProcessingParam(DataClassJsonMixin):
    volumeScale: float  # noqa: N815
    pitchScale: float  # noqa: N815
    intonationScale: float  # noqa: N815
    prePhonemeLength: float  # noqa: N815
    postPhonemeLength: float  # noqa: N815
    outputSamplingRate: int  # noqa: N815
    sampledIntervalValue: int  # noqa: N815
    adjustedF0: list[float]  # noqa: N815
    processingAlgorithm: str  # noqa: N815
    startTrimBuffer: float  # noqa: N815
    endTrimBuffer: float  # noqa: N815
    pauseLength: float  # noqa: N815
    pauseStartTrimBuffer: float  # noqa: N815
    pauseEndTrimBuffer: float  # noqa: N815
    wavBase64: str  # noqa: N815
    moraDurations: list[_MoraDurations]  # noqa: N815


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
            url=f"http://{self.host}:{self.port}/v1/speakers",
            model=_SpeakerMeta,
            is_list=True,
            log_action="GET speakers",
        )
        speakers_list: str = "Available speakers: " + ", ".join(
            f"{speaker.speakerName} ({speaker.speakerUuid})" for speaker in CoeiroInk2.speakers
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
            url=f"http://{self.host}:{self.port}/v1/estimate_prosody",
            model=_Prosody,
            data={"text": ttsparam.content},
            log_action="POST estimate_prosody",
        )

        _wav_making_param: _WavMakingParam = self._set_wav_making_param(ttsparam, _prosody)
        _wav_with_duration: _WavWithDuration = await self._api_request(
            method="post",
            url=f"http://{self.host}:{self.port}/v1/predict_with_duration",
            model=_WavWithDuration,
            data=_wav_making_param.to_dict(),
            log_action="POST predict_with_duration",
        )

        _wav_processing_param: _WavProcessingParam = self._set_wav_processing_param(ttsparam, _wav_with_duration)
        synthesis_response: bytes = await self._api_request(
            method="post",
            url=f"http://{self.host}:{self.port}/v1/process",
            model=None,
            data=_wav_processing_param.to_dict(),
            log_action="POST process",
        )

        return synthesis_response

    def _set_wav_making_param(self, ttsparam: TTSParam, prosody: _Prosody) -> _WavMakingParam:
        """Set the parameters for wav making based on the TTS parameters and prosody."""
        return _WavMakingParam(
            speakerUuid=self._get_speaker_uuid(ttsparam),
            styleId=0,  # Default style ID
            text=ttsparam.content,
            prosodyDetail=prosody.detail,
            speedScale=self._adjust_reading_speed(
                self._convert_parameters(ttsparam.tts_info.voice.speed, self.PARAMETER_RANGE["speedScale"]),
                len(ttsparam.content),
            ),
        )

    def _set_wav_processing_param(self, ttsparam: TTSParam, wav_with_duration: _WavWithDuration) -> _WavProcessingParam:
        """Set the parameters for wav processing based on the TTS parameters and wav with duration."""
        return _WavProcessingParam(
            volumeScale=self._convert_parameters(ttsparam.tts_info.voice.volume, self.PARAMETER_RANGE["volumeScale"]),
            # pitchScale=self._convert_parameters(ttsparam.tts_info.voice.tone, self.PARAMETER_RANGE["pitchScale"]),
            pitchScale=0.0,  # CoeiroInk(v2) does not support pitchScale
            # intonationScale=self._convert_parameters(
            #     ttsparam.tts_info.voice.intonation, self.PARAMETER_RANGE["intonationScale"]
            # ),
            intonationScale=1.00,  # CoeiroInk(v2) does not support intonationScale
            prePhonemeLength=0.05,
            postPhonemeLength=0.05,
            outputSamplingRate=44100,  # Resampling is performed on values other than 44100.
            sampledIntervalValue=0,
            adjustedF0=[],
            processingAlgorithm="coeiroink",
            startTrimBuffer=wav_with_duration.startTrimBuffer,
            endTrimBuffer=wav_with_duration.endTrimBuffer,
            pauseLength=0.25,
            pauseStartTrimBuffer=0.0,
            pauseEndTrimBuffer=0.0,
            wavBase64=wav_with_duration.wavBase64,
            moraDurations=wav_with_duration.moraDurations,
        )

    def _get_speaker_uuid(self, ttsparam: TTSParam) -> str:
        """Get the UUID of the speaker based on the TTS parameters.

        If the speaker name is invalid, the default UUID will be used.
        """
        for speaker_meta in CoeiroInk2.speakers:
            if speaker_meta.speakerName == ttsparam.tts_info.voice.cast:
                return speaker_meta.speakerUuid

        logger.warning("As the specified speaker name is invalid, the default value will be used instead.")
        return DEFAULT_UUID

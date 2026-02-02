"""
This is an implementation of the CoeiroInk (v2) engine, which is currently in an experimental phase.

- An Internal Server Error has occurred due to changes in pitch and intonation values,
  so this feature is currently unavailable.
- The styleID cannot be changed at this time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final

from core.tts.engines.vv_core import SpeakerID, VVCore
from models.coeiroink_v2_models import Prosody, SpeakerMeta, WavMakingParam, WavProcessingParam, WavWithDuration
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["CoeiroInk2"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

DEFAULT_UUID: Final[str] = "3c37646f-3881-5374-2a83-149267990abc"  # Default UUID for CoeiroInk2


class CoeiroInk2(VVCore):
    speakers: ClassVar[list[SpeakerMeta]] = []

    def __init__(self) -> None:
        """Initialize the CoeiroInk2 engine instance."""
        logger.debug("%s initializing", self.__class__.__name__)
        self.available_speakers: dict[str, dict[str, SpeakerID]] = {}
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        """Return the engine identifier."""
        return "coeiroink2"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the engine with configuration settings."""
        super().initialize_engine(tts_engine)
        print("Loaded speech synthesis engine: CoeiroInk2")
        return True

    async def async_init(self, param: UserTypeInfo) -> None:
        """Initialize speakers for the engine."""
        self.check_status_command = "/v1/engine_info"
        await super().async_init(param)

        self.available_speakers = await self.fetch_available_speakers()

        # CoeiroInk(v2) does not implement initialize_speaker, so preloading is not required.
        # cast_list: list[str] = param.get_cast_list(self.fetch_engine_name())
        # id_list: list[int] = [self.get_speaker_id_from_cast(cast, self.available_speakers) for cast in cast_list]

        logger.info("%s process initialised", self.__class__.__name__)

    async def fetch_available_speakers(self) -> dict[str, dict[str, SpeakerID]]:
        """Fetch available speakers from the TTS engine.

        Returns:
            dict[str, dict[str, SpeakerID]]: Mapping of available speakers with their styles and features.
        """
        speakers: list[SpeakerMeta] = await self._api_request(
            method="get",
            url=f"{self.url}/v1/speakers",
            model=SpeakerMeta,
            is_list=True,
            log_action="GET speakers",
        )
        logger.debug("Available speakers: %s", speakers)
        return self._build_speaker_id_map(speakers)

    def _build_speaker_id_map(self, speakers: list[SpeakerMeta]) -> dict[str, dict[str, SpeakerID]]:
        """Generate a dictionary mapping speaker casts to their IDs.

        The API speaker list is difficult to query directly, so this builds a dictionary
        keyed by speaker name and style for fast ID lookups.

        Args:
            speakers (list[_SpeakerMeta]): List of Speaker objects retrieved from the API.

        Returns:
            dict[str, dict[str, SpeakerID]]: Mapping of speaker names and styles to IDs.
        """
        id_dict: dict[str, dict[str, SpeakerID]] = {}
        for speaker in speakers:
            style_dict: dict[str, SpeakerID] = {}
            for style in speaker.styles:
                style_dict[style.style_name] = SpeakerID(uuid=speaker.speaker_uuid, style_id=style.style_id)
            id_dict[speaker.speaker_name] = style_dict
        logger.debug("Generated speaker ID dictionary: %s", id_dict)
        return id_dict

    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        """This method processes the TTS parameters and synthesizes speech using the CoeiroInk2 engine.

        As exception handling is performed in the superclass, exceptions are not caught in this method.

        Args:
            ttsparam (TTSParam): TTSParam object containing the text and voice parameters.
        Returns:
            bytes: The synthesized speech audio data in bytes format.
        """
        _prosody: Prosody = await self._api_request(
            method="post",
            url=f"{self.url}/v1/estimate_prosody",
            model=Prosody,
            data={"text": ttsparam.content},
            log_action="POST estimate_prosody",
        )

        _wav_making_param: WavMakingParam = self._set_wav_making_param(ttsparam, _prosody)
        _wav_with_duration: WavWithDuration = await self._api_request(
            method="post",
            url=f"{self.url}/v1/predict_with_duration",
            model=WavWithDuration,
            data=_wav_making_param.to_dict(),
            log_action="POST predict_with_duration",
        )

        _wav_processing_param: WavProcessingParam = self._set_wav_processing_param(ttsparam, _wav_with_duration)
        synthesis_response: bytes = await self._api_request(
            method="post",
            url=f"{self.url}/v1/process",
            model=None,
            data=_wav_processing_param.to_dict(),
            log_action="POST process",
        )

        return synthesis_response

    def _set_wav_making_param(self, ttsparam: TTSParam, prosody: Prosody) -> WavMakingParam:
        """Set the parameters for wav making based on the TTS parameters and prosody."""
        return WavMakingParam(
            speaker_uuid=self._get_speaker_uuid(ttsparam),
            style_id=0,  # Default style ID
            text=ttsparam.content,
            prosody_detail=prosody.detail,
            speed_scale=self._adjust_reading_speed(
                self._convert_parameters(ttsparam.tts_info.voice.speed, self.PARAMETER_RANGE["speedScale"]),
                len(ttsparam.content),
            ),
        )

    def _set_wav_processing_param(self, ttsparam: TTSParam, wav_with_duration: WavWithDuration) -> WavProcessingParam:
        """Set the parameters for wav processing based on the TTS parameters and wav with duration."""
        return WavProcessingParam(
            volume_scale=self._convert_parameters(ttsparam.tts_info.voice.volume, self.PARAMETER_RANGE["volumeScale"]),
            pitch_scale=0.0,
            intonation_scale=1.0,
            # Note: From version 2.12 onwards, changing the pitch and intonation settings from their defaults
            #       appears to cause an internal server error.
            # pitch_scale=self._convert_parameters(
            #     ttsparam.tts_info.voice.tone, self.PARAMETER_RANGE["pitchScale"]
            # ),
            # intonation_scale=self._convert_parameters(
            #     ttsparam.tts_info.voice.intonation, self.PARAMETER_RANGE["intonationScale"]
            # ),
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
        uuid: str = self.get_speaker_id_from_cast(ttsparam.tts_info.voice.cast, self.available_speakers).uuid
        if uuid:
            return uuid
        logger.warning("As the specified speaker name is invalid, the default value will be used instead.")
        return DEFAULT_UUID

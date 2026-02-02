"""VOICEVOX text-to-speech engine implementation.

Provides integration with VOICEVOX API for Japanese speech synthesis.
Supports version 0.20.0+ with pauseLength and pauseLengthScale parameters.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Final, TypeVar

from dataclasses_json import DataClassJsonMixin

from core.tts.engines.vv_core import SpeakerID, VVCore
from handlers.async_comm import AsyncCommError
from models.voicevox_models import AudioQueryType, Speaker
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo

__all__: list[str] = ["VoiceVox"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

_DEFAULT_PRE_PHONEME_LENGTH: Final[float] = 0.05  # Silence before phoneme
_DEFAULT_POST_PHONEME_LENGTH: Final[float] = 0.05  # Silence after phoneme
_DEFAULT_PAUSE_LENGTH: Final[float] = 0.25  # Pause between phrases
_DEFAULT_PAUSE_LENGTH_SCALE: Final[float] = 1.00  # Pause scale multiplier
_DEFAULT_OUTPUT_SAMPLING_RATE: Final[int] = 24000  # Sampling rate in Hz
_DEFAULT_OUTPUT_STEREO: Final[bool] = False  # Mono output

T = TypeVar("T", bound=DataClassJsonMixin)


class VoiceVox(VVCore):
    """VOICEVOX text-to-speech engine implementation.

    Provides Japanese speech synthesis via VOICEVOX API.
    Inherits from VVCore for common VOICEVOX-compatible functionality.
    """

    def __init__(self) -> None:
        """Initialize the VOICEVOX engine instance."""
        logger.debug("%s initializing", self.__class__.__name__)
        self.available_speakers: dict[str, dict[str, SpeakerID]] = {}
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        """Return the engine identifier.

        Returns:
            str: "voicevox"
        """
        return "voicevox"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the VOICEVOX engine with configuration.

        Args:
            tts_engine (TTSEngine): Engine configuration settings.

        Returns:
            bool: True if initialization succeeded.
        """
        super().initialize_engine(tts_engine)
        print("Loaded speech synthesis engine: VOICEVOX")
        return True

    async def async_init(self, param: UserTypeInfo) -> None:
        """Asynchronously initialize speakers for the VOICEVOX engine.

        Preloads speaker models specified in the configuration to reduce synthesis latency.

        Args:
            param (UserTypeInfo): User-specific voice configuration containing speaker IDs.
        """
        await super().async_init(param)
        self.available_speakers = await self.fetch_available_speakers()

        cast_list: list[str] = param.get_cast_list(self.fetch_engine_name())
        id_list: list[SpeakerID] = [self.get_speaker_id_from_cast(cast, self.available_speakers) for cast in cast_list]

        for _id in id_list:
            try:
                with contextlib.suppress(ValueError):
                    await self._api_request(
                        method="post",
                        url=f"{self.url}/initialize_speaker",
                        model=None,
                        params={"speaker": str(_id.style_id), "skip_reinit": "true"},
                        log_action="POST initialize_speaker",
                    )
            except AsyncCommError as err:
                logger.error("'%s': %s", self.fetch_engine_name().upper(), err)

        logger.info("%s process initialised", self.__class__.__name__)

    async def fetch_available_speakers(self) -> dict[str, dict[str, SpeakerID]]:
        """Fetch available speakers from the TTS engine.

        Returns:
            dict[str, dict[str, SpeakerID]]: Mapping of available speakers with their styles and features.
        """
        speakers: list[Speaker] = await self._api_request(
            method="get",
            url=f"{self.url}/speakers",
            model=Speaker,
            is_list=True,
            log_action="GET speakers",
        )
        logger.debug("Available speakers: %s", speakers)
        return self._build_speaker_id_map(speakers)

    def _build_speaker_id_map(self, speakers: list[Speaker]) -> dict[str, dict[str, SpeakerID]]:
        """Generate a dictionary mapping speaker casts to their IDs.

        The API speaker list is difficult to query directly, so this builds a dictionary
        keyed by speaker name and style for fast ID lookups.

        Args:
            speakers (list[Speaker]): List of Speaker objects retrieved from the API.

        Returns:
            dict[str, dict[str, SpeakerID]]: Mapping of speaker names and styles to IDs.
        """
        id_dict: dict[str, dict[str, SpeakerID]] = {}
        for speaker in speakers:
            style_dict: dict[str, SpeakerID] = {}
            for style in speaker.styles:
                style_dict[style.name] = SpeakerID(uuid=speaker.speaker_uuid, style_id=style.id)
            id_dict[speaker.name] = style_dict
        logger.debug("Generated speaker ID dictionary: %s", id_dict)
        return id_dict

    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        """Execute the VOICEVOX API request to generate synthesized speech.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters.

        Returns:
            bytes: WAV audio data of the synthesized speech.
        """
        _api_data: AudioQueryType = await self._api_request(
            method="post",
            url=f"{self.url}/audio_query",
            model=AudioQueryType,
            params={"text": ttsparam.content, "speaker": str(self._get_style_id(ttsparam))},
            log_action="POST audio_query",
        )

        self._set_synthesis_parameters(_api_data, ttsparam)

        synthesis_response: bytes = await self._api_request(
            method="post",
            url=f"{self.url}/synthesis",
            model=None,
            data=_api_data.to_dict(),
            params={"speaker": str(self._get_style_id(ttsparam)), "interrogative_upspeak": "true"},
            log_action="POST synthesis",
        )

        return synthesis_response

    def _set_synthesis_parameters(self, audio_query: AudioQueryType, ttsparam: TTSParam) -> None:
        """Apply user-specified synthesis parameters to the audio query.

        Args:
            audio_query (AudioQueryType): Audio query object to modify.
            ttsparam (TTSParam): User's text-to-speech parameters.
        """
        audio_query.speedScale = self._adjust_reading_speed(
            self._convert_parameters(ttsparam.tts_info.voice.speed, self.PARAMETER_RANGE["speedScale"]),
            len(ttsparam.content),
        )

        audio_query.pitchScale = self._convert_parameters(
            ttsparam.tts_info.voice.tone, self.PARAMETER_RANGE["pitchScale"]
        )

        audio_query.intonationScale = self._convert_parameters(
            ttsparam.tts_info.voice.intonation, self.PARAMETER_RANGE["intonationScale"]
        )

        audio_query.volumeScale = self._convert_parameters(
            ttsparam.tts_info.voice.volume, self.PARAMETER_RANGE["volumeScale"]
        )

        audio_query.prePhonemeLength = _DEFAULT_PRE_PHONEME_LENGTH
        audio_query.postPhonemeLength = _DEFAULT_POST_PHONEME_LENGTH
        audio_query.pauseLength = _DEFAULT_PAUSE_LENGTH
        audio_query.pauseLengthScale = _DEFAULT_PAUSE_LENGTH_SCALE
        audio_query.outputSamplingRate = _DEFAULT_OUTPUT_SAMPLING_RATE
        audio_query.outputStereo = _DEFAULT_OUTPUT_STEREO

        logger.debug(
            "speaker: %d, speedScale: %.2f, pitchScale: %.2f, intonationScale: %.2f, volumeScale: %.2f",
            self._get_style_id(ttsparam),
            audio_query.speedScale,
            audio_query.pitchScale,
            audio_query.intonationScale,
            audio_query.volumeScale,
        )

    def _get_style_id(self, ttsparam: TTSParam) -> int:
        """Extract and validate the speaker ID from TTS parameters.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters containing voice cast.

        Returns:
            int: The speaker ID, or default if invalid.
        """
        # Return the default speaker ID if the cast is empty or invalid.
        return self.get_speaker_id_from_cast(ttsparam.tts_info.voice.cast, self.available_speakers).style_id

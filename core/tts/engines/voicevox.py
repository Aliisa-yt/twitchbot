"""
In version 0.20.0, parameters were added to _AudioQueryType
pauseLength: float | None
pauseLengthScale: float
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dataclasses_json import DataClassJsonMixin, dataclass_json

from core.tts.engines.vv_core import VVCore
from handlers.async_comm import AsyncCommError
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["VoiceVox"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# Default synthesis parameters
_DEFAULT_PRE_PHONEME_LENGTH: Final[float] = 0.05
_DEFAULT_POST_PHONEME_LENGTH: Final[float] = 0.05
_DEFAULT_PAUSE_LENGTH: Final[float] = 0.25
_DEFAULT_PAUSE_LENGTH_SCALE: Final[float] = 1.00
_DEFAULT_OUTPUT_SAMPLING_RATE: Final[int] = 24000
_DEFAULT_OUTPUT_STEREO: Final[bool] = False
_DEFAULT_SPEAKER_ID: Final[int] = 0


@dataclass_json
@dataclass
class _MoraType(DataClassJsonMixin):
    text: str
    consonant: str | None
    consonant_length: float | None
    vowel: str
    vowel_length: float
    pitch: float


@dataclass_json
@dataclass
class _AccentPhraseType(DataClassJsonMixin):
    moras: list[_MoraType]
    accent: int
    pause_mora: _MoraType | None
    is_interrogative: bool


@dataclass_json
@dataclass
class _AudioQueryType(DataClassJsonMixin):
    accent_phrases: list[_AccentPhraseType]
    speedScale: float  # noqa: N815
    pitchScale: float  # noqa: N815
    intonationScale: float  # noqa: N815
    volumeScale: float  # noqa: N815
    prePhonemeLength: float  # noqa: N815
    postPhonemeLength: float  # noqa: N815
    pauseLength: float | None  # noqa: N815
    pauseLengthScale: float  # noqa: N815
    outputSamplingRate: int  # noqa: N815
    outputStereo: bool  # noqa: N815
    kana: str


class VoiceVox(VVCore):
    """VOICEVOX text-to-speech engine implementation.

    Provides integration with VOICEVOX API for high-quality Japanese speech synthesis.
    Inherits from VVCore for common VOICEVOX-compatible engine functionality.
    """

    def __init__(self) -> None:
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        """Return the engine identifier.

        Returns:
            str: The string "voicevox" identifying this engine.
        """
        return "voicevox"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the VOICEVOX engine with configuration.

        Args:
            tts_engine (TTSEngine): Engine configuration settings.

        Returns:
            bool: Always returns True indicating successful initialization.
        """
        super().initialize_engine(tts_engine)
        # Output a message to the console
        print("Loaded speech synthesis engine: VOICEVOX")
        return True

    async def async_init(self, param: UserTypeInfo) -> None:
        """Asynchronously initialize speakers for the VOICEVOX engine.

        Preloads all speaker models specified in the user configuration to reduce
        initial synthesis latency.

        Args:
            param (UserTypeInfo): User-specific voice configuration containing speaker IDs.
        """
        await super().async_init(param)
        # Get the list of Speaker IDs to use
        for _id in param.get_cast_list(self.fetch_engine_name()):
            try:
                with contextlib.suppress(ValueError):
                    await self._api_request(
                        method="post",
                        url=f"{self.url}/initialize_speaker",
                        model=None,
                        params={"speaker": str(_id), "skip_reinit": "true"},
                        log_action="POST initialize_speaker",
                    )
            except AsyncCommError as err:
                logger.error("'%s': %s", self.fetch_engine_name().upper(), err)

        logger.info("%s process initialised", self.__class__.__name__)

    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        """Execute the VOICEVOX API request to generate synthesized speech.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters including text, voice settings, and speaker.

        Returns:
            bytes: WAV audio data of the synthesized speech.
        """
        _api_data: _AudioQueryType = await self._api_request(
            method="post",
            url=f"{self.url}/audio_query",
            model=_AudioQueryType,
            params={"text": ttsparam.content, "speaker": str(self._get_speaker_id(ttsparam))},
            log_action="POST audio_query",
        )

        # Reflect parameters such as speaking speed and pitch
        self._set_synthesis_parameters(_api_data, ttsparam)

        synthesis_response: bytes = await self._api_request(
            method="post",
            url=f"{self.url}/synthesis",
            model=None,  # No model needed for raw bytes response
            data=_api_data.to_dict(),
            params={"speaker": str(self._get_speaker_id(ttsparam)), "interrogative_upspeak": "true"},
            log_action="POST synthesis",
        )

        return synthesis_response

    def _set_synthesis_parameters(self, audio_query: _AudioQueryType, ttsparam: TTSParam) -> None:
        """Apply user-specified synthesis parameters to the audio query.

        Args:
            audio_query (_AudioQueryType): The audio query object to modify.
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
            self._get_speaker_id(ttsparam),
            audio_query.speedScale,
            audio_query.pitchScale,
            audio_query.intonationScale,
            audio_query.volumeScale,
        )

    def _get_speaker_id(self, ttsparam: TTSParam) -> int:
        """Extract and validate the speaker ID from TTS parameters.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters containing voice cast information.

        Returns:
            int: The speaker ID, or the default speaker ID if invalid.
        """
        try:
            if ttsparam.tts_info.voice.cast is None:
                raise TypeError
            return int(ttsparam.tts_info.voice.cast)
        except (ValueError, TypeError):
            logger.warning("use default value because speakerID is invalid")
            return _DEFAULT_SPEAKER_ID

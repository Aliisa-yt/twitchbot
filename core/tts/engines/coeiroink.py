"""COEIROINK text-to-speech engine implementation.

Provides integration with COEIROINK v1 API for Japanese speech synthesis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from core.tts.engines.voicevox import VoiceVox
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam
    from models.voicevox_models import AudioQueryType


__all__: list[str] = ["CoeiroInk"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

_DEFAULT_PRE_PHONEME_LENGTH: Final[float] = 0.05  # Silence before speech
_DEFAULT_POST_PHONEME_LENGTH: Final[float] = 0.05  # Silence after speech
_DEFAULT_OUTPUT_SAMPLING_RATE: Final[int] = 24000  # Audio sampling rate in Hz
_DEFAULT_OUTPUT_STEREO: Final[bool] = False  # Mono output by default


class CoeiroInk(VoiceVox):
    """COEIROINK v1 engine wrapper."""

    def __init__(self) -> None:
        """Initialize the COEIROINK engine instance."""
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()

    @staticmethod
    def fetch_engine_name() -> str:
        """Return the engine identifier."""
        return "coeiroink"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the COEIROINK engine with configuration."""
        super(VoiceVox, self).initialize_engine(tts_engine)
        print("Loaded speech synthesis engine: COEIROINK")
        return True

    def _set_synthesis_parameters(self, audio_query: AudioQueryType, ttsparam: TTSParam) -> None:
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

"""Text-to-speech engine management and audio playback.

This package provides TTS synthesis and playback functionality through pluggable engine implementations,
including support for multiple voice engines, audio processing, and parameter management.
"""

from core.tts.audio_playback_manager import AudioPlaybackManager
from core.tts.interface import (
    Interface,
    TTSExceptionError,
    TTSFileCreateError,
    TTSFileError,
    TTSFileExistsError,
    TTSNotSupportedError,
)
from core.tts.manager import TTSManager
from core.tts.parameter_manager import ParameterManager
from core.tts.synthesis_manager import SynthesisManager

__all__: list[str] = [
    "AudioPlaybackManager",
    "Interface",
    "ParameterManager",
    "SynthesisManager",
    "TTSExceptionError",
    "TTSFileCreateError",
    "TTSFileError",
    "TTSFileExistsError",
    "TTSManager",
    "TTSNotSupportedError",
]

"""Text-to-speech engine implementations.

This package contains concrete implementations of the Interface for different TTS services,
including VOICEVOX, CeVIO AI/CS7, CoeiroINK, BouyomiChan, and Google Text-to-Speech.
"""

from core.tts.engines.bouyomichan import BouyomiChanSocket
from core.tts.engines.cevio_ai import CevioAI
from core.tts.engines.cevio_cs7 import CevioCS7
from core.tts.engines.coeiroink import CoeiroInk
from core.tts.engines.coeiroink_v2 import CoeiroInk2
from core.tts.engines.g_tts import GoogleText2Speech
from core.tts.engines.voicevox import VoiceVox
from core.tts.engines.vv_core import VVCore

__all__: list[str] = [
    "BouyomiChanSocket",
    "CevioAI",
    "CevioCS7",
    "CoeiroInk",
    "CoeiroInk2",
    "GoogleText2Speech",
    "VVCore",
    "VoiceVox",
]

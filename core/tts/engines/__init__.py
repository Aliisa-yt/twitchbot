"""Text-to-speech engine implementations.

This package contains concrete implementations of the Interface for different TTS services,
including VOICEVOX, CeVIO AI/CS7, CoeiroINK, BouyomiChan, and Google Text-to-Speech.
These classes handle the communication with external TTS APIs or local TTS software,
manage request/response formats, and provide error handling specific to each service.

Modules:
- BouyomiChanSocket: Interface for BouyomiChan TTS software via socket communication.
- CevioAI: Implementation for CeVIO AI TTS service.
- CevioCS7: Implementation for CeVIO CS7 TTS service.
- CoeiroInk: Implementation for CoeiroINK TTS service.
- CoeiroInk2: Implementation for CoeiroINK v2 TTS service.
- GoogleText2Speech: Implementation for Google Text-to-Speech service.
- VoiceVox: Implementation for VOICEVOX TTS service.
- VVCore: Base class for VOICEVOX-compatible TTS engines.
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

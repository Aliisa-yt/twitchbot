from __future__ import annotations

import asyncio
import platform
from typing import TYPE_CHECKING

import pythoncom
import win32com.client
from win32.lib.pywintypes import com_error

from core.tts.interface import Interface
from models.voice_models import TTSParam, Voice
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from win32com.client.dynamic import CDispatch

    from models.config_models import TTSEngine


__all__: list[str] = ["CevioCore"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class CevioCore(Interface):
    """Base class for CeVIO TTS engines

    This class provides the core functionality for CeVIO TTS engines, including connection management,
    speech synthesis, and preset management.
    """

    def __init__(self, *, cevio_type: str) -> None:
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()
        self.cevio: CDispatch
        self.talker: CDispatch
        self.cevio_name: str = ""
        # Raise an exception if the value of cevio_type is not "AI" or "CS7"
        cevio_type_upper: str = cevio_type.upper()
        if cevio_type_upper not in ("AI", "CS7"):
            error_message: str = f"Unsupported CeVIO type: {cevio_type}"
            raise ValueError(error_message)
        self.cevio_type: str = cevio_type_upper
        # Preset values of casts available in CeVIO
        self.talk_preset: dict[str, Voice] = {}

    @staticmethod
    def fetch_engine_name() -> str:
        """Returns the distinguished name of CeVIO"""
        return "cevio"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Reads settings from the configuration module and connects to CeVIO"""
        super().initialize_engine(tts_engine)
        if not self.connect_cevio(self.cevio_type):
            logger.critical("CeVIO %s is not available", self.cevio_type)
            return False
        # Output a message to the console
        print(f"Loaded speech synthesis engine: CeVIO {self.cevio_type}")
        return True

    def _get_preset_parameters(self, talker: CDispatch) -> dict[str, Voice]:
        """Get preset information for all casts

        Args:
            talker (CDispatch): CeVIO's Talker COM object

        Returns:
            dict[str, Voice]: Preset information for each cast
        """
        string_array = talker.AvailableCasts
        # Convert string_array to list[str] because it cannot be used as a COM object
        casts_list: list[str] = [string_array.At(i) for i in range(string_array.Length)]
        logger.info("Available casts: %s", casts_list)

        preset: dict[str, Voice] = {}
        for cast in casts_list:
            # By setting the cast, you can get the preset information for that cast
            # Therefore, to get information on multiple casts, it needs to be updated each time
            talker.Cast = cast
            preset[talker.Cast] = Voice(
                cast=talker.Cast,
                volume=talker.Volume,
                tone=talker.Tone,
                speed=talker.Speed,
                alpha=talker.Alpha,
                intonation=talker.ToneScale,
            )
            logger.debug(preset[cast])
        return preset

    @staticmethod
    def _get_apiname(cevio_type: str) -> tuple[str, str]:
        if cevio_type == "AI":
            logger.debug("Using CeVIO AI")
            return (
                "CeVIO.Talk.RemoteService2.ServiceControl2V40",
                "CeVIO.Talk.RemoteService2.Talker2V40",
            )
        if cevio_type == "CS7":
            logger.debug("Using CeVIO CS7")
            return (
                "CeVIO.Talk.RemoteService.ServiceControlV40",
                "CeVIO.Talk.RemoteService.TalkerV40",
            )
        return ("", "")

    def connect_cevio(self, cevio_type: str) -> bool:
        """Connect to CeVIO's COM object

        Args:
            cevio_type (str): "AI" or "CS7"

        Returns:
            bool: True if the connection is successful, False if it fails
        """
        if platform.system() != "Windows":
            logger.error("CeVIO is only available on Windows")
            return False

        api_control, api_talk = self._get_apiname(cevio_type)
        if not api_control:
            logger.error("Invalid CeVIO type specification: %s", cevio_type)
            return False

        def _cleanup() -> None:
            """Helper to clean up COM resources on error."""
            pythoncom.CoUninitialize()

        self.cevio_name = f"CeVIO {cevio_type}"

        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            self.cevio = win32com.client.Dispatch(api_control)
        except com_error as err:
            logger.error("%s initialization failed: %s", self.cevio_name, err)
            _cleanup()
            return False

        if self.linkedstartup:
            logger.info("%s is starting up...", self.cevio_name)
            result = self.cevio.StartHost(True)
            if result != 0:
                logger.error("Failed to start %s. Result: %s", self.cevio_name, result)
                _cleanup()
                return False

        logger.info("%s started successfully", self.cevio_name)
        try:
            self.talker = win32com.client.Dispatch(api_talk)
        except com_error as err:
            logger.error("%s '%s' not available: %s", self.cevio_name, api_talk, err)
            _cleanup()
            return False
        return True

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        """Perform speech synthesis asynchronously

        Since CeVIO is a synchronous API, it runs on a background thread.
        """
        await asyncio.to_thread(self._speech_synthesis_main, ttsparam)
        await self.play(ttsparam)

    def _speech_synthesis_main(self, ttsparam: TTSParam) -> None:
        """Main speech synthesis process (synchronous process)"""
        if not self.cevio.IsHostStarted:
            logger.warning("Speech synthesis not performed because %s is not available", self.cevio_name)
            return

        if not self.talk_preset:
            self.talk_preset = self._get_preset_parameters(self.talker)

        sel_cast: str = ttsparam.tts_info.voice.cast if isinstance(ttsparam.tts_info.voice.cast, str) else "none"
        logger.info("Selected cast: %s", sel_cast)

        if sel_cast.lower() == "none":
            logger.info("Speech synthesis skipped due to voiceless setting")
            return

        self.talker.Cast = sel_cast
        preset_voice: Voice | None = self.talk_preset.get(sel_cast)
        if preset_voice is None:
            logger.error("Preset for cast '%s' not found", sel_cast)
            return

        try:
            # Override parameters (set preset values as default)
            self.talker.Volume = ttsparam.tts_info.voice.get("volume", preset_voice.volume)
            self.talker.Speed = ttsparam.tts_info.voice.get("speed", preset_voice.speed)
            self.talker.Tone = ttsparam.tts_info.voice.get("tone", preset_voice.tone)
            self.talker.Alpha = ttsparam.tts_info.voice.get("alpha", preset_voice.alpha)
            self.talker.ToneScale = ttsparam.tts_info.voice.get("intonation", preset_voice.intonation)
        except com_error as err:
            logger.error("Failed to set parameters: %s", err)
            return

        # Provisional experiment to accelerate reading according to speech time
        if self.earlyspeech and ttsparam.content and len(ttsparam.content) > 30:
            logger.debug("Original speed: %03d", self.talker.Speed)
            self.talker.Speed = self._adjust_cevio_speed(self.talker.Speed, len(ttsparam.content))
            logger.debug("Adjusted speed: %03d", self.talker.Speed)

        logger.debug("Content: %s", ttsparam.content)
        logger.debug(
            "Parameters: cast=%s, volume=%s, speed=%s, tone=%s, alpha=%s, intonation=%s",
            self.talker.Cast,
            self.talker.Volume,
            self.talker.Speed,
            self.talker.Tone,
            self.talker.Alpha,
            self.talker.ToneScale,
        )

        if False:
            # Output sound from CeVIO
            # Currently only used for file generation
            state = self.talker.Speak(ttsparam.content)
            state.Wait()
        else:
            # Output by generating a Wave file
            _voicefile: Path = self.create_audio_filename(suffix="wav")
            logger.debug("TTS file: %s", _voicefile)
            if not self.talker.OutputWaveToFile(ttsparam.content, _voicefile):
                logger.error("Could not generate wave file '%s'", _voicefile)
                return

            ttsparam.filepath = _voicefile
            logger.debug("Wave file generated: %s", _voicefile)

    async def close(self) -> None:
        """Perform CeVIO termination process"""
        if self.linkedstartup:
            self.cevio.CloseHost(0)
        pythoncom.CoUninitialize()
        logger.info("%s process termination", self.__class__.__name__)

    def _adjust_cevio_speed(self, base_speed: int, content_length: int) -> int:
        """Adjust CeVIO speech speed based on content length.

        For content longer than 30 characters, applies polynomial acceleration.
        Upper limit capped at 60 to maintain voice clarity.
        """
        if content_length <= 30:
            return base_speed
        adjustment = int((content_length - 30) ** 1.1 / 10.0)
        return min(base_speed + adjustment, 60)

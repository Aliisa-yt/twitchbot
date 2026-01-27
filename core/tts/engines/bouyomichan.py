from __future__ import annotations

import contextlib
import struct
from typing import TYPE_CHECKING, Final

from core.tts.interface import Interface
from handlers.async_comm import AsyncCommError, AsyncSocket
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam


__all__: list[str] = ["BouyomiChanSocket"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 50001

C_TALK: Final[int] = 0x0001
C_PAUSE: Final[int] = 0x0010
C_RESUME: Final[int] = 0x0020
C_SKIP: Final[int] = 0x0030
C_CLEAR: Final[int] = 0x0040
C_GETPAUSE: Final[int] = 0x0110
C_GETNOWPLAYING: Final[int] = 0x0120
C_GETTASKCOUNT: Final[int] = 0x0130


class BouyomiChanError(Exception):
    """Parent class for exceptions specific to this module

    Currently, it does not perform any special processing, so it only exists for inheritance
    """


class BouyomiChanCommandError(BouyomiChanError):
    """Command error exception for BouyomiChan

    Occurs when a non-existent command is specified
    """


class BouyomiChanCommand:
    """Class to generate commands for BouyomiChan"""

    def __init__(self) -> None:
        """Initialize the BouyomiChanCommand with default values"""
        self.voice_id: int = 0
        self.volume: int = -1
        self.speed: int = -1
        self.tone: int = -1
        self.character_code: Final[int] = 0  # Fixed to UTF-8
        self.message: bytes = b""
        self.message_length: int = 0

    def generation(self, command: str, ttsparam: TTSParam) -> bytes:
        """Generate a binary message according to the command

        Args:
            command (str): The command to be sent to BouyomiChan.
            ttsparam (TTSParam): The parameters for text-to-speech.

        Returns:
            bytes: The generated binary message.

        Raises:
            BouyomiChanCommandError: If the command is not recognized.
        """
        self.voice_id = self._check_voice(ttsparam.tts_info.voice.get("cast", 0))
        self.volume = self._check_volume(ttsparam.tts_info.voice.get("volume", -1))
        self.speed = self._check_speed(ttsparam.tts_info.voice.get("speed", -1))
        self.tone = self._check_tone(ttsparam.tts_info.voice.get("tone", -1))

        _content: str = ttsparam.content or ""
        self.message = _content.encode("utf-8")
        self.message_length = len(self.message)

        command_map: dict[str, list[tuple[str, int | bytes]]] = {
            "talk": [
                ("<H", C_TALK),
                ("<h", self.speed),
                ("<h", self.tone),
                ("<h", self.volume),
                ("<H", self.voice_id),
                ("b", self.character_code),
                ("<I", self.message_length),
                (f"{self.message_length}s", self.message),
            ],
            "pause": [("<H", C_PAUSE)],
            "resume": [("<H", C_RESUME)],
            "skip": [("<H", C_SKIP)],
            "clear": [("<H", C_CLEAR)],
            "getpause": [("<H", C_GETPAUSE)],
            "getnowplaying": [("<H", C_GETNOWPLAYING)],
            "gettaskcount": [("<H", C_GETTASKCOUNT)],
        }

        if command.lower() not in command_map:
            raise BouyomiChanCommandError(command)

        return b"".join(struct.pack(fmt, val) for fmt, val in command_map[command.lower()])

    def _check_speed(self, value: int) -> int:
        """Check and clamp the speed value

        Args:
            value (int): The speed value to check.

        Returns:
            int: The clamped speed value.
        """
        return self._clamp(value, 50, 300) if value != -1 else value

    def _check_tone(self, value: int) -> int:
        """Check and clamp the tone value

        Args:
            value (int): The tone value to check.

        Returns:
            int: The clamped tone value.
        """
        return self._clamp(value, 50, 200) if value != -1 else value

    def _check_volume(self, value: int) -> int:
        """Check and clamp the volume value

        Args:
            value (int): The volume value to check.

        Returns:
            int: The clamped volume value.
        """
        return self._clamp(value, 0, 100) if value != -1 else value

    def _check_voice(self, value: int | str | None) -> int:
        """Check and clamp the voice ID value.

        Args:
            value: The voice ID value to check (int, str, or None).

        Returns:
            int: The clamped voice ID value (0-65535).
        """
        if value is None:
            return 0
        try:
            return self._clamp(int(value), 0, 65535)
        except (ValueError, TypeError):
            logger.warning("Invalid VoiceID '%s'; using default value (0)", value)
            return 0

    @staticmethod
    def _clamp(value: int, min_val: int, max_val: int) -> int:
        """Clamp the value within the specified range

        Args:
            value (int): The value to clamp.
            min_val (int): The minimum value.
            max_val (int): The maximum value.

        Returns:
            int: The clamped value.
        """
        return max(min(value, max_val), min_val)


class BouyomiChanSocket(Interface):
    """Control BouyomiChan via socket communication for speech synthesis

    Perform socket communication with asyncio
    Currently only supports the talk command
    """

    def __init__(self) -> None:
        """Initialize the BouyomiChanSocket with default values"""
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()
        self._buffer = 4096  # Buffer size for future response handling

    @staticmethod
    def fetch_engine_name() -> str:
        """Get the distinguished name of the TTS engine

        Returns:
            str: The distinguished name of the TTS engine.
        """
        return "bouyomichan"
        # Due to moving to a subdirectory, returning __name__ will include the directory name,
        # causing the module to not be found in subsequent processing
        # return __name__

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Setup the TTS engine with the given configuration

        Args:
            config: The configuration for the TTS engine.

        Returns:
            bool: True if setup is successful, False otherwise.
        """
        super().initialize_engine(tts_engine)
        # Output a message to the console
        print("Loaded speech synthesis engine: BouyomiChan")
        return True

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        """Perform speech synthesis using BouyomiChan

        Unlike file-based TTS engines, BouyomiChan processes speech directly
        without generating intermediate audio files. The play() callback is
        not invoked as playback is handled by the BouyomiChan application.

        Args:
            ttsparam (TTSParam): The parameters for text-to-speech.
        Raises:
            BouyomiChanCommandError: If there is an error with the command.
        """
        try:
            cmd = BouyomiChanCommand()
            bytes_msg: bytes = cmd.generation("talk", ttsparam)
        except BouyomiChanCommandError as err:
            logger.error("BouyomiChanCommandError: '%s'", err)
            return

        client = None
        try:
            client = AsyncSocket(timeout=self.timeout, buffer=self._buffer)
            await client.connect(self.address)
            await client.send(bytes_msg)
        except AsyncCommError as err:
            logger.error("'%s': %s", self.fetch_engine_name().upper(), err)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.close()

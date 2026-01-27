from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from models.voice_models import TTSParam, VoiceParamType
from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from handlers.chat_message import ChatMessageHandler
    from models.config_models import Config

__all__: list[str] = ["TTSUtils"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)
# logger.addHandler(logging.NullHandler())

T = TypeVar("T", int, float)


class TTSUtils:
    """Text-to-speech utility functions for TTS parameter preparation and validation.

    Provides helper methods for preparing TTS parameters from chat messages and validating
    voice parameter types.
    """

    @staticmethod
    def create_tts_parameters(config: Config, message: ChatMessageHandler) -> TTSParam:
        """Prepare TTS parameters from a chat message.

        Extracts and processes message content for TTS synthesis:
        - Removes or keeps emotes based on configuration
        - Removes '@' prefix from mentions
        - Compresses multiple spaces
        - Preserves author name and message ID

        Args:
            config (Config): The configuration object containing TTS settings.
            message (ChatMessageHandler): The chat message handler with parsed message data.

        Returns:
            TTSParam: TTS parameters prepared from the message.
        """
        tts_param = TTSParam(content=message.content)
        # Remove flagged emotes or all emotes based on configuration
        tts_param.content = message.emote.remove(tts_param.content, is_remove_all=not config.TTS.EMOTE_TEXT)
        # Remove '@' prefix from mentions to improve speech output
        tts_param.content = message.mention.strip_mentions(tts_param.content, atsign_only=True)
        tts_param.content = StringUtils.compress_blanks(tts_param.content)
        tts_param.author_name = message.author.name
        tts_param.message_id = message.id
        return tts_param

    @staticmethod
    def validate_voice_type(value: VoiceParamType, expected_type: type[T]) -> T | None:
        """Validate and convert a voice parameter value to the expected type.

        Ensures the value is of the correct type (int or float). Returns None if the value is None.

        Args:
            value (VoiceParamType): The value to validate.
            expected_type (type[T]): The expected type, must be int or float.

        Returns:
            T | None: The validated value converted to the expected type, or None.

        Raises:
            TypeError: If expected_type is not int or float, or if value is not of expected type.
        """
        if expected_type not in (int, float):
            msg = "expected_type must be int or float"
            raise TypeError(msg)

        if isinstance(value, expected_type):
            return expected_type(value)
        if value is None:
            return None

        msg: str = f"Expected value of type {expected_type.__name__}, got {type(value).__name__}"
        raise TypeError(msg)

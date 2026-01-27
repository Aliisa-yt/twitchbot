from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from models.re_models import COMMAND_PATTERN
from models.voice_models import TTSInfo, TTSInfoPerLanguage, UserTypeInfo, Voice
from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from twitchio import Chatter

    from config.loader import Config
    from handlers.chat_message import ChatMessageHandler

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class ParameterManager:
    def __init__(self, config: Config) -> None:
        self.config: Config = config
        self.voice_parameters: UserTypeInfo = config.VOICE_PARAMETERS
        self._onetime_voiceparameters: Voice = Voice()
        self._usertype_voiceparameters: TTSInfoPerLanguage = {}

    def clear(self) -> None:
        """Initialize temporary voice parameters and user type-specific voice parameters."""
        self._onetime_voiceparameters = Voice()
        self._usertype_voiceparameters.clear()

    def get_voice_param(self, lang: str | None = None) -> TTSInfo:
        """Retrieve the audio parameters for the specified language.

        Args:
            lang (str, optional): Language to speak. Defaults to config.TRANSLATION.NATIVE_LANGUAGE
        Raises:
            KeyError: If the corresponding parameters are not found
        Returns:
            TTSInfo: Audio parameters for the specified language
        """
        lang = lang or self.config.TRANSLATION.NATIVE_LANGUAGE
        ext_voice: TTSInfo | None = self._usertype_voiceparameters.get(lang) or self._usertype_voiceparameters.get(
            "all"
        )
        if ext_voice is None:
            error_msg: str = f"Voice parameters for '{lang}' and 'all' are missing."
            logger.error(error_msg)
            raise KeyError(error_msg)

        # Apply one-time voice parameters to the retrieved TTSInfo object.
        for param in ["volume", "speed", "tone", "alpha", "intonation"]:
            setattr(ext_voice.voice, param, self._onetime_voiceparameters.get(param, getattr(ext_voice.voice, param)))
        return ext_voice

    def select_voice_usertype(self, message: ChatMessageHandler) -> None:
        """Set parameters according to the sender's user type."""
        self.clear()  # Initialize

        # Mapping of user types to corresponding parameter keys
        author: Chatter = cast("Chatter", message.author)
        user_type_map: dict[str, Chatter | bool] = {
            "streamer": author.broadcaster,
            "moderator": author.moderator,
            "vip": author.vip,
            "subscriber": author.subscriber,
            "others": True,  # Default case
        }
        for key, condition in user_type_map.items():
            if condition:
                logger.debug("'user type': '%s'", key)
                self._usertype_voiceparameters.update(getattr(self.voice_parameters, key, {}))
                break

    def command_voiceparameters(self, message: ChatMessageHandler) -> None:
        """Analyse parameter change commands in chat messages and set temporary voice parameters.

        e.g. {v100, s100, t100, a100, i100}
             {v: volume, s: speed, t: tone, a: alpha, i: intonation}

        Multiple parameter change commands may be specified,
        but the last command for the same parameter takes precedence.

        Args:
            message (ChatMessageHandler): Chat message to be analysed.
        """
        # Extract all command blocks from the message.
        matches: list[re.Match[str]] = list(re.finditer(COMMAND_PATTERN, message.content.lower()))
        logger.debug("Command matches: %s", matches)

        if not matches:
            return

        # Delete whole block.
        # Currently, characters are replaced with spaces so that the index does not shift even
        # if it is processed from the beginning, but it is processed in reverse order because
        # the index may shift if the specification is changed.
        for match_ in reversed(matches):
            message.content = StringUtils.replace_blanks(message.content, match_.start(), match_.end())

        param_map: dict[str, str] = {
            "v": "volume",
            "s": "speed",
            "t": "tone",
            "a": "alpha",
            "i": "intonation",
        }

        # The commands in each block are analysed and parameters are set.
        for match_ in matches:
            for item in map(str.strip, match_.group(1).split(",")):
                if len(item) < 2 or item[0] not in param_map:
                    continue
                try:
                    value = int(item[1:])
                    setattr(self._onetime_voiceparameters, param_map[item[0]], value)
                except ValueError:
                    logger.warning("Invalid command format: '%s'", item)
        logger.debug("Temporary voice parameters: %s", self._onetime_voiceparameters)

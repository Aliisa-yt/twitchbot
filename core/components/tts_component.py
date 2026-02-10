from __future__ import annotations

from typing import TYPE_CHECKING

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["TTSServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

COMPONENT_KWARGS: dict[str, int] = {"priority": 1}


class TTSServiceComponent(ComponentBase, **COMPONENT_KWARGS):
    """TTS service component for Twitch bot.

    Manages TTS functionalities including initialization and teardown of TTS services.
    """

    async def component_load(self) -> None:
        """Load the component and initialize TTS services."""
        await self.tts_manager.initialize()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and close TTS services."""
        await self.tts_manager.close()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

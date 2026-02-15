from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from twitchio.ext import commands

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["TTSServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TTSServiceComponent(ComponentBase):
    """TTS service component for Twitch bot.

    Manages TTS functionalities including initialization and teardown of TTS services,
    as well as providing commands for playback management.
    """

    depends: ClassVar[list[str]] = ["ChatEventsManager"]

    async def component_load(self) -> None:
        """Load the component and initialize TTS services."""
        await self.tts_manager.initialize()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and close TTS services."""
        await self.tts_manager.close()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @commands.command()
    @commands.is_broadcaster()
    async def skip(self, context: commands.Context) -> None:
        """Skip the current playback.

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'skip' invoked by user: %s", context.author.name)

        if self.shared is None:
            return

        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")
            await context.send("Current playback cancelled.")

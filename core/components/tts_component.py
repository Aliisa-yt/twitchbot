"""TTS service component for Twitch bot.

Manages TTS functionalities including initialization and teardown of TTS services,
as well as providing commands for playback management.
"""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, ClassVar

from twitchio.ext import commands
from twitchio.ext.commands import Component

from core.components.base import ComponentBase
from models.voice_models import TTSParam
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from models.voice_models import TimeSignalParam


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
        try:
            await self.tts_manager.initialize()
            logger.debug("'%s' component loaded", self.__class__.__name__)
        except AttributeError as err:
            logger.warning("TTS service initialization skipped due to missing configuration: %s", err)

    async def component_teardown(self) -> None:
        """Teardown the component and close TTS services."""
        with suppress(AttributeError):
            await self.tts_manager.close()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @Component.listener()
    async def event_safe_tts_message(self, payload: TTSParam) -> None:
        """Event listener for safe TTS messages.

        Args:
            payload (TTSParam): The TTS parameters for the message to be synthesized and played.
        """
        queue_data: TTSParam | None = self.tts_manager.prepare_tts_content(payload)
        if queue_data is not None:
            await self.tts_manager.enqueue_tts_synthesis(queue_data)

    @Component.listener()
    async def event_safe_time_signal_message(self, payload: TimeSignalParam) -> None:
        """Event listener for safe time signal messages.

        Args:
            payload (TimeSignalParam): The time signal parameters for the message to be synthesized and played.
        """
        tts_param = TTSParam(
            content=payload.content,
            content_lang=payload.content_lang,
            tts_info=self.tts_manager.get_voice_param(payload.content_lang, is_system=True),
        )
        queue_data: TTSParam | None = self.tts_manager.prepare_tts_content(tts_param)
        if queue_data is not None:
            await self.tts_manager.enqueue_tts_synthesis(queue_data)

    @Component.listener()
    async def event_safe_tts_clear(self) -> None:
        """Event listener for clearing the TTS playback queue."""

        async def _enqueue_delete(tts_param: TTSParam) -> None:
            _file_path: Path | None = tts_param.filepath
            if _file_path is not None:
                self.tts_manager.file_manager.enqueue_file_deletion(_file_path)

        await self.tts_manager.playback_queue.clear(callback=_enqueue_delete)

        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")

    # @Component.listener()
    # async def event_safe_tts_voice_parameters(self, message: ChatMessageHandler) -> None:
    #     """Event listener for configuring TTS voice parameters based on message metadata.
    #
    #     Selects appropriate voice for user type and optionally applies voice parameter changes.
    #
    #     Args:
    #         message (ChatMessageHandler): The chat message handler instance.
    #     """
    #     self.tts_manager.select_voice_usertype(message)
    #     if self.config.TTS.ALLOW_TTS_TWEAK:
    #         self.tts_manager.command_voiceparameters(message)

    @commands.command()
    @commands.is_broadcaster()
    async def skip(self, context: commands.Context) -> None:
        """Skip the current playback.

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'skip' invoked by user: %s", context.author.name)

        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")
            await context.send("Current playback cancelled.")
        else:
            logger.debug("No active playback to skip.")
            await context.send("No active playback to skip.")

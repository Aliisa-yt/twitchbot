"""Command component for Twitch bot.

Provides chat commands for bot control including playback management,
version display, translation engine switching, and usage statistics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from twitchio.ext import commands

from core.components.base import Base
from core.trans.manager import TransManager
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from twitchio import Chatter

    from models.translation_models import CharacterQuota


__all__: list[str] = ["Command"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class Command(Base):
    """Command class to manage bot commands.

    Provides chat commands for bot control including playback management,
    version display, translation engine switching, and usage statistics.
    """

    async def async_init(self) -> None:
        """Initialize the component. No setup required for this component."""

    async def close(self) -> None:
        logger.debug("'%s' process termination", self.__class__.__name__)

    @commands.command()
    async def skip(self, context: commands.Context) -> None:
        """Skip the current playback.

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'skip' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        if self.shared is None:
            return

        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")
            await context.send("Current playback cancelled.")

    @commands.command()
    async def ver(self, context: commands.Context) -> None:
        """Display the version

        Args:
            context (commands.Context): The object passed when processing the command
        """
        logger.debug("Command 'ver' invoked by user: %s", context.author.name)
        await context.send(f"Current version is '{self.config.GENERAL.SCRIPT_NAME} ver.{self.config.GENERAL.VERSION}'")

    # The command to switch translation engines will only take effect when processing of
    # the next 'event_message' begins.
    # Switching immediately could cause inconsistencies if multiple translation requests
    # are made at the same time.
    @commands.command(name="te")
    async def change_translation_engine(self, context: commands.Context, *args) -> None:
        """Display or change the current translation engine.

        If no arguments are provided, the current engine is displayed.
        If 'google' or 'deepl' is specified as an argument, the translation engine is switched accordingly.

        Args:
            context (commands.Context): The context object passed during command execution.
        """
        logger.debug("Command 'te' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        available_translation_engines: list[str] = TransManager.get_trans_engine_names().copy()

        def usage_message() -> str:
            return f"Usage: !te [{'|'.join(available_translation_engines)}]"

        if not args or len(args) == 0:  # Redundant due to linter countermeasures
            await context.send(f"The current translation engine is '{available_translation_engines[0]}'.")
            return

        if len(args) > 1:
            await context.send(usage_message())
            return

        selected_engine: str = args[0].lower()
        if selected_engine in available_translation_engines:
            logger.debug("Changing translation engine to '%s'", selected_engine)
            try:
                available_translation_engines.remove(selected_engine)
                available_translation_engines.insert(0, selected_engine)
            except ValueError:
                await context.send(usage_message())
            except IndexError as err:
                logger.error("Error changing translation engine: %s", err)
            else:
                TransManager.set_trans_engine_names(available_translation_engines)
                await context.send(f"Translation engine switched to '{selected_engine}'.")
        else:
            await context.send(usage_message())

    @commands.command()
    async def trans_usage(self, context: commands.Context) -> None:
        """Display the character usage of the translation engine.

        This value is currently meaningful only when using DeepL.

        Args:
            context (commands.Context): The context object provided during command execution.
        """
        logger.debug("Command 'trans_usage' invoked by: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

        quota: CharacterQuota = await self.trans_manager.get_usage()

        msg: str
        if quota.is_quota_valid:
            if quota.limit > 0:
                percentage: float = (quota.count / quota.limit) * 100
                msg = f"Character usage: {quota.count:,}/{quota.limit:,} ({percentage:.2f}%)"
            else:
                msg = f"Character usage: {quota.count:,}/{quota.limit:,} (---%)"
        else:
            msg = "The current translation engine is unable to use information about character usage."
        logger.debug("Usage message: %s", msg)
        await context.send(msg)

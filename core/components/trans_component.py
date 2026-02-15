from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from twitchio.ext import commands

from core.components.base import ComponentBase
from core.trans.manager import TransManager
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.translation_models import CharacterQuota

if TYPE_CHECKING:
    import logging

__all__: list[str] = ["TranslationServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TranslationServiceComponent(ComponentBase):
    """Translation service component for Twitch bot.

    Manages translation functionalities including initialization and teardown of translation services,
    as well as providing commands for translation engine management and usage statistics.
    """

    depends: ClassVar[list[str]] = ["ChatEventsManager", "CacheServiceComponent"]

    async def component_load(self) -> None:
        """Load the component and initialize translation services."""
        await self.trans_manager.initialize()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and shutdown translation services."""
        await self.trans_manager.shutdown_engines()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @commands.command(name="te")
    @commands.is_broadcaster()
    async def change_translation_engine(self, context: commands.Context, *args) -> None:
        """Display or change the current translation engine.

        If no arguments are provided, the current engine is displayed.
        If 'google' or 'deepl' is specified as an argument, the translation engine is switched accordingly.

        Args:
            context (commands.Context): The context object passed during command execution.
            *args: Optional translation engine name to switch to.
        """
        logger.debug("Command 'te' invoked by user: %s", context.author.name)

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
    @commands.is_broadcaster()
    async def trans_usage(self, context: commands.Context) -> None:
        """Display the character usage of the translation engine.

        This value is currently meaningful only when using DeepL.

        Args:
            context (commands.Context): The context object provided during command execution.
        """
        logger.debug("Command 'trans_usage' invoked by: %s", context.author.name)

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

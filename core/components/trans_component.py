from __future__ import annotations

from typing import TYPE_CHECKING

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["TranslationServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

COMPONENT_KWARGS: dict[str, int] = {"priority": 1}


class TranslationServiceComponent(ComponentBase, **COMPONENT_KWARGS):
    """Translation service component for Twitch bot.

    Manages translation functionalities including initialization and teardown of translation services.
    """

    async def component_load(self) -> None:
        """Load the component and initialize translation services."""
        await self.trans_manager.initialize()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and shutdown translation services."""
        await self.trans_manager.shutdown_engines()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, ClassVar

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["InFlightServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class InFlightServiceComponent(ComponentBase):
    """Component to manage in-flight translation requests and prevent duplicate processing."""

    depends: ClassVar[list[str]] = ["TranslationServiceComponent", "CacheServiceComponent"]

    async def component_load(self) -> None:
        """Load the in-flight manager component."""
        try:
            await self.shared.inflight_manager.component_load()
            logger.debug("'%s' component loaded", self.__class__.__name__)
        except AttributeError as err:
            logger.warning("InFlightManager component initialization skipped due to missing configuration: %s", err)

    async def component_teardown(self) -> None:
        """Teardown the in-flight manager component."""
        with suppress(AttributeError):
            await self.shared.inflight_manager.component_teardown()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

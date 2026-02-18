from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["InFlightServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class InFlightServiceComponent(ComponentBase):
    depends: ClassVar[list[str]] = ["TranslationServiceComponent", "CacheServiceComponent"]

    async def component_load(self) -> None:
        """Load the in-flight manager component."""
        await self.shared.inflight_manager.component_load()
        logger.info("InFlightManager component loaded successfully")

    async def component_teardown(self) -> None:
        """Teardown the in-flight manager component."""
        await self.shared.inflight_manager.component_teardown()
        logger.info("InFlightManager component torn down successfully")

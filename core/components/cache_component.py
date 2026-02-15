"""Cache service component for translation cache."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from twitchio.ext import commands, routines

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from core.cache.manager import TranslationCacheManager
    from models.cache_models import CacheStatistics

__all__: list[str] = ["CacheServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# Setting the file extension to .log excludes it from Git management.
CACHE_EXPORT_PATH: Final[Path] = Path("cache_export.log")

CACHE_MAINTENANCE_INTERVAL: Final[float] = 2.0  # hours
DELAYED_START_TIME: Final[float] = 20.0  # seconds


class CacheServiceComponent(ComponentBase):
    """Manage translation cache initialization, maintenance, and export."""

    depends: ClassVar[list[str]] = ["ChatEventsManager"]

    async def component_load(self) -> None:
        """Load the component and initialize cache services."""
        await self.shared.cache_manager.component_load()
        self.cache_maintenance.start()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and shut down cache services."""
        self.cache_maintenance.cancel()
        await self.shared.cache_manager.component_teardown()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @routines.routine(delta=timedelta(hours=CACHE_MAINTENANCE_INTERVAL), stop_on_error=False)
    async def cache_maintenance(self) -> None:
        """Perform routine maintenance on the translation cache."""
        try:
            cache_manager: TranslationCacheManager = self.shared.cache_manager
            if cache_manager.is_initialized:
                await cache_manager.cleanup_expired_entries()
                logger.debug("Cache maintenance performed")
            else:
                logger.debug("Cache maintenance skipped: Cache manager not initialized")
        except Exception as err:  # noqa: BLE001
            logger.error("Error during cache maintenance: %s", err)

    @cache_maintenance.before_routine
    async def run_delayed_cache_maintenance(self) -> None:
        """Delay the start of the cache maintenance routine."""
        logger.debug("Delaying cache maintenance start by %d seconds", DELAYED_START_TIME)
        await asyncio.sleep(DELAYED_START_TIME)

    @commands.command()
    @commands.is_broadcaster()
    async def cache_stats(self, context: commands.Context) -> None:
        """Display translation cache statistics.

        Args:
            context (commands.Context): Context object passed during command execution.

        Note:
            Restricted to the broadcaster only.
            Output is directed solely to stdout to avoid chat interruptions.
        """
        logger.debug("Command 'cache_stats' invoked by user: %s", context.author.name)

        cache_manager: TranslationCacheManager = self.shared.cache_manager
        if not cache_manager.is_initialized:
            self.print_console_message("Translation cache is not initialized.")
            return

        stats: CacheStatistics = await cache_manager.get_cache_statistics()

        summary_lines: list[str] = []
        summary_lines.append("----- Translation Cache Statistics -----")
        summary_lines.append(f"Total entries: {stats.total_entries}")
        summary_lines.append(f"Total hits: {stats.total_hits}")

        if stats.engine_distribution:
            engine_stats_list: list[str] = []
            for engine, count in stats.engine_distribution.items():
                if engine == "":
                    engine_stats_list.append(f"common: {count}")
                else:
                    engine_stats_list.append(f"{engine}: {count}")
            engine_info: str = ", ".join(engine_stats_list)
            summary_lines.append(f"By engine: {engine_info}")

        if stats.hit_distribution:
            hit_ranges: list[str] = [
                f"{hit_count} hits: {stats.hit_distribution[hit_count]} entries"
                for hit_count in sorted(stats.hit_distribution.keys(), reverse=True)
            ]
            summary_lines.append("\n".join(hit_ranges[:3]))

        for line in summary_lines:
            self.print_console_message(line)

        logger.info("Cache statistics displayed")

    @commands.command()
    @commands.is_broadcaster()
    async def cache_export(self, context: commands.Context) -> None:
        """Export detailed translation cache data to a file.

        Args:
            context (commands.Context): Context object passed during command execution.

        Note:
            Restricted to the broadcaster only.
            Output is directed solely to stdout to avoid chat interruptions.
        """
        logger.debug("Command 'cache_export' invoked by user: %s", context.author.name)

        cache_manager: TranslationCacheManager = self.shared.cache_manager
        if not cache_manager.is_initialized:
            self.print_console_message("Translation cache is not initialized.")
            return

        output_path: Path = CACHE_EXPORT_PATH
        success: bool = await cache_manager.export_cache_detailed(output_path)

        if success:
            msg: str = f"Cache data exported to: {output_path}"
            self.print_console_message(msg)
            logger.info(msg)
        else:
            msg: str = "Failed to export cache data."
            self.print_console_message(msg)
            logger.error(msg)

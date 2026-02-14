"""Cache service component for translation cache."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, cast

from twitchio.ext import commands, routines

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from twitchio import Chatter

    from core.cache.manager import TranslationCacheManager
    from models.cache_models import CacheStatistics

__all__: list[str] = ["CacheServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# Setting the file extension to .log excludes it from Git management.
CACHE_EXPORT_PATH: Final[Path] = Path("cache_export.log")

CACHE_MAINTENANCE_INTERVAL: Final[int] = 2  # hours
DELAYED_START_TIME: Final[int] = 20  # seconds


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

    @routines.routine(delta=timedelta(seconds=DELAYED_START_TIME), iterations=1, wait_first=True)
    async def cache_maintenance(self) -> None:
        """Run periodic cache maintenance.

        Note: Delayed activation avoids congestion immediately after startup.
        """
        cache_manager: TranslationCacheManager = self.shared.cache_manager
        if cache_manager.is_initialized:
            await cache_manager.cleanup_expired_entries()
            logger.debug("Cache maintenance performed")
        else:
            logger.debug("Cache maintenance skipped: Cache manager not initialized")

    @cache_maintenance.after_routine
    async def cache_maintenance_after_time_signal(self) -> None:
        """Reschedule cache maintenance after the time signal routine."""
        _tim: datetime = self._next_time()
        self.cache_maintenance.change_interval(time=_tim)
        logger.debug(
            "Next maintenance schedule: %04d-%02d-%02d %02d:%02d:%02d",
            _tim.year,
            _tim.month,
            _tim.day,
            _tim.hour,
            _tim.minute,
            _tim.second,
        )

    def _next_time(self) -> datetime:
        """Return the next cache maintenance time (current time + 2 hours)."""
        now: datetime = datetime.now().astimezone()
        return now + timedelta(hours=CACHE_MAINTENANCE_INTERVAL)

    @commands.command()
    async def cache_stats(self, context: commands.Context) -> None:
        """Display translation cache statistics.

        Args:
            context (commands.Context): Context object passed during command execution.

        Note:
            Restricted to the broadcaster only.
            Output is directed solely to stdout to avoid chat interruptions.
        """
        logger.debug("Command 'cache_stats' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

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
    async def cache_export(self, context: commands.Context) -> None:
        """Export detailed translation cache data to a file.

        Args:
            context (commands.Context): Context object passed during command execution.

        Note:
            Restricted to the broadcaster only.
            Output is directed solely to stdout to avoid chat interruptions.
        """
        logger.debug("Command 'cache_export' invoked by user: %s", context.author.name)

        if not cast("Chatter", context.author).broadcaster:
            await context.send("This command is available to the broadcaster only.")
            return

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

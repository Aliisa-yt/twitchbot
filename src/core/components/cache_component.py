"""Cache service component for translation cache."""

from __future__ import annotations

import asyncio
import csv
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, override

from twitchio.ext import commands, routines

from core.components.base import ComponentBase
from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from core.cache.cache_manager import TranslationCacheManager
    from models.cache_models import CacheStatistics
    from models.config_models import Cache

__all__: list[str] = ["CacheServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# Setting the file extension to .log excludes it from Git management.
CACHE_EXPORT_PATH: Final[str] = "cache_export.log"
TRANSLATION_CACHE_PRELOAD_DIC_FILENAME: Final[str] = "translation_cache.dic"

CACHE_MAINTENANCE_INTERVAL: Final[float] = 2.0  # hours
DELAYED_START_TIME: Final[float] = 20.0  # seconds


class CacheServiceComponent(ComponentBase):
    """Manage translation cache initialization, maintenance, and export.

    Attributes:
        cache_manager (TranslationCacheManager): The cache manager instance responsible for handling translation cache.

    Event Listeners:
        No event listeners are currently defined for this component.

    Commands:
        !cache_stats: Display translation cache statistics (broadcaster only).
        !cache_export: Export detailed translation cache data to a file (broadcaster only).

    Routine Tasks:
        cache_maintenance: Perform routine maintenance on the translation cache at regular intervals.
    """

    depends: ClassVar[list[str]] = ["TranslationServiceComponent"]

    @override
    async def component_load(self) -> None:
        """Load the component and initialize cache services."""
        await self.shared.cache_manager.component_load()
        await self._load_predefined_translation_cache()
        self.cache_maintenance.start()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def _load_predefined_translation_cache(self) -> None:
        """Load predefined language and translation cache entries from the dictionary file."""
        dictionary_path: Path = self._resolve_predefined_translation_cache_path()
        try:
            with dictionary_path.open(mode="r", encoding="utf-8", newline="") as handle:
                rows: list[list[str]] = list(csv.reader(handle))
        except FileNotFoundError:
            logger.info("Predefined translation cache dictionary not found: %s", dictionary_path)
            return
        except OSError as err:
            logger.warning("Failed to load predefined translation cache dictionary '%s': %s", dictionary_path, err)
            return
        except csv.Error as err:
            logger.warning("Failed to parse predefined translation cache dictionary '%s': %s", dictionary_path, err)
            return

        cache_manager: TranslationCacheManager = self.shared.cache_manager
        loaded_count: int = 0
        for line_number, row in enumerate(rows, start=1):
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            if len(row) != 4:
                logger.warning(
                    "Skipping invalid predefined translation cache entry at %s:%d: expected 4 columns, got %d",
                    dictionary_path,
                    line_number,
                    len(row),
                )
                continue

            source_text, source_lang, translation_text, target_lang = (cell.strip() for cell in row)
            if not all((source_text, source_lang, translation_text, target_lang)):
                logger.warning(
                    "Skipping invalid predefined translation cache entry at %s:%d: empty column",
                    dictionary_path,
                    line_number,
                )
                continue

            detection_registered: bool = await cache_manager.register_language_detection_cache(
                source_text, source_lang
            )
            translation_registered: bool = await cache_manager.register_translation_cache(
                source_text=source_text,
                source_lang=source_lang,
                target_lang=target_lang,
                translation_text=translation_text,
                engine="",
            )
            if detection_registered and translation_registered:
                loaded_count += 1
            else:
                logger.warning(
                    "Failed to register predefined translation cache entry at %s:%d", dictionary_path, line_number
                )

        logger.info("Loaded %d predefined translation cache entry(s) from: %s", loaded_count, dictionary_path)

    def _resolve_predefined_translation_cache_path(self) -> Path:
        """Resolve the predefined translation cache dictionary path."""
        dic_base_path: str = "dic"
        with suppress(AttributeError):
            raw_path: str | Path = self.config.DICTIONARY.PATH
            if raw_path:
                dic_base_path = str(raw_path)
        return FileUtils.resolve_path(Path(dic_base_path) / TRANSLATION_CACHE_PRELOAD_DIC_FILENAME)

    @override
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
        except asyncio.CancelledError:
            logger.debug("Cache maintenance routine cancelled")
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
            await context.send("Translation cache is not initialized.")
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
        await context.send("Cache statistics displayed in console.")

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
            await context.send("Translation cache is not initialized.")
            return

        cfg_cache: Cache | None = getattr(self.config, "CACHE", None)
        export_path: str | None
        if cfg_cache is None:
            logger.warning("Cache configuration section is missing. Using default export path.")
            export_path = CACHE_EXPORT_PATH

        export_path = getattr(cfg_cache, "EXPORT_PATH", None)
        if export_path is None or export_path.strip() == "":
            logger.warning("Cache export path is not set. Using default export path.")
            export_path = CACHE_EXPORT_PATH

        try:
            output_path: Path = FileUtils.resolve_path(export_path)
        except RuntimeError as err:
            msg = f"Error resolving export path: {export_path} - {err}"
            logger.error(msg)
            return

        success: bool = await cache_manager.export_cache_detailed(output_path)

        if success:
            msg = f"Cache data exported to: {output_path}"
            self.print_console_message(msg)
            logger.info(msg)
            await context.send("Cache data export completed successfully.")
        else:
            msg = "Failed to export cache data."
            self.print_console_message(msg)
            logger.error(msg)
            await context.send("Failed to export cache data.")

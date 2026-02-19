# ruff: noqa: BLE001
"""Translation cache manager.

Manages translation and language detection caches using SQLite database with WAL mode.
Provides cache search, registration, in-flight request management, and cleanup functionality.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from models.cache_models import (
    CacheStatistics,
    LanguageDetectionCacheEntry,
    TranslationCacheEntry,
)
from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config

__all__: list[str] = ["TranslationCacheManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

TRANSLATION_CACHE_DB_PATH: Final[Path] = Path("translation_cache.db")


class TranslationCacheManager:
    """Manager for translation and language detection caches.

    Provides caching functionality for translation results and language detection using SQLite database.
    Supports in-flight request management to prevent duplicate translations, TTL-based expiration,
    and capacity-based LRU cleanup.

    Attributes:
        TTL_TRANSLATION_DAYS (ClassVar[int]): TTL for translation cache entries.
        TTL_LANGUAGE_DETECTION_DAYS (ClassVar[int]): TTL for language detection cache entries.
        MAX_ENTRIES_PER_ENGINE (ClassVar[int]): Maximum cache entries per engine.
        INFLIGHT_TIMEOUT_SEC (ClassVar[float]): In-flight request timeout in seconds.
        DB_SCHEMA_VERSION (ClassVar[int]): Cache database schema version.
    """

    TTL_TRANSLATION_DAYS: ClassVar[int] = 7
    TTL_LANGUAGE_DETECTION_DAYS: ClassVar[int] = 30
    MAX_ENTRIES_PER_ENGINE: ClassVar[int] = 200
    DB_SCHEMA_VERSION: ClassVar[int] = 1

    def __init__(self, config: Config) -> None:
        """Initialize the cache manager.

        Args:
            config (Config): Application configuration.
        """
        self.config: Config = config
        self._db_path: Path = TRANSLATION_CACHE_DB_PATH
        self._db_conn: sqlite3.Connection | None = None
        self._is_initialized: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        logger.debug("TranslationCacheManager instance created")

    @property
    def is_initialized(self) -> bool:
        """Check if the cache manager is initialized.

        Returns:
            bool: True if initialized, False otherwise.
        """
        return self._is_initialized

    async def component_load(self) -> None:
        """Initialize the cache manager and database connection."""
        logger.info("TranslationCacheManager initialization started")
        try:
            await self._initialize_database()
            # Do not perform cache clean-up here. Execute only within scheduled tasks.
            # await self.cleanup_expired_entries()
            self._is_initialized = True
            logger.info("TranslationCacheManager initialized successfully")
        except Exception as err:
            logger.critical("Failed to initialize TranslationCacheManager: %s", err)
            self._is_initialized = False

    async def component_teardown(self) -> None:
        """Close database connection and cleanup resources."""
        logger.info("TranslationCacheManager shutdown started")
        if self._db_conn is not None:
            try:
                self._db_conn.close()
                logger.info("Database connection closed")
            except Exception as err:
                logger.error("Error closing database connection: %s", err)
        self._is_initialized = False
        logger.info("TranslationCacheManager shutdown completed")

    async def _initialize_database(self) -> None:
        """Initialize SQLite database with WAL mode and create tables."""
        try:
            self._db_conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._db_conn.execute("PRAGMA journal_mode=WAL")
            self._db_conn.execute("PRAGMA busy_timeout=5000")

            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS translation_cache (
                    cache_key TEXT PRIMARY KEY,
                    normalized_source TEXT NOT NULL,
                    source_lang TEXT NOT NULL,
                    target_lang TEXT NOT NULL,
                    translation_text TEXT NOT NULL,
                    translation_profile TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_key ON translation_cache(cache_key)")
            self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_last_used ON translation_cache(last_used_at)")
            self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON translation_cache(engine)")

            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS language_detection_cache (
                    normalized_source TEXT PRIMARY KEY,
                    detected_lang TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL
                )
                """
            )
            self._db_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_lang_source ON language_detection_cache(normalized_source)"
            )
            self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_lang_used ON language_detection_cache(last_used_at)")

            self._db_conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            self._db_conn.execute(
                "INSERT OR IGNORE INTO cache_metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(self.DB_SCHEMA_VERSION)),
            )
            cursor: sqlite3.Cursor = self._db_conn.execute(
                "SELECT value FROM cache_metadata WHERE key = ?",
                ("schema_version",),
            )
            row = cursor.fetchone()
            if row is not None and row[0] != str(self.DB_SCHEMA_VERSION):
                logger.warning(
                    "Cache DB schema version mismatch (db: %s, expected: %s)",
                    row[0],
                    self.DB_SCHEMA_VERSION,
                )

            self._db_conn.commit()
            logger.info("Database initialized with WAL mode")
        except sqlite3.Error as err:
            msg: str = f"Database initialization failed: {err}"
            logger.critical(msg)
            raise RuntimeError(msg) from err

    def _now_epoch(self) -> int:
        """Get current time as epoch integer."""
        return int(datetime.now().astimezone().timestamp())

    def _epoch_to_datetime(self, value: int | str) -> datetime:
        """Convert epoch integer to datetime object."""
        return datetime.fromtimestamp(int(value), tz=UTC).astimezone()

    async def cleanup_expired_entries(self) -> None:
        """Remove expired cache entries based on TTL."""
        if not self._is_initialized or self._db_conn is None:
            return

        try:
            async with self._lock:
                cutoff_viewer: datetime = datetime.now().astimezone() - timedelta(days=self.TTL_TRANSLATION_DAYS)
                cutoff_streamer: datetime = datetime.now().astimezone() - timedelta(
                    days=self.TTL_LANGUAGE_DETECTION_DAYS
                )

                cursor: sqlite3.Cursor = self._db_conn.execute(
                    "DELETE FROM translation_cache WHERE CAST(last_used_at AS INTEGER) < ?",
                    (int(cutoff_viewer.timestamp()),),
                )
                deleted: int = cursor.rowcount
                logger.info("Deleted %d expired translation cache entries", deleted)

                cursor = self._db_conn.execute(
                    "DELETE FROM language_detection_cache WHERE CAST(last_used_at AS INTEGER) < ?",
                    (int(cutoff_streamer.timestamp()),),
                )
                deleted = cursor.rowcount
                logger.info("Deleted %d expired language detection cache entries", deleted)

                self._db_conn.commit()
        except sqlite3.Error as err:
            logger.error("Error during cache cleanup: %s", err)

    async def search_translation_cache(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        translation_profile: str = "",
        engine: str | None = None,
    ) -> TranslationCacheEntry | None:
        """Search for translation in cache with engine-specific and fallback support.

        Search priority:
            1. Engine-specific cache (with provided engine)
            2. Common cache fallback (engine-independent, only if engine-specific misses)

        Args:
            source_text (str): Source text to translate.
            source_lang (str): Source language code.
            target_lang (str): Target language code.
            translation_profile (str): Translation profile identifier.
            engine (str | None): Translation engine name (None for common cache).

        Returns:
            TranslationCacheEntry | None: Cache entry if found, None otherwise.
        """
        if not self._is_initialized or self._db_conn is None:
            return None
        if not StringUtils.is_hash_eligible(source_text):
            return None

        normalized_source: str = StringUtils.normalize_text(source_text)
        # Keep track whether caller explicitly provided an engine (None means not provided).
        provided_engine: bool = engine is not None
        engine_norm: str = engine or ""

        cache_key: str = StringUtils.generate_hash_key(
            normalized_source, source_lang, target_lang, translation_profile, engine_norm
        )
        if cache_key is None:
            return None

        try:
            entry: TranslationCacheEntry | None = await self._search_translation_entry(cache_key)

            if entry is None and provided_engine:
                logger.debug("Engine-specific cache miss for key: %s, trying fallback", cache_key[:16])

                common_cache_key: str = StringUtils.generate_hash_key(
                    normalized_source, source_lang, target_lang, translation_profile, engine=""
                )
                if common_cache_key is None:
                    return None
                entry = await self._search_translation_entry(common_cache_key)
                if entry is not None:
                    logger.debug("Cache hit via fallback (common cache)")
        except sqlite3.Error as err:
            logger.error("Error searching translation cache: %s", err)
            return None
        else:
            return entry

    async def _search_translation_entry(self, cache_key: str) -> TranslationCacheEntry | None:
        """Internal method to search for a translation cache entry by key.

        Args:
            cache_key (str): The cache key to search for.

        Returns:
            TranslationCacheEntry | None: Cache entry if found and valid, None otherwise.
        """
        if self._db_conn is None:
            return None

        try:
            async with self._lock:
                cursor: sqlite3.Cursor = self._db_conn.execute(
                    """
                    SELECT cache_key, normalized_source, source_lang, target_lang,
                           translation_text, translation_profile, engine,
                           created_at, last_used_at, hit_count
                    FROM translation_cache
                    WHERE cache_key = ?
                    """,
                    (cache_key,),
                )
                row = cursor.fetchone()

                if row is None:
                    logger.debug("Cache miss for key: %s", cache_key[:16])
                    return None

                entry = TranslationCacheEntry(
                    cache_key=row[0],
                    normalized_source=row[1],
                    source_lang=row[2],
                    target_lang=row[3],
                    translation_text=row[4],
                    translation_profile=row[5],
                    engine=row[6],
                    created_at=self._epoch_to_datetime(row[7]),
                    last_used_at=self._epoch_to_datetime(row[8]),
                    hit_count=row[9],
                )

                cutoff: datetime = datetime.now().astimezone() - timedelta(days=self.TTL_TRANSLATION_DAYS)
                if entry.last_used_at < cutoff:
                    self._db_conn.execute("DELETE FROM translation_cache WHERE cache_key = ?", (cache_key,))
                    self._db_conn.commit()
                    logger.debug("Cache entry expired for key: %s", cache_key[:16])
                    return None

                now_epoch: int = self._now_epoch()
                self._db_conn.execute(
                    "UPDATE translation_cache SET last_used_at = ?, hit_count = hit_count + 1 WHERE cache_key = ?",
                    (now_epoch, cache_key),
                )
                self._db_conn.commit()

                entry.hit_count += 1
                entry.last_used_at = self._epoch_to_datetime(now_epoch)

                logger.debug("Cache hit for key: %s (hit_count: %d)", cache_key[:16], entry.hit_count)

        except sqlite3.Error as err:
            logger.error("Error searching translation cache entry: %s", err)
            return None
        else:
            return entry

    async def register_translation_cache(
        self,
        *,
        source_text: str,
        source_lang: str,
        target_lang: str,
        translation_text: str,
        engine: str,
        translation_profile: str = "",
    ) -> bool:
        """Register translation result to cache.

        Args:
            source_text (str): Source text.
            source_lang (str): Source language code.
            target_lang (str): Target language code.
            translation_text (str): Translated text.
            engine (str): Translation engine name.
            translation_profile (str): Translation profile identifier.

        Returns:
            bool: True if registration succeeded, False otherwise.
        """
        if not self._is_initialized or self._db_conn is None:
            return False
        if not StringUtils.is_hash_eligible(source_text):
            return False

        normalized_source: str = StringUtils.normalize_text(source_text)
        cache_key: str = StringUtils.generate_hash_key(
            normalized_source, source_lang, target_lang, translation_profile, engine
        )
        if cache_key is None:
            return False

        try:
            async with self._lock:
                now_epoch: int = self._now_epoch()
                self._db_conn.execute(
                    """
                    INSERT OR REPLACE INTO translation_cache
                    (cache_key, normalized_source, source_lang, target_lang,
                     translation_text, translation_profile, engine,
                     created_at, last_used_at, hit_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        cache_key,
                        normalized_source,
                        source_lang,
                        target_lang,
                        translation_text,
                        translation_profile,
                        engine,
                        now_epoch,
                        now_epoch,
                    ),
                )
                self._db_conn.commit()

            logger.debug("Translation cached for key: %s", cache_key[:16])

            await self._enforce_capacity_limit(engine)

        except sqlite3.Error as err:
            logger.error("Error registering translation cache: %s", err)
            return False
        else:
            return True

    async def _enforce_capacity_limit(self, engine: str) -> None:
        """Enforce capacity limit per engine using LRU strategy.

        Args:
            engine (str): Translation engine name.
        """
        if not self._is_initialized or self._db_conn is None:
            return

        try:
            async with self._lock:
                cursor: sqlite3.Cursor = self._db_conn.execute(
                    "SELECT COUNT(*) FROM translation_cache WHERE engine = ?", (engine,)
                )
                count: int = cursor.fetchone()[0]

                if count > self.MAX_ENTRIES_PER_ENGINE:
                    to_delete: int = count - self.MAX_ENTRIES_PER_ENGINE
                    self._db_conn.execute(
                        """
                        DELETE FROM translation_cache
                        WHERE cache_key IN (
                            SELECT cache_key FROM translation_cache
                            WHERE engine = ?
                            ORDER BY CAST(last_used_at AS INTEGER) ASC, hit_count ASC
                            LIMIT ?
                        )
                        """,
                        (engine, to_delete),
                    )
                    self._db_conn.commit()
                    logger.info("Deleted %d LRU entries for engine: %s", to_delete, engine)

        except sqlite3.Error as err:
            logger.error("Error enforcing capacity limit: %s", err)

    async def search_language_detection_cache(self, source_text: str) -> LanguageDetectionCacheEntry | None:
        """Search for language detection result in cache.

        Args:
            source_text (str): Source text to detect language.

        Returns:
            LanguageDetectionCacheEntry | None: Cache entry if found, None otherwise.
        """
        if not self._is_initialized or self._db_conn is None:
            return None
        if not StringUtils.is_hash_eligible(source_text):
            return None

        normalized_source: str = StringUtils.normalize_text(source_text)

        try:
            async with self._lock:
                cursor: sqlite3.Cursor = self._db_conn.execute(
                    """
                    SELECT normalized_source, detected_lang, confidence,
                           created_at, last_used_at
                    FROM language_detection_cache
                    WHERE normalized_source = ?
                    """,
                    (normalized_source,),
                )
                row = cursor.fetchone()

                if row is None:
                    logger.debug("Language detection cache miss")
                    return None

                entry = LanguageDetectionCacheEntry(
                    normalized_source=row[0],
                    detected_lang=row[1],
                    confidence=row[2],
                    created_at=self._epoch_to_datetime(row[3]),
                    last_used_at=self._epoch_to_datetime(row[4]),
                )

                cutoff: datetime = datetime.now().astimezone() - timedelta(days=self.TTL_LANGUAGE_DETECTION_DAYS)
                if entry.last_used_at < cutoff:
                    self._db_conn.execute(
                        "DELETE FROM language_detection_cache WHERE normalized_source = ?",
                        (normalized_source,),
                    )
                    self._db_conn.commit()
                    logger.debug("Language detection cache entry expired")
                    return None

                now_epoch: int = self._now_epoch()
                self._db_conn.execute(
                    "UPDATE language_detection_cache SET last_used_at = ? WHERE normalized_source = ?",
                    (now_epoch, normalized_source),
                )
                self._db_conn.commit()

                entry.last_used_at = self._epoch_to_datetime(now_epoch)

                logger.debug("Language detection cache hit")

        except sqlite3.Error as err:
            logger.error("Error searching language detection cache: %s", err)
            return None
        else:
            return entry

    async def register_language_detection_cache(
        self, source_text: str, detected_lang: str, confidence: float = 1.0
    ) -> bool:
        """Register language detection result to cache.

        Args:
            source_text (str): Source text.
            detected_lang (str): Detected language code.
            confidence (float): Detection confidence (0.0 to 1.0).

        Returns:
            bool: True if registration succeeded, False otherwise.
        """
        if not self._is_initialized or self._db_conn is None:
            return False
        if not StringUtils.is_hash_eligible(source_text):
            return False

        normalized_source: str = StringUtils.normalize_text(source_text)

        try:
            async with self._lock:
                now_epoch: int = self._now_epoch()
                self._db_conn.execute(
                    """
                    INSERT OR REPLACE INTO language_detection_cache
                    (normalized_source, detected_lang, confidence, created_at, last_used_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (normalized_source, detected_lang, confidence, now_epoch, now_epoch),
                )
                self._db_conn.commit()

            logger.debug("Language detection cached: %s", detected_lang)

        except sqlite3.Error as err:
            logger.error("Error registering language detection cache: %s", err)
            return False
        else:
            return True

    async def get_cache_statistics(self) -> CacheStatistics:
        """Get cache statistics.

        Returns:
            CacheStatistics: Cache statistics data.
        """
        if not self._is_initialized or self._db_conn is None:
            return CacheStatistics()

        try:
            async with self._lock:
                cursor: sqlite3.Cursor = self._db_conn.execute("SELECT COUNT(*), SUM(hit_count) FROM translation_cache")
                row = cursor.fetchone()
                total_entries: int = row[0] or 0
                total_hits: int = row[1] or 0

                cursor = self._db_conn.execute("SELECT hit_count, COUNT(*) FROM translation_cache GROUP BY hit_count")
                hit_distribution: dict[int, int] = {row[0]: row[1] for row in cursor.fetchall()}

                cursor = self._db_conn.execute("SELECT engine, COUNT(*) FROM translation_cache GROUP BY engine")
                engine_distribution: dict[str, int] = {row[0]: row[1] for row in cursor.fetchall()}

                cursor = self._db_conn.execute(
                    "SELECT MIN(CAST(created_at AS INTEGER)), MAX(CAST(created_at AS INTEGER)) FROM translation_cache"
                )
                row = cursor.fetchone()
                oldest_entry: datetime | None = self._epoch_to_datetime(row[0]) if row[0] else None
                newest_entry: datetime | None = self._epoch_to_datetime(row[1]) if row[1] else None

            return CacheStatistics(
                total_entries=total_entries,
                total_hits=total_hits,
                hit_distribution=hit_distribution,
                engine_distribution=engine_distribution,
                oldest_entry=oldest_entry,
                newest_entry=newest_entry,
            )

        except sqlite3.Error as err:
            logger.error("Error getting cache statistics: %s", err)
            return CacheStatistics()

    async def export_cache_detailed(self, output_path: Path) -> bool:
        """Export detailed cache data to file sorted by hit count.

        Args:
            output_path (Path): Output file path.

        Returns:
            bool: True if export succeeded, False otherwise.
        """
        if not self._is_initialized or self._db_conn is None:
            logger.error("Cache not initialized, cannot export")
            return False

        try:
            async with self._lock:
                cursor: sqlite3.Cursor = self._db_conn.execute(
                    """
                    SELECT cache_key, normalized_source, source_lang, target_lang,
                           translation_text, engine, hit_count, last_used_at
                    FROM translation_cache
                      ORDER BY hit_count DESC, CAST(last_used_at AS INTEGER) DESC
                    """
                )
                rows = cursor.fetchall()

            with output_path.open("w", encoding="utf-8") as f:
                f.write("Translation Cache Detailed Export\n")
                f.write("=" * 80 + "\n\n")

                for row in rows:
                    last_used_dt: str = self._epoch_to_datetime(row[7]).isoformat()
                    f.write(
                        f'{row[2]} -> {row[3]}, "{row[1]}", "{row[4]}", Engine: {row[5]}, Hit Count: {row[6]},'
                        f" Last Used: {last_used_dt}, Cache Key: {row[0]}\n"
                    )

            logger.info("Cache data exported to: %s", output_path)

        except Exception as err:
            logger.error("Error exporting cache data: %s", err)
            return False
        else:
            return True

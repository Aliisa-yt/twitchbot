"""Models for translation cache data.

Defines data classes for translation cache entries, language detection cache, and cache statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__: list[str] = [
    "CacheStatistics",
    "LanguageDetectionCacheEntry",
    "TranslationCacheEntry",
]


@dataclass
class TranslationCacheEntry:
    """Translation cache entry data.

    Attributes:
        cache_key (str): Cache key identifier (hash of normalized data).
        normalized_source (str): Normalized source text.
        source_lang (str): Source language code.
        target_lang (str): Target language code.
        translation_text (str): Translated text.
        translation_profile (str): Translation style identifier (optional).
        engine (str): Translation engine name.
        created_at (datetime): Entry creation timestamp.
        last_used_at (datetime): Last usage timestamp.
        hit_count (int): Number of cache hits.
    """

    cache_key: str
    normalized_source: str
    source_lang: str
    target_lang: str
    translation_text: str
    translation_profile: str
    engine: str
    created_at: datetime
    last_used_at: datetime
    hit_count: int


@dataclass
class LanguageDetectionCacheEntry:
    """Language detection cache entry data.

    Attributes:
        normalized_source (str): Normalized source text.
        detected_lang (str): Detected language code.
        confidence (float): Detection confidence score (0.0 to 1.0).
        created_at (datetime): Entry creation timestamp.
        last_used_at (datetime): Last usage timestamp.
    """

    normalized_source: str
    detected_lang: str
    confidence: float
    created_at: datetime
    last_used_at: datetime


@dataclass
class CacheStatistics:
    """Cache usage statistics.

    Attributes:
        total_entries (int): Total number of cache entries.
        total_hits (int): Total cache hits across all entries.
        hit_distribution (dict[int, int]): Distribution of entries by hit count (hit_count -> count).
        engine_distribution (dict[str, int]): Distribution of entries by engine (engine -> count).
        oldest_entry (datetime | None): Timestamp of oldest entry.
        newest_entry (datetime | None): Timestamp of newest entry.
    """

    total_entries: int = 0
    total_hits: int = 0
    hit_distribution: dict[int, int] = field(default_factory=dict)
    engine_distribution: dict[str, int] = field(default_factory=dict)
    oldest_entry: datetime | None = None
    newest_entry: datetime | None = None

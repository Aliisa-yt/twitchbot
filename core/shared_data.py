"""Shared data management for bot components.

This module defines the SharedData class, which serves as a centralized container for shared resources and services
used across different bot components. It provides properties for accessing configuration, translation cache management,
translation services, text-to-speech services, and in-flight translation request management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.cache.inflight_manager import InFlightManager
from core.cache.manager import TranslationCacheManager
from core.trans.manager import TransManager
from core.tts.manager import TTSManager

if TYPE_CHECKING:
    from config.loader import Config


__all__: list[str] = ["SharedData"]


@dataclass
class SharedData:
    _config: Config = field()
    _cache_manager: TranslationCacheManager = field(init=False)
    _trans_manager: TransManager = field(init=False)
    _tts_manager: TTSManager = field(init=False)
    _inflight_manager: InFlightManager = field(init=False)

    async def async_init(self) -> None:
        self._cache_manager = TranslationCacheManager(self.config)
        self._inflight_manager = InFlightManager()
        self._trans_manager = TransManager(self.config, self._cache_manager, self._inflight_manager)
        self._tts_manager = TTSManager(self.config)

    @property
    def config(self) -> Config:
        return self._config

    @property
    def cache_manager(self) -> TranslationCacheManager:
        return self._cache_manager

    @property
    def trans_manager(self) -> TransManager:
        return self._trans_manager

    @property
    def tts_manager(self) -> TTSManager:
        return self._tts_manager

    @property
    def inflight_manager(self) -> InFlightManager:
        return self._inflight_manager

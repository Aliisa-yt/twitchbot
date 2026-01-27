"""Shared data management for bot components.

This module provides centralized access to translation and text-to-speech managers
that are shared across all bot components. SharedData coordinates the initialization
and lifecycle of these managers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.trans.manager import TransManager
from core.tts.manager import TTSManager

if TYPE_CHECKING:
    from config.loader import Config


__all__: list[str] = ["SharedData"]


@dataclass
class SharedData:
    _config: Config = field()
    _trans_manager: TransManager = field(init=False)
    _tts_manager: TTSManager = field(init=False)

    async def async_init(self) -> None:
        self._trans_manager = TransManager(self.config)
        self._tts_manager = TTSManager(self.config)

    @property
    def config(self) -> Config:
        return self._config

    @property
    def trans_manager(self) -> TransManager:
        return self._trans_manager

    @property
    def tts_manager(self) -> TTSManager:
        return self._tts_manager

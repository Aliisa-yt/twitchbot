"""CeVIO CS7 text-to-speech engine implementation.

This module provides a TTS interface implementation for CeVIO Creative Studio 7 (CS7)
speech synthesis. CeVIO CS7 is a Windows-based voice synthesis software with advanced
voice customization capabilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.tts.engines.cevio_core import CevioCore
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["CevioCS7"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class CevioCS7(CevioCore):
    def __init__(self) -> None:
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__(cevio_type="CS7")

    @staticmethod
    def fetch_engine_name() -> str:
        return "cevio_cs7"

    # def initialize_engine(self, tts_engine: TTSEngine) -> bool:
    #     super().initialize_engine(tts_engine)
    #     return True

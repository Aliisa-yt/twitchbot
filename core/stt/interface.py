"""STT interface definitions and common models.

This module defines shared data structures, exceptions, and the abstract interface used by
all STT engine implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from config.loader import Config

__all__: list[str] = [
    "STTExceptionError",
    "STTInput",
    "STTInterface",
    "STTNonRetriableError",
    "STTNotAvailableError",
    "STTResult",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


@dataclass(frozen=True)
class STTInput:
    """Input metadata passed to STT engines.

    Attributes:
        audio_path (Path): Path to temporary PCM audio file.
        language (str): STT language code such as ja-JP.
        sample_rate (int): Sample rate in Hz.
        channels (int): Number of channels.
    """

    audio_path: Path
    language: str
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class STTResult:
    """STT output result.

    Attributes:
        text (str): Transcribed text.
        language (str | None): Detected or configured language code.
        confidence (float | None): Confidence score if provided by engine.
        metadata (dict[str, str] | None): Optional engine-specific metadata.
    """

    text: str
    language: str | None = None
    confidence: float | None = None
    metadata: dict[str, str] | None = None


class STTExceptionError(Exception):
    """Base class for STT-related exceptions."""


class STTNotAvailableError(STTExceptionError):
    """Raised when STT engine is not available."""


class STTNonRetriableError(STTExceptionError):
    """Raised when retrying an STT request is not expected to recover."""


class STTInterface(ABC):
    """Abstract base class for STT engines.

    Subclasses are auto-registered by engine name.
    """

    registered: ClassVar[dict[str, type[STTInterface]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "fetch_engine_name") or not callable(cls.fetch_engine_name):
            msg = "Subclasses of STTInterface must implement fetch_engine_name()."
            raise TypeError(msg)

        name: str = cls.fetch_engine_name()
        if not name:
            return

        if name in cls.registered:
            msg = f"An STT engine with name '{name}' is already registered."
            raise ValueError(msg)

        cls.registered[name] = cls

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Return whether the engine is available for use."""
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def fetch_engine_name() -> str:
        """Return unique engine name used in configuration."""
        raise NotImplementedError

    @abstractmethod
    def initialize(self, config: Config) -> None:
        """Initialize engine resources from configuration."""
        raise NotImplementedError

    @abstractmethod
    def transcribe(self, stt_input: STTInput) -> STTResult:
        """Transcribe a single audio segment."""
        raise NotImplementedError

"""This module defines the abstract base class for translation interfaces and related exceptions.
It includes the Result data class for translation results, and exceptions for unsupported languages and quota limits.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config
    from models.translation_models import CharacterQuota

__all__: list[str] = [
    "EngineAttributes",
    "NotSupportedLanguagesError",
    "Result",
    "TransInterface",
    "TranslateExceptionError",
    "TranslationQuotaExceededError",
    "TranslationRateLimitError",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)
# logger.addHandler(logging.NullHandler())


@dataclass
class EngineAttributes:
    """Engine-specific capabilities and behavior flags.

    Attributes:
        name (str): Name of translation engine.
            As this name is not used for identification purposes, any name is acceptable.
        supports_dedicated_detection_api (bool): Whether the engine has a dedicated language detection API.
        supports_quota_api (bool): Whether the engine provides an API to check character quota.
    """

    name: str
    supports_dedicated_detection_api: bool = False
    supports_quota_api: bool = False
    # Comments for future expansion:
    # detection_includes_translation: bool = False  # Google/Deepl: True, Google Cloud: False
    # supports_auto_detection: bool = True
    # has_character_limit: bool = False  # Deepl: True, Google/Google Cloud: False


@dataclass
class Result:
    """Data class for translation results.

    Attributes:
        text (str | None): Translated text. None if translation fails.
        detected_source_lang (str | None): Detected source language code. None if detection fails.
        metadata (dict[str, str] | None): Engine-specific metadata (e.g., URL detection, confidence scores).
    """

    text: str | None = None
    detected_source_lang: str | None = None
    metadata: dict[str, str] | None = None

    def __str__(self) -> str:
        if self.text is None:
            return ""
        return self.text

    def __repr__(self) -> str:
        return (
            f"Result(text={self.text!r}, detected_source_lang={self.detected_source_lang!r}, "
            f"metadata={self.metadata!r})"
        )


class TranslateExceptionError(Exception):
    """An error occurred during the translation process."""


class NotSupportedLanguagesError(TranslateExceptionError):
    """An unsupported language code was specified."""


class TranslationQuotaExceededError(TranslateExceptionError):
    """The translatable character quota has been exceeded."""


class TranslationRateLimitError(TranslateExceptionError):
    """The translation request was rate-limited by the API."""


class TransInterface(ABC):
    """Abstract base class for translation interfaces.

    This class defines the interface for translation engines, including methods for initialization,
    language detection, translation, and quota management.
    Subclasses must implement these methods to provide specific translation functionality.

    Attributes:
        registered (ClassVar[dict[str, type[TransInterface]]]): A class variable that holds a dictionary of
            registered translation engine classes, keyed by their distinguished names.
    """

    registered: ClassVar[dict[str, type[TransInterface]]] = {}

    def __init_subclass__(cls, **kwargs) -> None:
        """Register the subclass in the registered dictionary.

        This method is called when a subclass of TransInterface is created.
        Automatically registers the subclass using its distinguished name.

        Args:
            **kwargs: Additional keyword arguments passed to parent class.
        """
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "fetch_engine_name") or not callable(cls.fetch_engine_name):
            msg = "Subclasses of TransInterface must implement the static method fetch_engine_name()."
            raise TypeError(msg)

        if not isinstance(cls.fetch_engine_name(), str) or cls.fetch_engine_name() == "":
            return  # Allow registration of engines with empty names, but they won't be added to the registry.

        if cls.fetch_engine_name() in cls.registered:
            msg: str = f"A translation engine with the name '{cls.fetch_engine_name()}' is already registered."
            raise ValueError(msg)

        cls.registered[cls.fetch_engine_name()] = cls

    def __init__(self) -> None:
        """Initialize the TransInterface base class."""
        self._engine_attributes: EngineAttributes | None = None

    @property
    def engine_attributes(self) -> EngineAttributes:
        """Get the engine attributes.

        Returns:
            EngineAttributes: The engine attributes.
        """
        if self._engine_attributes is None:
            msg = "Engine attributes have not been set."
            raise RuntimeError(msg)
        return self._engine_attributes

    @engine_attributes.setter
    def engine_attributes(self, attributes: EngineAttributes) -> None:
        if self._engine_attributes is not None:
            msg = "Engine attributes can only be set once during initialization."
            raise RuntimeError(msg)
        self._engine_attributes = attributes

    @property
    def engine_name(self) -> str:
        """Get the distinguished name of the translation engine.

        Returns:
            str: The engine name.
        """
        return self.engine_attributes.name

    @property
    def has_dedicated_detection_api(self) -> bool:
        """Check if the engine has a dedicated language detection API.

        Returns:
            bool: True if the engine supports a dedicated detection API, False otherwise.
        """
        return self.engine_attributes.supports_dedicated_detection_api

    @property
    def has_quota_api(self) -> bool:
        """Check if the engine provides an API to check character quota.

        Returns:
            bool: True if the engine supports a quota API, False otherwise.
        """
        return self.engine_attributes.supports_quota_api

    def is_rate_limit_error(self, err: Exception) -> bool:
        """Check if the given exception indicates rate limiting.

        Args:
            err (Exception): Exception raised during translation or detection.

        Returns:
            bool: True if the exception represents rate limiting.
        """
        return isinstance(err, TranslationRateLimitError)

    @property
    @abstractmethod
    def count(self) -> int:
        """Get the number of characters used.

        Note: The value is invalid if get_quota_status() has not been executed.
        Returns 0 if there is no limit.

        Returns:
            int: Number of characters used.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def limit(self) -> int:
        """Get the maximum number of characters available.

        Note: The value is invalid if get_quota_status() has not been executed.
        Returns 500000 if there is no limit.

        Returns:
            int: Maximum number of characters available.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def limit_reached(self) -> bool:
        """Check if the character limit has been reached.

        Returns:
            bool: True if the character limit has been reached, False otherwise.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the translation engine is available.

        Returns:
            bool: True if the translation engine is available, False otherwise.
        """
        raise NotImplementedError

    @staticmethod
    @abstractmethod
    def fetch_engine_name() -> str:
        """Fetch the distinguished name of the translation engine.

        Must be implemented by subclasses. This method is called during class registration
        in __init_subclass__, so the implementation must be available at subclass definition time.

        Returns:
            str: The distinguished name of the translation engine.
        """
        raise NotImplementedError

    @abstractmethod
    def initialize(self, config: Config) -> None:
        """Initialize the translation engine with the given configuration.

        Args:
            config (Config): Configuration object containing settings for the translation engine.
        """
        raise NotImplementedError

    @abstractmethod
    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        """Detect the language of the input text.

        Some translation engines do not have a dedicated language detection API.
        Instead, they translate to a known target language and extract the detected source language
        from the translation results. Therefore, a target language must be specified.

        Args:
            content (str): Text to analyze for language detection.
            tgt_lang (str): Target language code used for detection.

        Returns:
            Result: Detection result with detected_source_lang populated.

        Raises:
            NotSupportedLanguagesError: If the specified language is not supported.
            TranslateExceptionError: If detection fails.
        """
        raise NotImplementedError

    @abstractmethod
    async def translation(self, content: str, tgt_lang: str, src_lang: str | None = None) -> Result:
        """Translate input text to the target language.

        Args:
            content (str): Text to be translated.
            tgt_lang (str): Target language code.
            src_lang (str | None): Source language code. If None, auto-detect.

        Returns:
            Result: Translation result with translated text.

        Raises:
            NotSupportedLanguagesError: If the specified language is not supported.
            TranslationQuotaExceededError: If the character quota has been exceeded.
            TranslateExceptionError: If translation fails.
            TranslationRateLimitError: If the request is rate-limited by the API.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_quota_status(self) -> CharacterQuota:
        """Retrieve the current character quota status.

        Returns:
            CharacterQuota: Object containing characters_used and characters_limit.

        Raises:
            TranslateExceptionError: If quota retrieval fails.
        """
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """Perform cleanup and shutdown of the translation engine.

        Subclasses should override this method to clean up resources if needed.
        """
        raise NotImplementedError

    def get_authentication_key(self) -> str:
        """Retrieve the authentication key from environment variables.

        The key is retrieved from an environment variable named after the engine's distinguished name,
        with the suffix "_API_OAUTH". For example, if the engine name is "google_translate",
        the variable would be "GOOGLE_TRANSLATE_API_OAUTH".

        Returns:
            str: The authentication key, or an empty string if the environment variable is not set.
        """
        return os.getenv(f"{self.fetch_engine_name().upper()}_API_OAUTH", "")

"""Google Cloud Translation API Basic (v2) implementation.

This module provides a translation interface implementation using Google Cloud Translation API v2.
Requires google-cloud-translate library and proper authentication setup.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from google.api_core.exceptions import BadRequest, GoogleAPIError, TooManyRequests, Unauthorized
from google.auth.credentials import AnonymousCredentials
from google.auth.transport.requests import AuthorizedSession
from google.cloud import translate_v2 as translate

from core.trans.interface import (
    EngineAttributes,
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
    TranslationRateLimitError,
)
from models.translation_models import CharacterQuota
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config

__all__: list[str] = ["GoogleCloudTranslation"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class APIKeySession:
    """Custom HTTP session that appends API key to request URLs."""

    def __init__(self, api_key: str) -> None:
        self.api_key: str = api_key
        self._session: AuthorizedSession = AuthorizedSession(AnonymousCredentials())

    def request(self, method: str, url: str, **kwargs):
        """Make HTTP request with API key appended to URL.

        Args:
            method (str): HTTP method (GET, POST, etc.).
            url (str): Request URL.
            **kwargs: Additional request parameters.

        Returns:
            HTTP response object.
        """
        separator = "&" if "?" in url else "?"
        url_with_key: str = f"{url}{separator}key={self.api_key}"
        return self._session.request(method, url_with_key, **kwargs)


class GoogleCloudTranslation(TransInterface):
    """Google Cloud Translation API Basic (v2) implementation.

    This class provides translation services using Google Cloud Translation API v2.
    Authentication can be done via:
    1. Service account JSON key file (GOOGLE_APPLICATION_CREDENTIALS env var)
    2. API key (GOOGLE_CLOUD_API_OAUTH env var)

    Attributes:
        _inst: Google Cloud Translate client instance.
        _character_count: Accumulated character count for quota tracking.
        _available: Flag indicating if the service is available.
    """

    def __init__(self) -> None:
        """Initialize the Google Cloud Translation engine."""
        super().__init__()
        self.__inst: translate.Client | None = None

    @property
    def _inst(self) -> translate.Client:
        """Get the Google Cloud Translate client instance.

        Returns:
            Google Cloud Translate client instance.

        Raises:
            TranslateExceptionError: If the instance is not initialized.
        """
        if self.__inst is None:
            msg = "The Google Cloud Translate instance is not initialised"
            raise TranslateExceptionError(msg)
        return self.__inst

    @_inst.setter
    def _inst(self, inst: translate.Client | None) -> None:
        """Set the Google Cloud Translate client instance.

        Args:
            inst: Google Cloud Translate client instance or None.
        """
        if inst is not None:
            self.__inst = inst
        else:
            self.__inst = None
        logger.debug("'%s': 'set instance'", self.__class__.__name__)

    @property
    def count(self) -> int:
        return 0

    @property
    def limit(self) -> int:
        return 500000

    @property
    def limit_reached(self) -> bool:
        return False

    @property
    def isavailable(self) -> bool:
        return True

    @staticmethod
    def fetch_engine_name() -> str:
        """Fetch the distinguished name of the translation engine.

        Returns:
            str: Engine name 'google_cloud'.
        """
        return "google_cloud"

    def initialize(self, config: Config) -> None:
        """Initialize the Google Cloud Translation API client.

        Authentication methods:
        1. Service account JSON key: Set GOOGLE_APPLICATION_CREDENTIALS env var
        2. API key: Set GOOGLE_CLOUD_API_OAUTH env var

        Args:
            config (Config): Configuration object (currently unused but kept for interface consistency).

        Raises:
            RuntimeError: If client initialization fails.
            TranslateExceptionError: If authentication fails.
        """
        logger.debug("'%s' Initialization start", self.__class__.__name__)
        _ = config  # Indicate unused

        self.engine_attributes = EngineAttributes(
            name="google_cloud",
            supports_dedicated_detection_api=True,
            supports_quota_api=False,
        )
        try:
            # Try to get API key from environment variable
            api_key: str = self.get_authentication_key()

            if api_key:
                # Use API key authentication via custom HTTP session
                # This approach avoids accessing private members like _connection
                logger.debug("Using API key authentication")

                # Create custom HTTP session that adds API key to all requests
                session: APIKeySession = self._create_api_key_session(api_key)
                self._inst = translate.Client(credentials=AnonymousCredentials(), _http=session)
            else:
                # Use default credentials (service account JSON)
                logger.debug("Using default credentials (GOOGLE_APPLICATION_CREDENTIALS)")
                self._inst = translate.Client()

            # Test the connection by getting supported languages (synchronous)
            self._inst.get_languages()
            logger.info("Google Cloud Translation API connection test successful")

        except ImportError as err:
            logger.critical("google-cloud-translate library not installed: %s", err)
            msg = "google-cloud-translate library is required. Install with: pip install google-cloud-translate"
            raise RuntimeError(msg) from err
        except Unauthorized as err:
            logger.critical("Authentication failed: %s", err)
            msg = (
                "Authentication failed. Please set GOOGLE_APPLICATION_CREDENTIALS "
                "or GOOGLE_CLOUD_API_OAUTH environment variable"
            )
            raise TranslateExceptionError(msg) from err
        except Exception as err:
            logger.critical("Unexpected error during initialization: %s", err)
            msg: str = f"Failed to initialize Google Cloud Translation client: {err}"
            raise RuntimeError(msg) from err

    def _create_api_key_session(self, api_key: str) -> APIKeySession:
        """Create a custom HTTP session that adds API key to all requests.

        Args:
            api_key (str): Google Cloud API key.

        Returns:
            Custom session object with API key injection.
        """
        return APIKeySession(api_key)

    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        """Detect the language of the input text.

        Note: Google Cloud Translation's detect_language only performs detection without translation.
        Therefore, Result.text is set to None. The caller must handle this appropriately.

        Args:
            content (str): Text to analyze for language detection.
            tgt_lang (str): Target language code (unused but required by interface).

        Returns:
            Result: Detection result with detected_source_lang populated and text=None.

        Raises:
            TranslateExceptionError: If detection fails.
        """
        logger.debug("'%s': 'detect language'", self.__class__.__name__)
        _ = tgt_lang  # Indicate unused

        try:
            detection = await asyncio.to_thread(self._inst.detect_language, content)
            logger.debug("Language detection result: %s", detection)

            detected_lang = detection["language"].lower()

            # Update character count for quota tracking
            logger.debug("Detected language: '%s' with confidence: %s", detected_lang, detection.get("confidence"))

            result = Result(
                text=None,
                detected_source_lang=detected_lang,
                metadata={"engine": "google_cloud", "confidence": str(detection.get("confidence"))},
            )

        except TooManyRequests as err:
            logger.error("Google API rate limit during language detection: %s", err)
            msg: str = f"Language detection rate limited: {err}"
            raise TranslationRateLimitError(msg) from err
        except GoogleAPIError as err:
            logger.error("Google API error during language detection: %s", err)
            msg: str = f"Language detection failed: {err}"
            raise TranslateExceptionError(msg) from err
        except Exception as err:
            logger.error("Unexpected error during language detection: %s", err)
            msg: str = f"Language detection failed: {err}"
            raise TranslateExceptionError(msg) from err
        else:
            logger.debug("Detected language: '%s' with confidence: %s", detected_lang, detection.get("confidence"))
            return result

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
            TranslateExceptionError: If translation fails.
        """
        logger.info("'%s': 'start translation'", self.__class__.__name__)
        logger.debug("'content': '%s', 'src_lang': '%s', 'tgt_lang': '%s'", content, src_lang, tgt_lang)

        try:
            # Perform translation
            translation_result = await asyncio.to_thread(
                self._inst.translate, content, target_language=tgt_lang, source_language=src_lang
            )

            # Extract results
            translated_text = translation_result["translatedText"]
            detected_lang = translation_result.get("detectedSourceLanguage", src_lang)
            if detected_lang:
                detected_lang = detected_lang.lower()

            result = Result(
                text=translated_text,
                detected_source_lang=detected_lang,
                metadata={"engine": "google_cloud"},
            )

        except BadRequest as err:
            logger.error("Invalid language code: %s", err)
            msg: str = f"Unsupported language pair (src: '{src_lang}', tgt: '{tgt_lang}'): {err}"
            raise NotSupportedLanguagesError(msg) from err
        except TooManyRequests as err:
            logger.error("Google API rate limit during translation: %s", err)
            msg: str = f"Translation rate limited: {err}"
            raise TranslationRateLimitError(msg) from err
        except GoogleAPIError as err:
            logger.error("Google API error during translation: %s", err)
            msg: str = f"Translation failed: {err}"
            raise TranslateExceptionError(msg) from err
        except Exception as err:
            logger.error("Unexpected error during translation: %s", err)
            msg: str = f"Translation failed: {err}"
            raise TranslateExceptionError(msg) from err
        else:
            logger.info("translation completed (%s > %s)", src_lang or detected_lang, tgt_lang)
            logger.debug("'return': '%s'", result)
            return result

    async def get_quota_status(self) -> CharacterQuota:
        """Retrieve the current character quota status.

        Note: Google Cloud Translation API v2 does not provide a direct API
        to check quota. This returns the local counter only.
        Actual quota usage can be checked in Google Cloud Console.

        Returns:
            CharacterQuota: Object containing local character count and limit, along with quota validity.
        """
        logger.debug("Getting quota status (local counter only)")
        return CharacterQuota(count=self.count, limit=self.limit, is_quota_valid=self.has_quota_api)

    async def close(self) -> None:
        """Perform cleanup and shutdown of the translation engine.

        The Google Cloud Translation client does not require explicit cleanup,
        but we reset the instance to ensure proper state.
        """
        self._inst = None
        logger.info("'%s' process termination", self.__class__.__name__)

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar

from core.trans.engines import (
    DeeplTranslation,  # noqa: F401
    GoogleCloudTranslation,  # noqa: F401
    GoogleTranslation,  # noqa: F401
)
from core.trans.engines.const_google import LANGUAGES
from core.trans.interface import (
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
    TranslationQuotaExceededError,
)
from models.cache_models import TranslationCacheEntry
from models.re_models import ONE_LANGUAGE_DESIGNATION_PATTERN, TWO_LANGUAGE_DESIGNATIONS_PATTERN
from models.translation_models import CharacterQuota
from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config
    from core.cache.inflight_manager import InFlightManager
    from core.cache.manager import TranslationCacheManager
    from models.cache_models import LanguageDetectionCacheEntry, TranslationCacheEntry
    from models.translation_models import TranslationInfo


__all__: list[str] = ["TransManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

ADAPTIVE_LIMITER_ENABLED: bool = True
ADAPTIVE_LIMITER_BASE_COOLDOWN_SEC: float = 1.0
ADAPTIVE_LIMITER_MAX_COOLDOWN_SEC: float = 30.0
ADAPTIVE_LIMITER_RESET_SEC: float = 60.0
ADAPTIVE_LIMITER_LOG_INTERVAL_SEC: float = 5.0


class TransManager:
    """Manager for handling translation engines.

    This class initializes translation engines based on the provided configuration,
    manages the active translation engine, and provides methods for language detection and translation.

    Attributes:
        _trans_engine (ClassVar[list[str]]): List of available translation engine names.
    """

    # Class-level list of available engines; accessed via class methods for command handlers.
    _trans_engine: ClassVar[list[str]] = []

    def __init__(
        self,
        config: Config,
        cache_manager: TranslationCacheManager | None = None,
        inflight_manager: InFlightManager | None = None,
    ) -> None:
        """Initialize the TransManager with the given configuration.

        Args:
            config (Config): The configuration object containing translation engine settings.
            cache_manager (TranslationCacheManager | None): Cache manager for translation caching.
            inflight_manager (InFlightManager | None): In-flight manager for handling concurrent translation requests.
        """
        self.config: Config = config
        self.cache_manager: TranslationCacheManager | None = cache_manager
        self.inflight_manager: InFlightManager | None = inflight_manager
        self._trans_instance: dict[str, TransInterface] = {}
        self._rate_limit_error_count: int = 0
        self._rate_limit_last_error: float = 0.0
        self._rate_limit_until: float = 0.0
        self._rate_limit_last_log: float = 0.0
        logger.debug("Registered translation engines: %s", TransInterface.registered)

    async def initialize(self) -> None:
        """Initialize translation engines based on the configuration."""
        logger.info("TransManager initialization started")

        TransManager._trans_engine.clear()
        for _name in self.config.TRANSLATION.ENGINE:
            _cls: type[TransInterface] | None = TransInterface.registered.get(_name)
            if _cls is None:
                logger.critical("Translation class not found: '%s'", _name)
                continue
            _instance: TransInterface = _cls()
            try:
                # Initialise the translation engine using the configuration and perform authentication if necessary.
                _instance.initialize(self.config)
                self._trans_instance[_name] = _instance
                logger.info("Translation engine initialized: '%s'", _name)
                logger.debug("Engine attributes: %s", _instance.engine_attributes)
                # Output a message to the console
                print(f"Loaded translation engine: {_name}")
                TransManager._trans_engine.append(_name)
            except RuntimeError as err:
                logger.critical("RuntimeError in '%s' translation setup: %s", _name, err)
            except TranslateExceptionError as err:
                logger.critical("Exception in '%s' translation setup: %s", _name, err)

    @classmethod
    def fetch_engine_names(cls) -> list[str]:
        """Get the list of available translation engine names.

        Returns:
            list[str]: List of available translation engine names.
        """
        return cls._trans_engine

    @classmethod
    def update_engine_names(cls, engine_names: list[str]) -> None:
        """Update the list of available translation engine names.

        Args:
            engine_names (list[str]): List of translation engine names to set as available.
        """
        valid: list[str] = [n for n in engine_names if n in TransInterface.registered]
        invalid: list[str] = [n for n in engine_names if n not in TransInterface.registered]
        if invalid:
            logger.warning("Ignoring unregistered translation engines: %s", invalid)
        cls._trans_engine = valid

    @property
    def current_engine_instance(self) -> TransInterface:
        """Get the currently active translation engine.

        If no engine is available, it raises a TranslateExceptionError.

        Returns:
            TransInterface: The currently active translation engine instance.

        Raises:
            TranslateExceptionError: If no translation engines are available or if the current engine is invalid.
        """
        try:
            return self._trans_instance[self.fetch_engine_names()[0]]
        except IndexError as err:
            logger.debug("No available translation engines. Error: %s", err)
            error_message = "No translation engines currently available"
            raise TranslateExceptionError(error_message) from err
        except KeyError as err:
            logger.debug("Invalid translation engine key: %s", err)
            error_message: str = f"Invalid translation engine key: {err}"
            raise TranslateExceptionError(error_message) from err

    def refresh_active_engine_list(self) -> None:
        """Refresh the list of active translation engines.

        This method checks the availability of the current active engine.
        If the engine is unavailable, it removes it from the list of active engines.
        """
        if not self.fetch_engine_names():
            logger.debug("No translation engines configured.")
            return
        try:
            if self.current_engine_instance.is_available:
                return
        except TranslateExceptionError:
            logger.error("No active engine available to refresh, skipping.")
            return

        # Remove the current engine from the list if it is unavailable.
        try:
            engine_list: list[str] = self.fetch_engine_names().copy()
            remove_engine_name: str = engine_list.pop(0)
            logger.error("Translation engine disabled: '%s'", remove_engine_name)
            # Update the translation engines list in the class
            self.update_engine_names(engine_list)
        except IndexError:
            logger.error("No translation engines available after removal attempt.")

    def _rate_limit_blocked(self) -> bool:
        """Check if translation is currently blocked due to rate limiting.

        Returns:
            bool: True if translation is blocked, False otherwise.
        """
        if not ADAPTIVE_LIMITER_ENABLED:
            return False

        now: float = time.monotonic()
        if now < self._rate_limit_until:
            if now - self._rate_limit_last_log >= ADAPTIVE_LIMITER_LOG_INTERVAL_SEC:
                remaining: float = self._rate_limit_until - now
                logger.warning("Translation temporarily throttled (%.1f sec remaining).", remaining)
                self._rate_limit_last_log = now
            return True
        return False

    def _register_rate_limit(self) -> None:
        """Register a rate-limit event and update the cooldown period accordingly."""
        if not ADAPTIVE_LIMITER_ENABLED:
            return

        now: float = time.monotonic()
        if now - self._rate_limit_last_error > ADAPTIVE_LIMITER_RESET_SEC:
            self._rate_limit_error_count = 0

        self._rate_limit_error_count += 1
        self._rate_limit_last_error = now

        backoff: float = ADAPTIVE_LIMITER_BASE_COOLDOWN_SEC * (2 ** (self._rate_limit_error_count - 1))
        backoff = min(backoff, ADAPTIVE_LIMITER_MAX_COOLDOWN_SEC)

        self._rate_limit_until = max(self._rate_limit_until, now + backoff)

    def _handle_rate_limit_error(self, trans_info: TranslationInfo, err: TranslateExceptionError) -> bool:
        """Handle rate-limit errors based on the active engine classification.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the engine instance.
            err (TranslateExceptionError): Translation error raised by the engine.

        Returns:
            bool: True if the error is classified as rate limiting.
        """
        try:
            is_rate_limited: bool = trans_info.engine.is_rate_limit_error(err)
        except TranslateExceptionError:
            logger.error("No active engine available for rate-limit classification.")
            return False

        if is_rate_limited:
            self._register_rate_limit()
            logger.warning("Translation rate limit detected: %s", err)
            return True
        return False

    async def detect_language(self, trans_info: TranslationInfo) -> bool:  # noqa: C901, PLR0911
        """Detect the language of the content and set language information.

        This method uses the active translation engine to detect the language of the content.
        If the content is empty, the method returns False without setting any language information.
        When content exists, it sets the source language and preliminary translation text in the trans_info object.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content to analyze.

        Returns:
            bool: True if language detection was successful, False otherwise.
        """
        logger.debug("Language detection started. Content: '%s'", trans_info.content)

        # Empty content indicates that either the message was empty after preprocessing,
        # or no meaningful text remains (e.g., only emotes, or removed by filters).
        # In such cases, return False to indicate detection was not performed.
        if not trans_info.content:
            logger.debug("Content is empty after preprocessing.")
            return False

        if await self.fetch_language_detection_cache(trans_info):
            logger.debug("Language detection cache hit: '%s'", trans_info.src_lang)
            return trans_info.is_translate

        if self._rate_limit_blocked():
            return False

        try:
            result: Result = await trans_info.engine.detect_language(
                content=trans_info.content, tgt_lang=self.config.TRANSLATION.SECOND_LANGUAGE
            )
            src_lang: str | None = result.detected_source_lang

            # Twitch treats URL-like strings as URLs (e.g., "test.py" becomes "http://test.py").
            # Google Cloud returns "und" (undetermined) for URLs; Google follows this convention.
            # Deepl treats URLs as plain text and returns a language code.
            if src_lang == "und":
                # Currently, "und" is only returned in the URL,
                # so we assign "en" as the language code and skip translation.
                logger.info("Unverifiable content. Assigned language: 'en'.")
                trans_info.src_lang = "en"
                trans_info.tgt_lang = "en"
                trans_info.translated_text = trans_info.content
                trans_info.is_translate = False
            elif src_lang is None:
                # Detection should always return a language code; None indicates an error.
                msg = "An unknown error occurred during language detection."
                raise TranslateExceptionError(msg)
            else:
                trans_info.src_lang = src_lang
                # Engines without dedicated detection API return translated text during detection.
                if not trans_info.engine.has_dedicated_detection_api:
                    trans_info.translated_text = StringUtils.ensure_str(result.text)

                await self.write_language_detection_cache(trans_info)

        except TranslationQuotaExceededError as err:
            logger.error("Translation quota exceeded: %s", err)
            return False
        except NotSupportedLanguagesError as err:
            logger.error("Language detection failed: %s", err)
            return False
        except TranslateExceptionError as err:
            if not self._handle_rate_limit_error(trans_info, err):
                logger.error("Language detection failed: %s", err)
            return False

        logger.debug("Final detected language: '%s'", trans_info.src_lang)
        return trans_info.is_translate

    async def fetch_language_detection_cache(self, trans_info: TranslationInfo) -> bool:
        """Fetch the detected language from the cache if caching is enabled.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content to analyze.

        Returns:
            bool: True if the language was fetched from the cache, False otherwise.
        """
        if self.cache_manager is not None:
            cached_detection: (
                LanguageDetectionCacheEntry | None
            ) = await self.cache_manager.search_language_detection_cache(trans_info.content)
            if cached_detection is not None:
                trans_info.src_lang = cached_detection.detected_lang
                return trans_info.is_translate
        return False

    async def write_language_detection_cache(self, trans_info: TranslationInfo) -> None:
        """Write the detected language to the cache if caching is enabled.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content to analyze.
        """
        if self.cache_manager is not None and trans_info.src_lang:
            await self.cache_manager.register_language_detection_cache(trans_info.content, trans_info.src_lang)

    @staticmethod
    def _build_translation_hash_key(trans_info: TranslationInfo) -> str | None:
        """Build a hash key for inflight translation coordination.

        Args:
            trans_info (TranslationInfo): Translation parameters containing content and language pair.

        Returns:
            str | None: Hash key if source/target language is available, otherwise None.
        """
        if not trans_info.src_lang or not trans_info.tgt_lang:
            return None

        return StringUtils.generate_translation_hash_key(
            source_text=trans_info.content,
            source_lang=trans_info.src_lang,
            target_lang=trans_info.tgt_lang,
            engine=trans_info.engine.engine_name,
        )

    async def _try_reuse_inflight_translation(self, trans_info: TranslationInfo, hash_key: str | None) -> bool | None:
        """Try to reuse an in-flight translation result.

        Args:
            trans_info (TranslationInfo): Translation parameters to populate on success.
            hash_key (str | None): Inflight hash key.

        Returns:
            bool | None: True if reused successfully, False if inflight handling failed, None if caller should continue.
        """
        if self.inflight_manager is None or hash_key is None:
            return None

        try:
            started: Result | None = await self.inflight_manager.mark_inflight_start(hash_key)
        except TimeoutError:
            logger.warning("In-flight translation timeout for key: %s", hash_key[:16])
            trans_info.translated_text = ""
            return False
        except TranslateExceptionError as err:
            return self._handle_translation_failure(trans_info, err, context="In-flight translation")

        if started is None:
            return None

        trans_info.translated_text = StringUtils.ensure_str(started.text)
        logger.debug("Received in-flight translation result: '%s'", trans_info.translated_text[:50])
        return True

    async def _store_inflight_result(self, hash_key: str | None, result: Result) -> None:
        """Store completed translation result for in-flight waiters."""
        if self.inflight_manager is not None and hash_key is not None:
            await self.inflight_manager.store_inflight_result(hash_key, result)

    async def _store_inflight_exception(self, hash_key: str | None, err: Exception) -> None:
        """Store translation exception for in-flight waiters."""
        if self.inflight_manager is not None and hash_key is not None:
            await self.inflight_manager.store_inflight_exception(hash_key, err)

    def _handle_translation_failure(self, trans_info: TranslationInfo, err: Exception, *, context: str) -> bool:
        """Handle translation-related failures in a single place.

        Args:
            trans_info (TranslationInfo): Translation parameters to update.
            err (Exception): Exception raised during translation or inflight waiting.
            context (str): Context label for logging.

        Returns:
            bool: Always False to indicate failure.
        """
        if isinstance(err, TranslationQuotaExceededError):
            logger.error("%s quota exceeded: %s", context, err)
        elif isinstance(err, NotSupportedLanguagesError):
            logger.error(
                "%s unsupported language pair (src: '%s', tgt: '%s'): %s",
                context,
                trans_info.src_lang,
                trans_info.tgt_lang,
                err,
            )
        elif isinstance(err, TranslateExceptionError):
            if not self._handle_rate_limit_error(trans_info, err):
                logger.error("%s failed: %s", context, err)
        else:
            logger.exception("%s failed with unexpected error.", context)

        trans_info.translated_text = ""
        return False

    async def perform_translation(self, trans_info: TranslationInfo) -> bool:  # noqa: C901, PLR0911, PLR0912
        """Perform translation for the given content.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content to translate.

        Returns:
            bool: True if translation was successful, False otherwise.
        """
        logger.debug("Translation started. Parameters: %s", trans_info)

        if not trans_info.content:
            logger.debug("Empty content, skipping translation.")
            trans_info.translated_text = ""
            return False

        # Reuse translated text from detection if target language matches.
        if trans_info.translated_text and trans_info.tgt_lang == self.config.TRANSLATION.SECOND_LANGUAGE:
            logger.debug("Reusing previous translation, skipping process.")
            return True

        if await self.fetch_cached_translation(trans_info):
            logger.debug("Translation cache hit: '%s'", trans_info.translated_text[:50])
            return True

        if self._rate_limit_blocked():
            trans_info.translated_text = ""
            return False

        hash_key: str | None = self._build_translation_hash_key(trans_info)

        inflight_result: bool | None = await self._try_reuse_inflight_translation(trans_info, hash_key)
        if inflight_result is not None:
            return inflight_result

        try:
            logger.debug(
                "Using translation engine. Source: '%s', Target: '%s'", trans_info.src_lang, trans_info.tgt_lang
            )
            result: Result = await trans_info.engine.translation(
                content=trans_info.content, tgt_lang=trans_info.tgt_lang, src_lang=trans_info.src_lang
            )
            trans_info.translated_text = StringUtils.ensure_str(result.text)
            await self.write_translation_cache(trans_info)
            await self._store_inflight_result(hash_key, result)
        except TranslateExceptionError as err:
            await self._store_inflight_exception(hash_key, err)
            return self._handle_translation_failure(trans_info, err, context="Translation")
        else:
            logger.debug(
                "Final translation result (src: '%s', tgt: '%s'): %s",
                trans_info.src_lang,
                trans_info.tgt_lang,
                trans_info.translated_text[:50],
            )
            return True

    async def fetch_cached_translation(self, trans_info: TranslationInfo) -> bool:
        """Fetch the translation result from the cache if caching is enabled and language information is available.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content and language information.

        Returns:
            bool: True if a cached translation was found and set, False otherwise.
        """
        if self.cache_manager is not None and trans_info.src_lang and trans_info.tgt_lang:
            cached_translation: TranslationCacheEntry | None = await self.cache_manager.search_translation_cache(
                source_text=trans_info.content,
                source_lang=trans_info.src_lang,
                target_lang=trans_info.tgt_lang,
                engine=trans_info.engine.engine_name,
            )
            if cached_translation is not None:
                trans_info.translated_text = cached_translation.translation_text
                return True
        return False

    async def write_translation_cache(self, trans_info: TranslationInfo) -> bool:
        """Write the translation result to the cache if caching is enabled and language information is available.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content and language information.

        Returns:
            bool: True if the engine-specific cache registration succeeded, False otherwise.
        """
        if self.cache_manager is not None and trans_info.src_lang and trans_info.tgt_lang:
            # Register the translation result in the cache for future reuse.
            success: bool = await self.cache_manager.register_translation_cache(
                source_text=trans_info.content,
                source_lang=trans_info.src_lang,
                target_lang=trans_info.tgt_lang,
                translation_text=trans_info.translated_text,
                engine=trans_info.engine.engine_name,
            )
            # Register the translation result in the cache for shared use (engine name is empty)
            await self.cache_manager.register_translation_cache(
                source_text=trans_info.content,
                source_lang=trans_info.src_lang,
                target_lang=trans_info.tgt_lang,
                translation_text=trans_info.translated_text,
                engine="",
            )
            return success
        return False

    @staticmethod
    def parse_language_prefix(trans_info: TranslationInfo) -> bool:
        """Extract forced language codes from the content of translation parameters.

        Checks for patterns like "en:ja:" or "ja:" in the content and sets the source and/or
        target language codes accordingly.

        Syntax examples:
            "en:ja:This is a test."  # sets src_lang to 'en' and tgt_lang to 'ja'
            "ja:This is a test."     # sets tgt_lang to 'ja'

        Args:
            trans_info (TranslationInfo): Translation parameters containing the content to analyze.
        Returns:
            bool: True if language codes were successfully extracted, False otherwise.
        """

        def validate_language_code(lang: str) -> str | None:
            """Validate if the given language string matches a known language code."""
            for code in LANGUAGES:
                if lang.lower() == code.lower():
                    return code
            return None

        def remove_pattern_from_content(content: str, match_start: int, match_end: int) -> str:
            """Remove matched pattern from content and compress blanks."""
            return StringUtils.compress_blanks(StringUtils.replace_blanks(content, match_start, match_end))

        content: str = trans_info.content
        logger.debug("Extracting forced language codes from content: '%s'", content)

        if not content:
            logger.debug("No content to process for language extraction.")
            return False

        # Check for two-language pattern (e.g., "en->ja")
        if match := TWO_LANGUAGE_DESIGNATIONS_PATTERN.search(content):
            code1: str | None = validate_language_code(match.group("lang1"))
            code2: str | None = validate_language_code(match.group("lang2"))
            if code1 and code2:
                trans_info.src_lang = code1
                trans_info.tgt_lang = code2
                trans_info.content = remove_pattern_from_content(content, match.start(), match.end())
                logger.debug("Extracted languages - Source: '%s', Target: '%s'", code1, code2)
                return True

        # Check for single-language pattern (e.g., "->ja")
        if (match := ONE_LANGUAGE_DESIGNATION_PATTERN.search(content)) and (
            code := validate_language_code(match.group("lang"))
        ):
            trans_info.tgt_lang = code
            trans_info.content = remove_pattern_from_content(content, match.start(), match.end())
            logger.debug("Extracted target language: '%s'", code)
            return True

        logger.debug("No forced language code found")
        return False

    def determine_target_language(self, trans_info: TranslationInfo) -> bool:
        """Determine the target language for translation based on the source language and configuration.

        Args:
            trans_info (TranslationInfo): Translation parameters containing the source language.

        Returns:
            bool: True if the target language is set and different from the source language, False otherwise.
        """
        logger.debug("Processing translation parameters: %s", trans_info)

        if trans_info.tgt_lang:
            # If the target language is already set, no need to change it.
            logger.debug("Target language already set: '%s'", trans_info.tgt_lang)
            return True

        # ignore_langs: list[str] = self.config.TRANSLATION.IGNORE_LANGUAGE
        native_lang: str = self.config.TRANSLATION.NATIVE_LANGUAGE
        second_lang: str = self.config.TRANSLATION.SECOND_LANGUAGE

        if trans_info.src_lang != native_lang:
            logger.debug("Setting target language to native language: '%s'", native_lang)
            trans_info.tgt_lang = native_lang
        else:
            logger.debug("Source is native language, setting target to second language: '%s'", second_lang)
            trans_info.tgt_lang = second_lang

        logger.debug("Final target language selected: '%s'", trans_info.tgt_lang)
        logger.debug("Translation required: %s", trans_info.is_translate)
        return trans_info.is_translate

    async def get_usage(self) -> CharacterQuota:
        """Get the usage statistics of the active translation engine.

        Returns:
            CharacterQuota: An object containing the count of characters used and the limit, along with quota validity.
        """
        try:
            return await self.current_engine_instance.get_quota_status()
        except TranslateExceptionError as err:
            logger.error(err)
            return CharacterQuota(count=0, limit=0, is_quota_valid=False)

    async def shutdown_engines(self) -> None:
        """Shut down all active translation engines."""
        logger.info("Class '%s' termination process started.", self.__class__.__name__)
        for _inst in self._trans_instance.values():
            await _inst.close()
        logger.info("Class '%s' termination process completed.", self.__class__.__name__)

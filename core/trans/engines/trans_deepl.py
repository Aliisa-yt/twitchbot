from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, ClassVar

from deepl import DeepLClient, Language, TextResult, Usage
from deepl.exceptions import (
    AuthorizationException,
    ConnectionException,
    DeepLException,
    QuotaExceededException,
    TooManyRequestsException,
)

from core.trans.interface import (
    EngineAttributes,
    NotSupportedLanguagesError,
    Result,
    TransInterface,
    TranslateExceptionError,
    TranslationQuotaExceededError,
    TranslationRateLimitError,
)
from models.translation_models import CharacterQuota
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from config.loader import Config


__all__: list[str] = ["DeeplTranslation"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class DeeplTranslation(TransInterface):
    _source_codes: ClassVar[dict[str, str]] = {}  # Mapping of source language codes to DeepL's format
    _target_codes: ClassVar[dict[str, str]] = {}  # Mapping of target language codes to DeepL's format

    def __init__(self) -> None:
        super().__init__()
        self.__inst: DeepLClient | None = None
        self.__usage: Usage | None = None
        self.__available: bool = False
        self._generate_langcode_mappings()

    def _generate_langcode_mappings(self) -> None:
        """Generate language code mappings for DeepL source and target codes.

        This method populates the _source_codes and _target_codes class variables
        with mappings from the Language constants provided by the DeepL library.
        It maps the first two characters of each language code to DeepL's format,
        ensuring that the codes are in uppercase as required by DeepL.
        It also handles specific cases for Chinese language variations.
        """
        language_constants: dict[str, str] = self._get_language_constants(Language)

        for code in language_constants.values():
            # Normalize code to base form (e.g., 'en-US' -> 'en')
            base_code: str = code.split("-")[0].lower()
            DeeplTranslation._source_codes[base_code] = base_code.upper()
            DeeplTranslation._target_codes[base_code] = code.upper()

        # Handle Chinese variations explicitly (DeepL uses unified 'ZH')
        for zh_variant in ("zh-CN", "zh-TW"):
            DeeplTranslation._source_codes[zh_variant] = "ZH"
            DeeplTranslation._target_codes[zh_variant] = "ZH"

        logger.debug("Language code mapping generated for DeepL.")

    def _get_language_constants(self, cls) -> dict[str, str]:
        """Get language constants from the given class.

        This method retrieves all uppercase string constants from the class,
        which are typically used for language codes in DeepL.

        Args:
            cls: The class from which to retrieve language constants.

        Returns:
            A dictionary mapping constant names to their values, where the names are uppercase.
        """
        return {name: value for name, value in vars(cls).items() if isinstance(value, str) and name.isupper()}

    @property
    def _inst(self) -> DeepLClient:
        if self.__inst is None:
            msg = "The DeepL instance is not initialised"
            raise TranslateExceptionError(msg)
        return self.__inst

    @_inst.setter
    def _inst(self, inst: DeepLClient | None) -> None:
        if inst is not None:
            self.__inst = inst
            # self.__available = True
            # Do not unconditionally set 'self.__available' to 'True' when registering an instance.
            # 'self.__available' will be set to 'True' if 'self._get_usage()' has not reached its upper limit.
            self._get_usage()
        else:
            self.__inst = None
            self.__available = False
            self.__usage = None
        logger.debug("'%s': 'set instance'", self.__class__.__name__)

    @property
    def _usage(self) -> Usage:
        if self.__usage is None:
            msg = "The DeepL Usage instance is not initialised"
            raise TranslateExceptionError(msg)
        return self.__usage

    @_usage.setter
    def _usage(self, usage: Usage | None) -> None:
        if usage is not None:
            self.__usage = usage
        else:
            self.__usage = None
        logger.debug("'%s': 'set usage'", self.__class__.__name__)

    @property
    def count(self) -> int:
        if self._usage.character.count:
            return self._usage.character.count
        return 0

    @property
    def limit(self) -> int:
        if self._usage.character.limit:
            return self._usage.character.limit
        return 500000

    @property
    def limit_reached(self) -> bool:
        return self._usage.character.limit_reached

    @property
    def isavailable(self) -> bool:
        return self.__available

    @staticmethod
    def fetch_engine_name() -> str:
        return "deepl"

    def initialize(self, config: Config) -> None:
        """Initializes the DeepL translation client with the provided configuration.

        Args:
            config (Config): The configuration object containing the authentication key.

        Raises:
            RuntimeError: If an error occurs during the initialization of the DeepL client.
            TranslateExceptionError: If authorization fails or if the authentication key is invalid.
        """
        logger.debug("'%s' Initialization start", self.__class__.__name__)
        _ = config  # Indicate unused.

        self.engine_attributes = EngineAttributes(
            name="deepl",
            supports_dedicated_detection_api=False,
            supports_quota_api=True,
        )
        try:
            # Create an instance of DeepLClient with the authentication key.
            # Authentication occurs when the API is used, rather than when the instance is created.
            # Therefore, the validity of the authentication key is verified via the API.
            self._inst = DeepLClient(self.get_authentication_key())
        except (AttributeError, ValueError) as err:
            logger.critical(err)
            msg = "An error occurred while creating the DeepL client instance"
            raise RuntimeError(msg) from err
        except AuthorizationException:
            self._inst = None
            msg = "Authorisation failed. Please check your authentication key"
            raise TranslateExceptionError(msg) from None

    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        """Detects the language of the given content using DeepL.

        Args:
            content (str): The text content for which the language needs to be detected.
            tgt_lang (str): The target language code for the translation.

        Returns:
            Result: A Result object containing the detected source language and the original text.

        Raises:
            NotSupportedLanguagesError: If the specified target language is not supported by DeepL.
            TranslationQuotaExceededError: If the translation quota has been exceeded.
            TranslateExceptionError: If an error occurs during the detection process.
        """
        result: Result = await self.translation(content, tgt_lang=tgt_lang)
        logger.debug("Detected language: '%s'", result.detected_source_lang)
        return result

    async def translation(self, content: str, tgt_lang: str, src_lang: str | None = None) -> Result:
        """Translates the given content from source language to target language using DeepL.

        Args:
            content (str): The text content to be translated.
            tgt_lang (str): The target language code for the translation.
            src_lang (str | None): The source language code for the translation.
                                   If None, DeepL will attempt to detect it.

        Returns:
            Result: A Result object containing the translated text and detected source language.

        Raises:
            NotSupportedLanguagesError: If the specified languages are not supported by DeepL.
            TranslationQuotaExceededError: If the translation quota has been exceeded.
            TranslateExceptionError: If an error occurs during the translation process.
        """
        logger.debug("'content': '%s', 'src_lang': '%s', 'tgt_lang': '%s'", content, src_lang, tgt_lang)
        try:
            _src_lang: str | None = (
                DeeplTranslation._source_codes[src_lang] if src_lang else None
            )  # When empty, it is set to 'None'.
            _tgt_lang: str = DeeplTranslation._target_codes[tgt_lang]
        except KeyError:
            msg: str = (
                f"Languages not supported by DeepL. Source language: '{src_lang}'. Target language: '{tgt_lang}'."
            )
            raise NotSupportedLanguagesError(msg) from None

        try:
            results: TextResult | list[TextResult] = await asyncio.to_thread(
                self._inst.translate_text,
                content,
                source_lang=_src_lang,
                target_lang=_tgt_lang,
            )

            logger.info("translation completed (%s > %s)", _src_lang, _tgt_lang)
            return self._build_result(results)

        except QuotaExceededException as err:
            self.__available = False
            raise TranslationQuotaExceededError(err) from None
        except AuthorizationException:
            msg = "Authorisation failed. Please check your authentication key"
            raise TranslateExceptionError(msg) from None
        except TooManyRequestsException as err:
            msg = "DeepL rate limit reached"
            raise TranslationRateLimitError(msg) from err
        except ConnectionException:
            msg = "An error occurred when connecting to the DeepL server"
            raise TranslateExceptionError(msg) from None
        except DeepLException:
            msg = "An anomaly occurred during the translation process at DeepL"
            raise TranslateExceptionError(msg) from None
        except (ValueError, TypeError):
            msg = "An anomaly occurred during the translation process at DeepL"
            raise TranslateExceptionError(msg) from None

    def _build_result(self, results: TextResult | list[TextResult]) -> Result:
        """Builds a Result object from the translation results.

        Args:
            results (TextResult | list[TextResult]):
                The translation results, which can be a single TextResult or a list of TextResults.

        Returns:
            Result: A Result object containing the translated text and detected source language.

        Raises:
            TranslateExceptionError: If the results are not in the expected format or if an error occurs.
        """
        if isinstance(results, TextResult):
            result: TextResult = results
        elif isinstance(results, list):
            # Although this app does not return list types, type checking is performed.
            logger.debug("The return value is of type list.")
            result: TextResult = results[0]
        else:
            msg = "An anomaly occurred during the translation process at DeepL"
            raise TranslateExceptionError(msg) from None

        _result = Result(
            text=result.text,
            detected_source_lang=result.detected_source_lang.lower(),
            metadata={"engine": "deepl"},
        )
        logger.debug("'return': '%s'", _result)
        return _result

    def _get_usage(self) -> None:
        """Fetches the current usage statistics from the DeepL client.

        This method retrieves the usage statistics, including the character count and limit,
        and updates the instance variables accordingly. It also handles exceptions related to
        quota limits and connection issues.

        Raises:
            TranslateExceptionError: If an error occurs while fetching usage statistics.
        """
        try:
            self._usage = self._inst.get_usage()
            self.__available = not self.limit_reached
        except TooManyRequestsException as err:
            msg = "DeepL rate limit reached"
            raise TranslationRateLimitError(msg) from err
        except ConnectionException:
            msg = "An error occurred when connecting to the DeepL server"
            raise TranslateExceptionError(msg) from None
        except AuthorizationException:
            msg = "Authorisation failed. Please check your authentication key"
            raise TranslateExceptionError(msg) from None
        except DeepLException:
            msg = "An anomaly occurred during the translation process at DeepL"
            raise TranslateExceptionError(msg) from None

    async def get_quota_status(self) -> CharacterQuota:
        """Asynchronously retrieves the current character usage quota from DeepL.

        This method fetches the usage statistics, including the current character count and limit,
        and returns a CharacterQuota object containing this information.

        Returns:
            CharacterQuota: An object containing the current character count and limit, along with quota validity.

        Raises:
            TranslateExceptionError: If an error occurs while fetching usage statistics.
        """
        await asyncio.to_thread(self._get_usage)
        return CharacterQuota(count=self.count, limit=self.limit, is_quota_valid=self.has_quota_api)

    async def close(self) -> None:
        """This closes the DeepL client instance and resets the usage statistics.

        This method sets the instance variables to 'None', indicating that the client is no longer available.
        """
        self.__available = False
        self._usage = None
        self._inst = None
        logger.debug("'%s' process termination", self.__class__.__name__)

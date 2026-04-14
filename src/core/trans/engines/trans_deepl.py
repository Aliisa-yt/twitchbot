"""This module implements the DeepL translation engine using the DeepL API.

It provides functionality for translating text, detecting languages, and managing usage quotas.
The implementation includes error handling for various exceptions that may occur during API interactions,
such as authorization failures, quota limits, and connection issues.
"""

import asyncio
from typing import TYPE_CHECKING, ClassVar, Final, Literal, override

from deepl import DeepLClient, Language, TextResult, Usage, version
from deepl.exceptions import (
    AuthorizationException,
    ConnectionException,
    DeepLException,
    QuotaExceededException,
    TooManyRequestsException,
)

from core.trans.trans_interface import (
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

    from models.config_models import Config


__all__: list[str] = ["DeeplTranslation"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

_EXPECTED_DEEPL_VERSION: Final[str] = "1.30.0"

_DEEPL_DEFAULT_CHAR_LIMIT: Final[int] = 500000  # Default character limit for DeepL if not provided by the API

_DEFAULT_SPANISH_CODE: Final[Literal["es", "es-419"]] = "es"
_DEFAULT_ENGLISH_CODE: Final[Literal["en-US", "en-GB"]] = "en-US"
_DEFAULT_PORTUGUESE_CODE: Final[Literal["pt-BR", "pt-PT"]] = "pt-PT"
_DEFAULT_CHINESE_CODE: Final[Literal["zh", "zh-Hans", "zh-Hant"]] = "zh"


class DeeplTranslation(TransInterface):
    _source_codes: ClassVar[dict[str, str]] = {}  # Mapping of source language codes to DeepL's format
    _target_codes: ClassVar[dict[str, str]] = {}  # Mapping of target language codes to DeepL's format

    def __init__(self) -> None:
        super().__init__()
        self.__inst: DeepLClient | None = None
        self.__usage: Usage | None = None
        self.__available: bool = False
        self._generate_langcode_mappings()
        # If regional language codes have been added or changed in an update, it may not function correctly.
        if version.VERSION != _EXPECTED_DEEPL_VERSION:
            logger.warning(
                "The version of the DeepL library is '%s', which may not be compatible with this implementation. "
                "Please ensure you are using version '%s' for optimal performance.",
                version.VERSION,
                _EXPECTED_DEEPL_VERSION,
            )

    @classmethod
    def _generate_langcode_mappings(cls) -> None:  # noqa: C901
        """Generate language code mappings for DeepL source and target codes.

        This method retrieves the mappings from language constants provided by the DeepL library and stores the
        values in the `_source_codes` and `_target_codes` class variables.
        It maps language codes (ISO639-1) to the DeepL format, ensuring the codes are capitalized according to
        DeepL requirements.
        It also handles special processing for Spanish, English, Portuguese, and Chinese, including region codes.

        Special rules for language code handling:
            - For Spanish, if `es` is detected as the source language,
                it is mapped to the language set in `_DEFAULT_SPANISH_CODE` as the target language.
            - For English, if `en` is detected as the source language,
                it is mapped to the language set in `_DEFAULT_ENGLISH_CODE` as the target language.
            - For Portuguese, if `pt` is detected as the source language,
                it is mapped to the language set in `_DEFAULT_PORTUGUESE_CODE` as the target language.
            - For Chinese, if `zh` is detected as the source language,
                it is mapped to the language set in `_DEFAULT_CHINESE_CODE` as the target language,
                and region-specific codes are also processed for both the source and target languages.
        """

        def _get_language_constants(target_cls: type) -> dict[str, str]:
            """Get language constants from the given class.

            This method retrieves all uppercase string constants from the target_cls,
            which are typically used for language codes in DeepL.

            Args:
                target_cls: The class from which to retrieve language constants.

            Returns:
                A dictionary mapping constant names to their values, where the names are uppercase.
            """
            return {
                name: value for name, value in vars(target_cls).items() if isinstance(value, str) and name.isupper()
            }

        if cls._source_codes and cls._target_codes:
            logger.debug("Language code mappings already generated. Skipping regeneration.")
            return

        language_constants: dict[str, str] = _get_language_constants(Language)

        for code in language_constants.values():
            if "-" in code:
                continue  # Skip codes with region specifiers for now; they will be handled separately.
            cls._source_codes[code] = code.upper()
            cls._target_codes[code] = code.upper()

        # Handle special cases for Spanish to ensure they are included in the mappings.
        if cls._source_codes.get("es") is not None:
            cls._target_codes["es"] = _DEFAULT_SPANISH_CODE.upper()

        # Handle special cases for English to ensure they are included in the mappings.
        if cls._source_codes.get("en") is not None:
            cls._target_codes["en"] = _DEFAULT_ENGLISH_CODE.upper()

        # Handle special cases for Portuguese to ensure they are included in the mappings.
        if cls._source_codes.get("pt") is not None:
            cls._target_codes["pt"] = _DEFAULT_PORTUGUESE_CODE.upper()

        # Handle special cases for Chinese to ensure they are included in the mappings.
        if cls._source_codes.get("zh") is not None:
            cls._target_codes["zh"] = _DEFAULT_CHINESE_CODE.upper()

            # Compatibility processing with the language codes used by Google.
            code = language_constants.get("CHINESE_SIMPLIFIED", "").upper()
            if code:
                cls._source_codes["zh-CN"] = "zh".upper()
                cls._target_codes["zh-CN"] = code
            code = language_constants.get("CHINESE_TRADITIONAL", "").upper()
            if code:
                cls._source_codes["zh-TW"] = "zh".upper()
                cls._target_codes["zh-TW"] = code

        logger.debug("Language code mapping generated for DeepL.")

    @property
    def _inst(self) -> DeepLClient:
        if self.__inst is None:
            msg = "The DeepL instance is not initialised"
            raise TranslateExceptionError(msg)
        return self.__inst

    @_inst.setter
    def _inst(self, inst: DeepLClient | None) -> None:
        if isinstance(inst, DeepLClient):
            self.__inst = inst
            # self.__available = True
            # Do not unconditionally set 'self.__available' to 'True' when registering an instance.
            # 'self.__available' will be set to 'True' if 'self._get_usage()' has not reached its upper limit.
            self._get_usage()
            logger.debug("DeepL client instance set successfully.")
        else:
            self.__inst = None
            self.__available = False
            self.__usage = None
            logger.debug(
                "DeepL client instance set to None or invalid type. Availability set to False and usage reset."
            )

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
            usage_str = f"Character count: {usage.character.count} / Character limit: {usage.character.limit}"
        else:
            self.__usage = None
            usage_str = "None"
        logger.debug("%s usage: '%s'", self.__class__.__name__, usage_str)

    @property
    @override
    def count(self) -> int:
        if self._usage.character.count is not None:
            return self._usage.character.count
        return 0

    @property
    @override
    def limit(self) -> int:
        if self._usage.character.limit is not None:
            return self._usage.character.limit
        return _DEEPL_DEFAULT_CHAR_LIMIT

    @property
    @override
    def limit_reached(self) -> bool:
        return self._usage.character.limit_reached

    @property
    @override
    def is_available(self) -> bool:
        return self.__available

    @staticmethod
    @override
    def fetch_engine_name() -> str:
        return "deepl"

    @override
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

        self.engine_attributes: EngineAttributes = EngineAttributes(
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
            # Do not set 'self._inst' to 'None' as this will cause an error in the 'Mypy Type Checker' extension.
            # self._inst = None
            self.__inst = None
            self.__available = False
            self.__usage = None
            msg = "Authorisation failed. Please check your authentication key"
            raise TranslateExceptionError(msg) from None

    @override
    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        """Detects the language of the given content using DeepL.

        Args:
            content (str): The text content for which the language needs to be detected.
            tgt_lang (str): The target language code for the translation.

        Returns:
            Result: A Result object containing the detected source language and the original text.

        Raises:
            NotSupportedLanguagesError: If the specified languages are not supported by DeepL.
            TranslationQuotaExceededError: If the translation quota has been exceeded.
            TranslateExceptionError: If an error occurs during the translation process.
            TranslationRateLimitError: If the DeepL rate limit has been reached.
        """
        result: Result = await self.translation(content, tgt_lang=tgt_lang)
        logger.debug("Detected language: '%s'", result.detected_source_lang)
        return result

    @override
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
            TranslationRateLimitError: If the DeepL rate limit has been reached.
        """
        logger.info("'%s': 'start translation'", self.__class__.__name__)
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
        except ValueError, TypeError:
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
            result = results[0]
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
            TranslationRateLimitError: If the DeepL rate limit has been reached.
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

    @override
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

    @override
    async def close(self) -> None:
        """This closes the DeepL client instance and resets the usage statistics.

        This method sets the instance variables to 'None', indicating that the client is no longer available.
        """
        self.__available = False
        self.__usage = None
        self.__inst = None
        logger.info("'%s' process termination", self.__class__.__name__)

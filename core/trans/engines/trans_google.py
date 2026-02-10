"""Google Translate translation engine implementation.

This module provides a translation interface implementation using Google Translate API
through the async_google_translate library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.trans.engines.async_google_translate import (
    AsyncTranslator,
    GoogleError,
    HTTPConnectionError,
    HTTPError,
    HTTPRedirection,
    HTTPTimeoutError,
    HTTPTooManyRequests,
    InvalidLanguageCodeError,
    ResponseFormatError,
    TextResult,
)
from core.trans.interface import (
    EngineAttributes,
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

__all__: list[str] = ["GoogleTranslation"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class GoogleTranslation(TransInterface):
    def __init__(self) -> None:
        super().__init__()
        self.__inst: AsyncTranslator | None = None

    @property
    def _inst(self) -> AsyncTranslator:
        if self.__inst is None:
            msg = "The google instance is not initialised"
            raise TranslateExceptionError(msg)
        return self.__inst

    @_inst.setter
    def _inst(self, inst: AsyncTranslator | None) -> None:
        if inst is not None:
            self.__inst = inst
        else:
            self.__inst = None
        logger.debug("'%s': 'set instance'", self.__class__.__name__)

    @property
    def count(self) -> int:
        return 0  # The free version of Google has no character limit, meaning it always returns the same value.

    @property
    def limit(self) -> int:
        return 500000  # The free version of Google has no character limit, so it always returns the same value.

    @property
    def limit_reached(self) -> bool:
        return False  # The free version of Google has no character limit, so it always returns the same value.

    @property
    def isavailable(self) -> bool:
        return True  # The free version of Google has no character limit, meaning it always returns the same value.

    @staticmethod
    def fetch_engine_name() -> str:
        return "google"

    def initialize(self, config: Config) -> None:
        logger.debug("'%s' Initialization start", self.__class__.__name__)
        self.engine_attributes = EngineAttributes(
            name="google",
            supports_dedicated_detection_api=False,
            supports_quota_api=False,
        )
        try:
            self._inst = AsyncTranslator(url_suffix=config.TRANSLATION.GOOGLE_SUFFIX)
        except (AttributeError, ValueError) as err:
            logger.critical(err)
            msg = "an error occurred in instance creation"
            raise RuntimeError(msg) from err

    async def detect_language(self, content: str, tgt_lang: str) -> Result:
        logger.debug("'%s': 'detect language'", self.__class__.__name__)
        result: Result = await self.translation(content, tgt_lang=tgt_lang)
        logger.debug("%s", result)
        return result

    async def translation(self, content: str, tgt_lang: str, src_lang: str | None = None) -> Result:
        logger.info("'%s': 'start translation'", self.__class__.__name__)
        logger.debug("'content': '%s', 'src_lang': '%s', 'tgt_lang': '%s'", content, src_lang, tgt_lang)

        try:
            result: TextResult = await self._inst.translate(content, tgt_lang, src_lang)
            logger.info("translation completed (%s > %s)", src_lang, tgt_lang)
            _result = Result(
                text=result.text,
                detected_source_lang=result.detected_source_lang,
                metadata=result.metadata,
            )
            logger.debug("'return': '%s'", _result)
        except (
            InvalidLanguageCodeError,
            ResponseFormatError,
            GoogleError,
            HTTPConnectionError,
            HTTPError,
            HTTPTimeoutError,
            HTTPRedirection,
        ) as err:
            logger.error(err)
            msg = "an anomaly occurred during translation at Google"
            raise TranslateExceptionError(msg) from err
        except HTTPTooManyRequests as err:
            logger.error(err)
            msg = "an anomaly occurred during translation at Google"
            raise TranslationRateLimitError(msg) from err
        return _result

    async def get_quota_status(self) -> CharacterQuota:
        return CharacterQuota(count=self.count, limit=self.limit, is_quota_valid=self.has_quota_api)

    async def close(self) -> None:
        await self._inst.close()
        logger.info("'%s' process termination", self.__class__.__name__)

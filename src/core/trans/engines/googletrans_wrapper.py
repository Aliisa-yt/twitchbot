"""Compatibility wrapper around :mod:`googletrans`.

The application translation engine predates ``googletrans`` and uses a small,
library-independent asynchronous client contract.  This module keeps that
contract stable while isolating googletrans and httpx specific result objects
and exceptions.
"""

import re
from typing import Final, Never, override

import httpx
from googletrans import Translator

from core.trans.engines.const_google import DEFAULT_SERVICE_URLS

__all__: list[str] = [
    "AsyncTranslator",
    "GoogleError",
    "HTTPConnectionError",
    "HTTPError",
    "HTTPRedirection",
    "HTTPTimeoutError",
    "HTTPTooManyRequests",
    "InvalidLanguageCodeError",
    "ResponseFormatError",
    "TextResult",
]

URL_SUFFIX_DEFAULT: Final[str] = "com"
_STATUS_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r'Unexpected status code "(?P<status>\d{3})"')


class GoogleException(Exception):  # noqa: N818
    """Base exception raised by the Google Translate compatibility client."""


class GoogleError(GoogleException):
    """A Google Translate request could not be completed."""


class ResponseFormatError(GoogleException):
    """The response returned by googletrans did not have the expected shape."""


class InvalidLanguageCodeError(GoogleException):
    """A source or target language code is not accepted by Google Translate."""


class HTTPException(GoogleException):
    """Base exception for HTTP failures."""


class HTTPConnectionError(HTTPException):
    """The Google Translate host could not be reached."""


class HTTPTimeoutError(HTTPException):
    """The Google Translate request timed out."""


class HTTPRedirection(HTTPException):
    """Google Translate returned a redirection response."""


class HTTPError(HTTPException):
    """Google Translate returned a non-success HTTP response."""


class HTTPTooManyRequests(HTTPException):
    """Google Translate returned HTTP 429."""


class TextResult:
    """Normalized translation result consumed by :class:`GoogleTranslation`."""

    def __init__(
        self,
        text: str,
        detected_source_lang: str | None,
        *,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.text: str = text
        self.detected_source_lang: str | None = detected_source_lang
        self.metadata: dict[str, str] | None = metadata

    @override
    def __str__(self) -> str:
        return self.text

    @override
    def __repr__(self) -> str:
        return (
            f"<TextResult text={self.text} detected_source_lang={self.detected_source_lang} "
            f"metadata={self.metadata}>"
        )


class AsyncTranslator:
    """Async client exposing the legacy translation-client interface.

    ``googletrans`` defaults to returning fabricated fallback data for request
    failures.  ``raise_exception=True`` is required so failures propagate to
    the application's translation error handling.
    """

    def __init__(self, url_suffix: str = URL_SUFFIX_DEFAULT, timeout: float = 10.0) -> None:
        self.url_suffix: str = self._normalize_url_suffix(url_suffix)
        self.service_url: str = f"translate.google.{self.url_suffix}"
        self._translator: Translator = Translator(
            service_urls=[self.service_url],
            raise_exception=True,
            timeout=httpx.Timeout(timeout),
        )

    @staticmethod
    def _normalize_url_suffix(url_suffix: str) -> str:
        suffixes = {url.removeprefix("translate.google.") for url in DEFAULT_SERVICE_URLS}
        return url_suffix if url_suffix in suffixes else URL_SUFFIX_DEFAULT

    async def translate(self, text: str, lang_tgt: str = "auto", lang_src: str | None = "auto") -> TextResult:
        self._validate_text(text)
        try:
            translated = await self._translator.translate(text, dest=lang_tgt, src=lang_src or "auto")
        except ValueError as err:
            raise InvalidLanguageCodeError(err) from err
        except httpx.TimeoutException as err:
            raise HTTPTimeoutError(err) from err
        except httpx.NetworkError as err:
            raise HTTPConnectionError(err) from err
        except httpx.HTTPStatusError as err:
            self._raise_for_status(err.response.status_code, str(err))
        except httpx.HTTPError as err:
            raise HTTPError(err) from err
        except Exception as err:
            status_match = _STATUS_CODE_PATTERN.search(str(err))
            if status_match is not None:
                self._raise_for_status(int(status_match["status"]), str(err))
            raise GoogleError(err) from err

        translated_text = getattr(translated, "text", None)
        detected_source_lang = getattr(translated, "src", None)
        if not isinstance(translated_text, str) or not isinstance(detected_source_lang, str):
            msg = "googletrans returned an invalid translation result"
            raise ResponseFormatError(msg)
        return TextResult(
            translated_text,
            detected_source_lang,
            metadata={"engine": "google", "service_url": self.service_url},
        )

    async def close(self) -> None:
        await self._translator.client.aclose()

    @staticmethod
    def _validate_text(text: str) -> None:
        if not text:
            msg = "No characters to translate"
            raise GoogleError(msg)
        if len(text) >= 5000:
            msg = "Can only translate less than 5000 characters"
            raise GoogleError(msg)

    @staticmethod
    def _raise_for_status(status: int, message: str) -> Never:
        if status == 429:
            raise HTTPTooManyRequests(message)
        if 300 <= status < 400:
            raise HTTPRedirection(message)
        raise HTTPError(message)

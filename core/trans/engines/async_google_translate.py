"""Modified version of async_google_trans_new

Note:
    Error handling (4xx and 5xx responses) behaviour is unconfirmed
    Response data integrity verification is missing

Original repository:
    https://github.com/sevenc-nanashi/async-google-trans-new
"""

from __future__ import annotations

import json
import logging
import random
import re
from json import JSONDecodeError
from re import Match
from typing import Any, Final
from urllib.parse import quote

import aiohttp

from core.trans.engines.const_google import DEFAULT_SERVICE_URLS, LANGUAGES
from utils.logger_utils import LoggerUtils

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

logger: logging.Logger = LoggerUtils.get_logger(__name__)
logger.addHandler(logging.NullHandler())

URL_SUFFIX_DEFAULT: Final[str] = "com"
URLS_SUFFIX: Final[list[str]] = []

for _url in DEFAULT_SERVICE_URLS:
    _match: Match[str] | None = re.search("translate.google.(.*)", _url.strip())
    if _match is not None:
        URLS_SUFFIX.append(_match.group(1))


class GoogleException(Exception):  # noqa: N818
    pass


class GoogleError(GoogleException):
    pass


class ResponseFormatError(GoogleException):
    """An unknown response format from Google

    Response format has changed or response was interrupted for some reason.
    If this exception occurs every time, the format has likely changed.
    """


class InvalidLanguageCodeError(GoogleException):
    """Language Code for languages not listed in Google Translate

    When 'code_sensitive' is 'True', specifying a language code that does not exist
    in the list will cause an exception.
    Language code is case-insensitive.
    """


class HTTPException(GoogleException):
    pass


class HTTPConnectionError(HTTPException):
    pass


class HTTPTimeoutError(HTTPException):
    pass


class HTTPRedirection(HTTPException):
    """HTTP 3xx Redirection Exception"""


class HTTPError(HTTPException):
    """HTTP 4xx/5xx Error Exception"""


class HTTPTooManyRequests(HTTPException):
    """HTTP 429 Too Many Requests Exception"""


class TextResult:
    def __init__(
        self,
        sentences: str | list[str],
        detected_source_lang: str | None,
        *,
        pronounce_src: str | None = None,
        pronounce_tgt: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        if isinstance(sentences, str):
            self.text: str = sentences
        elif isinstance(sentences, list):
            # The specification for when it becomes a list is unclear.
            # e.g. when translating simultaneously into multiple languages?
            # Given the current implementation, it should never return as a list, so for now, return the combined list.
            self.text: str = " ".join(sentences)
        else:
            msg: str = f"'{type(sentences)}' is an unsupported type"
            raise ResponseFormatError(msg)

        self.detected_source_lang: str | None = detected_source_lang
        self.pronounce_src: str | None = pronounce_src
        self.pronounce_tgt: str | None = pronounce_tgt
        self.metadata: dict[str, str] | None = metadata

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return (
            f"<TextResult text={self.text} detected_source_lang={self.detected_source_lang} "
            f"pronounce_src={self.pronounce_src} pronounce_tgt={self.pronounce_tgt} metadata={self.metadata}>"
        )


class AsyncTranslator:
    def __init__(
        self,
        url_suffix: str = "com",
        timeout: float = 10.0,
        proxies: dict[str, str] | None = None,
        *,
        code_sensitive: bool = False,
        return_list: bool = True,
    ) -> None:
        self.proxies: dict[str, str] | None = proxies
        if url_suffix not in URLS_SUFFIX:
            self.url_suffix = URL_SUFFIX_DEFAULT
        else:
            self.url_suffix: str = url_suffix
        _url_base: str = f"https://translate.google.{self.url_suffix}"
        self.url: str = _url_base + "/_/TranslateWebserverUi/data/batchexecute"
        self.timeout: float = timeout
        self.code_sensitive: bool = code_sensitive
        self.return_list: bool = return_list
        self.__session: aiohttp.ClientSession = aiohttp.ClientSession()

    @property
    def _session(self) -> aiohttp.ClientSession:
        """Returns current session information

        If the session has not been created or closed, a new session is created.
        """
        try:
            if self.__session.closed:
                self.__session = aiohttp.ClientSession()
        except (NameError, AttributeError):
            self.__session = aiohttp.ClientSession()
        return self.__session

    async def close(self) -> None:
        logger.debug("'%s': 'termination process'", self.__class__.__name__)
        try:
            await self.__session.close()
        except (NameError, AttributeError):
            pass
        finally:
            logger.debug("'%s': 'finished'", self.__class__.__name__)

    def _package_rpc(self, text: str, lang_src: str = "auto", lang_tgt: str = "auto") -> str:
        _google_tts_rpc: list[str] = ["MkEWBc"]
        _parameter: list[list[str | int | bool]] = [[text.strip(), lang_src, lang_tgt, True], [1]]
        _escaped_parameter: str = json.dumps(_parameter, separators=(",", ":"))
        _rpc: list[list[list[str | None]]] = [[[random.choice(_google_tts_rpc), _escaped_parameter, None, "generic"]]]  # noqa: S311
        _espaced_rpc: str = json.dumps(_rpc, separators=(",", ":"))
        return f"f.req={quote(_espaced_rpc)}&"

    @staticmethod
    def _check_langcode(lang: str, *, sensitive: bool = False) -> str:
        for code in LANGUAGES:
            if lang.lower() == code.lower():
                return code
        if sensitive:
            msg: str = f"Invalid language code passed ({lang})"
            raise InvalidLanguageCodeError(msg)
        return "auto"

    @staticmethod
    def _build_body_preview(body: str, limit: int = 500) -> str:
        body_preview: str = body.strip().replace("\n", "\\n")
        if len(body_preview) > limit:
            return f"{body_preview[:limit]}..."
        return body_preview

    @staticmethod
    def _format_http_error(
        status: int,
        reason: str | None,
        url: str,
        *,
        body_preview: str | None = None,
        location: str | None = None,
    ) -> str:
        status_reason: str = f"{status} {reason}".strip() if reason else str(status)
        parts: list[str] = [f"HTTP {status_reason} from {url}"]
        if location:
            parts.append(f"Location: {location}")
        if body_preview:
            parts.append(f"Body: {body_preview}")
        return ". ".join(parts)

    async def _post(
        self,
        *,
        url: str,
        data: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 300.0,  # noqa: ASYNC109
        proxies: dict[str, str] | None = None,
    ) -> str:
        if proxies is None or not isinstance(proxies, dict):
            proxies = {}

        try:
            _timeout = aiohttp.ClientTimeout(total=timeout)
            async with self._session.post(
                url=url,
                data=data,
                headers=headers,
                timeout=_timeout,
                proxy=proxies.get("https"),
            ) as response:
                body: str = await response.text()
                if response.status >= 300:
                    body_preview = self._build_body_preview(body)
                    if response.status == 429:
                        msg = self._format_http_error(
                            response.status,
                            response.reason,
                            url,
                            body_preview=body_preview,
                        )
                        raise HTTPTooManyRequests(msg)
                    if response.status >= 400:
                        msg = self._format_http_error(
                            response.status,
                            response.reason,
                            url,
                            body_preview=body_preview,
                        )
                        raise HTTPError(msg)

                    msg = self._format_http_error(
                        response.status,
                        response.reason,
                        url,
                        location=response.headers.get("Location"),
                    )
                    raise HTTPRedirection(msg)

                return body
        except TimeoutError:
            msg = "Timeout occurred for aiohttp.ClientSession"
            raise HTTPTimeoutError(msg) from None
        except ConnectionResetError:
            msg = "connection to host has been disconnected"
            raise HTTPConnectionError(msg) from None
        except aiohttp.ClientConnectorError as err:
            # Request failed
            raise HTTPConnectionError(err) from None

    async def translate(self, text: str, lang_tgt: str = "auto", lang_src: str | None = "auto") -> TextResult:
        lang_src, lang_tgt = self._validate_languages(lang_src, lang_tgt)
        self._validate_text_length(text)
        headers: dict[str, str] = self._build_headers()
        freq: str = self._package_rpc(text, lang_src, lang_tgt)

        try:
            resp: str = await self._post(
                url=self.url, data=freq, headers=headers, timeout=self.timeout, proxies=self.proxies
            )
            return self._process_response(resp)
        except (JSONDecodeError, TypeError) as err:
            raise ResponseFormatError(err) from None
        except TimeoutError as err:
            raise HTTPTimeoutError(err) from None

    def _validate_languages(self, lang_src: str | None, lang_tgt: str) -> tuple[str, str]:
        lang_src = self._check_langcode(lang_src or "auto", sensitive=self.code_sensitive)
        lang_tgt = self._check_langcode(lang_tgt, sensitive=self.code_sensitive)
        return lang_src, lang_tgt

    def _validate_text_length(self, text: str) -> None:
        if not text:
            msg = "No characters to translate"
            raise GoogleError(msg)
        if len(text) >= 5000:
            msg = "Can only translate less than 5000 characters"
            raise GoogleError(msg)

    def _build_headers(self) -> dict[str, str]:
        return {
            "Referer": f"http://translate.google.{self.url_suffix}/",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        }

    def _process_response(self, resp: str) -> TextResult:
        for line in resp.splitlines():
            if "MkEWBc" not in line:
                continue

            logger.debug(line)
            try:
                decoded_data = json.loads(json.loads(line)[0][2])
                detect_lang = decoded_data[1][3]
                trans_info = decoded_data[1][0]
            except JSONDecodeError as err:
                msg = "failed to decode response"
                raise ResponseFormatError(msg) from err
            except (IndexError, TypeError) as err:
                msg = "invalid response format"
                raise ResponseFormatError(msg) from err

            if len(trans_info) == 1 or not self.return_list:
                return self._handle_single_translation(decoded_data, trans_info, detect_lang)

            if len(trans_info) == 2:
                return self._handle_multiple_translations(decoded_data, trans_info, detect_lang)

            msg = "unknown error"
            raise GoogleError(msg)
        msg = "unknown response format"
        raise ResponseFormatError(msg)

    def _handle_single_translation(self, decoded_data: Any, trans_info: Any, detect_lang: str) -> TextResult:
        if len(trans_info[0]) > 5:
            translate_text: str = self._extract_translation(trans_info)
            (pronounce_src, pronounce_tgt) = self._extract_language_codes(decoded_data)

            return TextResult(
                translate_text,
                detect_lang,
                pronounce_src=pronounce_src,
                pronounce_tgt=pronounce_tgt,
                metadata={"engine": "google", "type": "single translation"},
            )

        sentences = trans_info[0][0]
        return TextResult(
            sentences,
            "und",  # undetermined
            metadata={"engine": "google", "type": "url recognition", "text": "argument text was recognized as a URL"},
        )

    def _handle_multiple_translations(self, decoded_data: Any, trans_info: Any, detect_lang: str) -> TextResult:
        sentences = [i[0] for i in trans_info]
        (pronounce_src, pronounce_tgt) = self._extract_language_codes(decoded_data)

        return TextResult(
            sentences,
            detect_lang,
            pronounce_src=pronounce_src,
            pronounce_tgt=pronounce_tgt,
            metadata={"engine": "google", "type": "multiple translation"},
        )

    def _extract_translation(self, trans_info: list[Any]) -> str:
        try:
            sentences = trans_info[0][5]
        except (IndexError, TypeError) as err:
            msg = "Invalid response format for sentences"
            raise ResponseFormatError(msg) from err

        translate_text: str = ""
        for sentence in sentences:
            translate_text += sentence[0].strip() + " "
        return translate_text.strip()

    def _extract_language_codes(self, decoded_data: Any) -> tuple[str, str]:
        try:
            src = decoded_data[0][0]
            tgt = decoded_data[1][0][0][1]
        except (IndexError, TypeError) as err:
            msg = "Invalid response format for language code"
            raise ResponseFormatError(msg) from err

        return (src, tgt)

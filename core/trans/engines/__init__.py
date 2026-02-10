"""Translation engine implementations.

This package contains concrete implementations of the TransInterface for different
translation services (Google Translate, DeepL) and utilities for interfacing with them.
These classes handle the communication with external translation APIs, manage request/response formats,
and provide error handling specific to each service.

Modules:
- AsyncTranslator: Asynchronous translator interface for making translation requests.
- DeeplTranslation: Implementation for DeepL translation service.
- GoogleCloudTranslation: Implementation for Google Cloud Translation service.
- GoogleTranslation: Implementation for Google Translate service.
"""

from core.trans.engines.async_google_translate import (
    AsyncTranslator,
    GoogleError,
    HTTPConnectionError,
    HTTPError,
    HTTPTimeoutError,
    InvalidLanguageCodeError,
    ResponseFormatError,
    TextResult,
)
from core.trans.engines.const_google import DEFAULT_SERVICE_URLS, LANGUAGES
from core.trans.engines.trans_deepl import DeeplTranslation
from core.trans.engines.trans_google import GoogleTranslation
from core.trans.engines.trans_google_cloud import GoogleCloudTranslation

__all__: list[str] = [
    "DEFAULT_SERVICE_URLS",
    "LANGUAGES",
    "AsyncTranslator",
    "DeeplTranslation",
    "GoogleCloudTranslation",
    "GoogleError",
    "GoogleTranslation",
    "HTTPConnectionError",
    "HTTPError",
    "HTTPTimeoutError",
    "InvalidLanguageCodeError",
    "ResponseFormatError",
    "TextResult",
]

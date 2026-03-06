"""Google Cloud Speech-to-Text engine implementation."""

from __future__ import annotations

import base64
import json
import os
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib import error, parse, request

from core.stt.interface import (
    STTExceptionError,
    STTInput,
    STTInterface,
    STTNonRetriableError,
    STTNotAvailableError,
    STTResult,
)
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from types import ModuleType

    from config.loader import Config

__all__: list[str] = ["GoogleCloudSpeechToText"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

NON_RETRIABLE_GOOGLE_ERROR_NAMES: frozenset[str] = frozenset(
    {
        "InvalidArgument",
        "PermissionDenied",
        "Unauthenticated",
        "FailedPrecondition",
        "OutOfRange",
        "Unimplemented",
    }
)


class GoogleCloudSpeechToText(STTInterface):
    """Google Cloud Speech-to-Text engine.

    This engine supports two authentication modes:
    - Service account credentials via ``GOOGLE_APPLICATION_CREDENTIALS``.
    - API key text via ``GOOGLE_CLOUD_API_OAUTH``.

    When service account credentials are available, the official client library is used.
    Otherwise, when an API key is configured, the REST API endpoint is used.
    """

    def __init__(self) -> None:
        self._available: bool = False
        self._auth_source: str | None = None
        self._api_key: str | None = None
        self._client: Any | None = None
        self._speech_module: ModuleType | None = None

    @property
    def is_available(self) -> bool:
        return self._available

    @staticmethod
    def fetch_engine_name() -> str:
        return "google_cloud_stt"

    def initialize(self, config: Config) -> None:
        """Initialize Google Cloud STT authentication and runtime mode.

        Args:
            config: Loaded application config. This engine currently relies on environment variables,
                but the argument is kept for interface compatibility.

        Notes:
            Authentication priority is:
            1. ``GOOGLE_APPLICATION_CREDENTIALS`` (service account).
            2. ``GOOGLE_CLOUD_API_OAUTH`` (API key text).

            If neither is configured, the engine remains unavailable.
        """
        _ = config
        self._available = False
        self._auth_source = None
        self._api_key = None
        self._client = None
        self._speech_module = None

        api_oauth: str = os.getenv("GOOGLE_CLOUD_API_OAUTH", "").strip()
        credentials_path: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

        if credentials_path:
            credentials_file = Path(credentials_path)
            if not credentials_file.is_file():
                logger.warning("GOOGLE_APPLICATION_CREDENTIALS does not point to a valid file: %s", credentials_path)
                return
            self._auth_source = "GOOGLE_APPLICATION_CREDENTIALS"
            self._initialize_client_mode()
        elif api_oauth:
            self._api_key = api_oauth
            self._auth_source = "GOOGLE_CLOUD_API_OAUTH"
            self._available = True
            logger.info("Google Cloud STT initialized (auth source: %s)", self._auth_source)
        else:
            logger.warning(
                "Google Cloud STT auth is not configured. Set GOOGLE_CLOUD_API_OAUTH or GOOGLE_APPLICATION_CREDENTIALS"
            )
            return

    def transcribe(self, stt_input: STTInput) -> STTResult:
        """Transcribe audio using Google Cloud Speech-to-Text.

        Args:
            stt_input: STT input containing PCM audio file path and recognition settings.

        Returns:
            STT result with combined transcript text, optional average confidence,
            and engine metadata.

        Raises:
            STTNotAvailableError: If the engine is not initialized or auth mode is unavailable.
            STTExceptionError: If input audio is missing or recognition fails.
            STTNonRetriableError: If Google Cloud returns a non-retriable request error.
        """
        if not self._available:
            msg = "Google Cloud STT engine is not available"
            raise STTNotAvailableError(msg)

        if not stt_input.audio_path.is_file():
            msg = f"Audio file not found: {stt_input.audio_path}"
            raise STTExceptionError(msg)

        pcm_data: bytes = stt_input.audio_path.read_bytes()
        if not pcm_data:
            return STTResult(
                text="", language=stt_input.language, confidence=None, metadata={"engine": "google_cloud_stt"}
            )

        if self._client is not None and self._speech_module is not None:
            transcripts, confidences = self._recognize_by_client(stt_input, pcm_data)
        elif self._api_key:
            transcripts, confidences = self._recognize_by_api_key(stt_input, pcm_data)
        else:
            msg = "Google Cloud STT auth mode is not initialized"
            raise STTNotAvailableError(msg)

        combined_text: str = " ".join(transcripts).strip()
        average_confidence: float | None = None
        if confidences:
            average_confidence = sum(confidences) / len(confidences)

        return STTResult(
            text=combined_text,
            language=stt_input.language,
            confidence=average_confidence,
            metadata={"engine": "google_cloud_stt", "auth_source": str(self._auth_source)},
        )

    @staticmethod
    def _import_speech_module() -> ModuleType:
        """Import the Google Cloud Speech client module.

        Returns:
            Imported ``google.cloud.speech`` module.
        """
        return import_module("google.cloud.speech")

    @staticmethod
    def _create_client(speech_module: ModuleType) -> Any:
        """Create a SpeechClient instance.

        Args:
            speech_module: Imported ``google.cloud.speech`` module.

        Returns:
            Speech client instance created from the module.
        """
        return speech_module.SpeechClient()

    def _initialize_client_mode(self) -> None:
        """Initialize client-library mode for service-account authentication."""
        try:
            speech_module: ModuleType = self._import_speech_module()
            self._client = self._create_client(speech_module)
            self._speech_module = speech_module
            self._available = True
            logger.info("Google Cloud STT initialized (auth source: %s)", self._auth_source)
        except ImportError as err:
            logger.warning("Google Cloud STT package is unavailable: %s", err)
        except Exception as err:  # noqa: BLE001
            logger.warning("Failed to initialize Google Cloud STT client: %s", err)

    def _recognize_by_client(self, stt_input: STTInput, pcm_data: bytes) -> tuple[list[str], list[float]]:
        """Run recognition via the Google Cloud Python client.

        Args:
            stt_input: STT input containing sample rate, language, and channel count.
            pcm_data: Raw LINEAR16 PCM audio bytes.

        Returns:
            Tuple of ``(transcripts, confidences)``.

        Raises:
            STTNonRetriableError: If Google returns a non-retriable error.
            STTExceptionError: If the request fails for other reasons.
        """
        speech_module = cast("Any", self._speech_module)
        client = cast("Any", self._client)
        try:
            audio = speech_module.RecognitionAudio(content=pcm_data)
            config = speech_module.RecognitionConfig(
                encoding=speech_module.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=stt_input.sample_rate,
                language_code=stt_input.language,
                audio_channel_count=stt_input.channels,
                enable_automatic_punctuation=True,
            )
            response = client.recognize(config=config, audio=audio)
            return self._extract_results(getattr(response, "results", []), object_mode=True)
        except Exception as err:  # noqa: BLE001
            if self._is_non_retriable_google_error(err):
                msg = f"Google Cloud STT non-retriable request error: {type(err).__name__}: {err}"
                raise STTNonRetriableError(msg) from err
            msg = f"Google Cloud STT request failed: {err}"
            raise STTExceptionError(msg) from err

    def _recognize_by_api_key(self, stt_input: STTInput, pcm_data: bytes) -> tuple[list[str], list[float]]:
        """Run recognition via the Google Cloud REST API using an API key.

        Args:
            stt_input: STT input containing sample rate, language, and channel count.
            pcm_data: Raw LINEAR16 PCM audio bytes.

        Returns:
            Tuple of ``(transcripts, confidences)``.

        Raises:
            STTNonRetriableError: If Google returns a non-retriable error.
            STTExceptionError: If the request fails for other reasons.
        """
        payload: dict[str, Any] = {
            "config": {
                "encoding": "LINEAR16",
                "sampleRateHertz": stt_input.sample_rate,
                "languageCode": stt_input.language,
                "audioChannelCount": stt_input.channels,
                "enableAutomaticPunctuation": True,
            },
            "audio": {
                "content": base64.b64encode(pcm_data).decode("utf-8"),
            },
        }
        url: str = f"https://speech.googleapis.com/v1/speech:recognize?key={parse.quote(self._api_key or '')}"
        try:
            response_json = self._post_json(url=url, payload=payload)
            return self._extract_results(response_json.get("results", []), object_mode=False)
        except STTNonRetriableError:
            raise
        except Exception as err:  # noqa: BLE001
            if self._is_non_retriable_google_error(err):
                msg = f"Google Cloud STT REST non-retriable request error: {type(err).__name__}: {err}"
                raise STTNonRetriableError(msg) from err
            msg = f"Google Cloud STT REST request failed: {err}"
            raise STTExceptionError(msg) from err

    @staticmethod
    def _is_non_retriable_google_error(err: Exception) -> bool:
        """Check whether an exception class maps to a non-retriable Google API error."""
        error_name: str = type(err).__name__
        return any(name in error_name for name in NON_RETRIABLE_GOOGLE_ERROR_NAMES)

    @staticmethod
    def _extract_results(results: list[Any], *, object_mode: bool) -> tuple[list[str], list[float]]:
        """Extract transcript and confidence values from recognition results.

        Args:
            results: API result entries from either client-library objects or REST dictionaries.
            object_mode: ``True`` when ``results`` contains SDK objects; ``False`` for REST dicts.

        Returns:
            Tuple of ``(transcripts, confidences)`` where confidences include positive values only.
        """
        transcripts: list[str] = []
        confidences: list[float] = []
        for result in results:
            alternatives = getattr(result, "alternatives", []) if object_mode else result.get("alternatives", [])
            if not alternatives:
                continue

            top = alternatives[0]
            if object_mode:
                transcript = str(getattr(top, "transcript", "")).strip()
                confidence_raw = getattr(top, "confidence", 0.0)
            else:
                transcript = str(top.get("transcript", "")).strip()
                confidence_raw = top.get("confidence", 0.0)

            if transcript:
                transcripts.append(transcript)

            confidence = float(confidence_raw or 0.0)
            if confidence > 0.0:
                confidences.append(confidence)
        return transcripts, confidences

    @staticmethod
    def _post_json(*, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON payload to the given URL and return decoded JSON object.

        Args:
            url: HTTPS endpoint URL.
            payload: Request JSON body.

        Returns:
            Decoded JSON response as a dictionary.

        Raises:
            STTExceptionError: If URL scheme is invalid, network/HTTP errors occur,
                or the response format is not a JSON object.
        """
        parsed_url: parse.ParseResult = parse.urlparse(url)
        if parsed_url.scheme != "https":
            msg = f"Unsupported URL scheme for STT request: {parsed_url.scheme}"
            raise STTExceptionError(msg)

        request_data = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url=url, data=request_data, headers={"Content-Type": "application/json"})  # noqa: S310
        try:
            with request.urlopen(http_request, timeout=30) as response:  # noqa: S310
                body = response.read().decode("utf-8")
        except error.HTTPError as err:
            error_body = err.read().decode("utf-8", errors="ignore")
            msg = f"HTTP {err.code}: {error_body}"
            raise STTExceptionError(msg) from err
        except error.URLError as err:
            msg = f"Network error: {err.reason}"
            raise STTExceptionError(msg) from err

        decoded = json.loads(body)
        if not isinstance(decoded, dict):
            msg = "Unexpected response format from Google Cloud STT"
            raise STTExceptionError(msg)
        return decoded

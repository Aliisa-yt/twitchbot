"""Google Cloud Speech-to-Text V2 engine implementation."""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from core.stt.interface import (
    STTExceptionError,
    STTInput,
    STTInterface,
    STTNonRetriableError,
    STTNotAvailableError,
    STTResult,
)
from core.stt.stt_location_model_loader import (
    STABLE_LOCATIONS,
    STTLanguageInfo,
    get_stt_language_info,
    load_stt_language_index,
)
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from types import ModuleType

    from config.loader import Config

__all__: list[str] = ["GoogleCloudSpeechToTextV2"]

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

STT_V2_SUPPORTED_LANGUAGES_FILE: Path = (
    Path(__file__).resolve().parents[3] / "data" / "stt" / "google-cloud-stt-v2_supported-languages.txt"
)
STT_V2_PREFERRED_LOCATIONS: tuple[str, ...] = ("global", "us", "eu", "us-central1")


class GoogleCloudSpeechToTextV2(STTInterface):
    """Google Cloud Speech-to-Text V2 engine.

    This engine uses the latest Google Cloud Speech-to-Text API (v2) with service account authentication.
    It supports automatic recognizer management and enhanced recognition features.

    Authentication:
    - Requires service account credentials with appropriate permissions (e.g., speech.recognizers.create).
        - Credentials are resolved from GOOGLE_APPLICATION_CREDENTIALS.
        - GOOGLE_CLOUD_API_OAUTH is treated as API key text and is not used by this engine.

    Configuration:
    - GOOGLE_CLOUD_STT_V2_LOCATION: API location (default: "global")
    - GOOGLE_CLOUD_STT_V2_MODEL: Model to use (default: "chirp_2")
    - GOOGLE_CLOUD_STT_V2_RECOGNIZER: Recognizer to use (optional)
    """

    def __init__(self) -> None:
        self._available: bool = False
        self._auth_source: str | None = None
        self._client: Any | None = None
        self._speech_module: ModuleType | None = None
        self._project_id: str | None = None
        self._language: str = "ja-JP"
        self._location: str = "global"
        self._recognizer: str = ""
        self._recognizer_name: str = ""
        self._model: str = "chirp_2"

    @property
    def is_available(self) -> bool:
        return self._available

    @staticmethod
    def fetch_engine_name() -> str:
        return "google_cloud_stt_v2"

    def initialize(self, config: Config) -> None:
        """Initialize the Google Cloud Speech-to-Text V2 engine."""
        self._available = False
        self._auth_source = None
        self._client = None
        self._speech_module = None
        self._project_id = None
        self._recognizer_name = ""
        self._language = "ja-JP"
        stt_config = getattr(config, "STT", None)
        location = str(getattr(stt_config, "GOOGLE_CLOUD_STT_V2_LOCATION", "")).strip()
        model = str(getattr(stt_config, "GOOGLE_CLOUD_STT_V2_MODEL", "")).strip()
        recognizer = str(getattr(stt_config, "GOOGLE_CLOUD_STT_V2_RECOGNIZER", "")).strip()
        language = str(getattr(stt_config, "LANGUAGE", "")).strip()

        if language:
            self._language = language

        location, model = self._resolve_location_model(
            language=language,
            location=location,
            model=model,
        )

        self._location = location
        self._model = model
        self._recognizer = recognizer

        api_oauth: str = os.getenv("GOOGLE_CLOUD_API_OAUTH", "").strip()
        credentials_path: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

        if credentials_path:
            credentials_file = Path(credentials_path)
            if not credentials_file.is_file():
                logger.warning("GOOGLE_APPLICATION_CREDENTIALS does not point to a valid file: %s", credentials_path)
                return
            self._auth_source = "GOOGLE_APPLICATION_CREDENTIALS"
            self._project_id = self._resolve_project_id(credentials_file)
            self._initialize_client_mode()
            return

        if api_oauth:
            logger.warning(
                "GOOGLE_CLOUD_API_OAUTH is configured, but STT V2 requires service-account auth via "
                "GOOGLE_APPLICATION_CREDENTIALS"
            )
            return

        logger.warning("Google Cloud STT V2 auth is not configured. Set GOOGLE_APPLICATION_CREDENTIALS")

    def _resolve_location_model(self, *, language: str, location: str, model: str) -> tuple[str, str]:
        """Resolve STT V2 location/model from config and language metadata."""
        resolved_location: str = location
        resolved_model: str = model

        if resolved_location and resolved_model:
            return resolved_location, resolved_model

        if language:
            try:
                preferred_locations = STT_V2_PREFERRED_LOCATIONS
                if resolved_location:
                    preferred_locations = (
                        resolved_location,
                        *tuple(item for item in STT_V2_PREFERRED_LOCATIONS if item != resolved_location),
                    )

                language_index: dict[str, STTLanguageInfo] = load_stt_language_index(
                    STT_V2_SUPPORTED_LANGUAGES_FILE,
                    preferred_locations=preferred_locations,
                    allowed_locations=STABLE_LOCATIONS,
                )
                language_info: STTLanguageInfo | None = get_stt_language_info(language_index, language)

                if language_info is None:
                    logger.warning(
                        "STT language metadata was not found for STT.LANGUAGE=%s. Falling back to static defaults.",
                        language,
                    )
                else:
                    if not resolved_location:
                        resolved_location = language_info["location"]
                        logger.warning(
                            "GOOGLE_CLOUD_STT_V2_LOCATION is not configured in ini. "
                            "Auto-assigned '%s' from STT.LANGUAGE=%s.",
                            resolved_location,
                            language,
                        )

                    if not resolved_model:
                        resolved_model = language_info["default_model"]
                        logger.warning(
                            "GOOGLE_CLOUD_STT_V2_MODEL is not configured in ini. "
                            "Auto-assigned '%s' from STT.LANGUAGE=%s.",
                            resolved_model,
                            language,
                        )
            except Exception as err:  # noqa: BLE001
                logger.warning(
                    "Failed to load STT V2 language metadata from %s: %s",
                    STT_V2_SUPPORTED_LANGUAGES_FILE,
                    err,
                )

        if not resolved_location:
            logger.warning("GOOGLE_CLOUD_STT_V2_LOCATION is not configured in ini. Falling back to 'global'.")
            resolved_location = "global"

        if not resolved_model:
            logger.warning("GOOGLE_CLOUD_STT_V2_MODEL is not configured in ini. Falling back to 'chirp_2'.")
            resolved_model = "chirp_2"

        return resolved_location, resolved_model

    def transcribe(self, stt_input: STTInput) -> STTResult:
        """Transcribe audio using Google Cloud Speech-to-Text V2.

        Args:
            stt_input: STTInput object containing audio path and settings.

        Returns:
            STTResult object with transcription results.

        Raises:
            STTNotAvailableError: If the engine is not available or not properly initialized.
            STTExceptionError: If the transcription request fails.
        """
        if not self._available:
            msg = "Google Cloud STT V2 engine is not available"
            raise STTNotAvailableError(msg)

        if not stt_input.audio_path.is_file():
            msg = f"Audio file not found: {stt_input.audio_path}"
            raise STTExceptionError(msg)

        pcm_data: bytes = stt_input.audio_path.read_bytes()
        if not pcm_data:
            return STTResult(
                text="",
                language=stt_input.language,
                confidence=None,
                metadata={"engine": "google_cloud_stt_v2"},
            )

        if self._client is None or self._speech_module is None:
            msg = "Google Cloud STT V2 auth mode is not initialized"
            raise STTNotAvailableError(msg)

        transcripts, confidences = self._recognize_by_client(stt_input=stt_input, pcm_data=pcm_data)
        combined_text: str = " ".join(transcripts).strip()
        average_confidence: float | None = None
        if confidences:
            average_confidence = sum(confidences) / len(confidences)

        return STTResult(
            text=combined_text,
            language=stt_input.language,
            confidence=average_confidence,
            metadata={
                "engine": "google_cloud_stt_v2",
                "auth_source": str(self._auth_source),
                "project_id": str(self._project_id),
                "location": self._location,
                "recognizer": self._recognizer_name,
                "model": self._model,
            },
        )

    @staticmethod
    def _import_speech_module() -> ModuleType:
        """Import the Google Cloud Speech client module.

        Returns:
            Imported ``google.cloud.speech_v2`` module.
        """
        return import_module("google.cloud.speech_v2")

    def _create_client(self, speech_module: ModuleType) -> Any:
        """Create a SpeechClient with the appropriate API endpoint based on location.
        If the client library does not support client_options, it will fall back to the default endpoint.
        """
        api_endpoint: str = "speech.googleapis.com"
        if self._location != "global":
            api_endpoint = f"{self._location}-speech.googleapis.com"

        try:
            return speech_module.SpeechClient(client_options={"api_endpoint": api_endpoint})
        except TypeError:
            logger.warning(
                "SpeechClient does not support client_options. Falling back to default endpoint. "
                "To fix this, update google-cloud-speech package to a version that supports client_options."
            )
            return speech_module.SpeechClient()

    @staticmethod
    def _resolve_project_id(credentials_file: Path) -> str | None:
        """Extract project_id from the service account credentials JSON file."""
        try:
            raw: str = credentials_file.read_text(encoding="utf-8")
            decoded = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return None

        if isinstance(decoded, dict):
            value: str = str(decoded.get("project_id", "")).strip()
            if value:
                return value
        return None

    def _initialize_client_mode(self) -> None:
        """Initialize the client mode for Google Cloud STT V2 using service account credentials."""
        if not self._project_id:
            msg = "Google Cloud STT V2 project id is not configured. Include project_id in credentials JSON"
            logger.warning(msg)
            return

        try:
            speech_module: ModuleType = self._import_speech_module()
            self._client = self._create_client(speech_module)
            self._speech_module = speech_module
            self._ensure_recognizer()
            self._available = True
            logger.info("Google Cloud STT V2 initialized (auth source: %s)", self._auth_source)
        except ImportError as err:
            logger.warning("Google Cloud STT V2 package is unavailable: %s", err)
        except STTNotAvailableError as err:
            logger.warning("Google Cloud STT V2 initialization failed: %s", err)
        except Exception as err:  # noqa: BLE001
            logger.warning("Failed to initialize Google Cloud STT V2 client: %s", err)

    @staticmethod
    def _is_not_found_error(err: Exception) -> bool:
        name: str = type(err).__name__
        return "NotFound" in name or "404" in str(err)

    @staticmethod
    def _is_permission_denied_error(err: Exception, *, permission: str | None = None) -> bool:
        """Check if the error is a permission denied error, optionally checking for a specific permission string.

        Args:
            err: The exception to check.
            permission: Optional specific permission string to look for in the error message.

        Returns:
            True if it's a permission denied error (and contains the specific permission if provided), False otherwise.
        """
        body: str = str(err)
        is_denied: bool = "IAM_PERMISSION_DENIED" in body or ("Permission" in body and "denied" in body.lower())
        if not is_denied:
            return False
        if permission is None:
            return True
        return permission in body

    def _resolve_recognizer_id(self) -> str:
        """Resolve the recognizer ID, either from configuration or by generating a default one."""
        recognizer_id: str = self._recognizer
        if recognizer_id:
            # Some guides for global recognition still show recognizer="-".
            # Keep compatibility by translating "-" to the current default recognizer id "_".
            if recognizer_id == "-":
                recognizer_id = "_"
                logger.warning(
                    "GOOGLE_CLOUD_STT_V2_RECOGNIZER is set to '-', which is deprecated. "
                    "Using '_' for default recognizer instead."
                )
            return recognizer_id

        recognizer_id = f"twitchbot-{self._location}-default"
        logger.info(
            "GOOGLE_CLOUD_STT_V2_RECOGNIZER is not configured in ini. Auto-creating/using recognizer: %s",
            recognizer_id,
        )
        return recognizer_id

    def _try_get_recognizer(self, *, client: Any, speech_types: Any, recognizer_name: str) -> bool:
        """Try to get the recognizer by name. Return True if it exists, False if not found, and raise for other errors.

        Args:
            client: The SpeechClient instance.
            speech_types: The module containing request/response types.
            recognizer_name: The full resource name of the recognizer to get.

        Returns:
            True if the recognizer exists, False if not found, and raises for other errors.
        """
        try:
            get_request_cls = getattr(speech_types, "GetRecognizerRequest", None)
            if get_request_cls is not None:
                request = get_request_cls(name=recognizer_name)
                client.get_recognizer(request=request)
            else:
                client.get_recognizer(name=recognizer_name)
        except Exception as err:  # noqa: BLE001
            is_not_found: bool = self._is_not_found_error(err)

            if self._recognizer and is_not_found:
                msg = f"Configured recognizer was not found: {recognizer_name}"
                raise STTNotAvailableError(msg) from err

            if self._recognizer and not is_not_found:
                raise

            return False
        else:
            return True

    def _create_recognizer(self, *, client: Any, speech_types: Any, recognizer_id: str) -> None:
        """Create a new recognizer with the given ID.

        Args:
            client: The SpeechClient instance.
            speech_types: The module containing request/response types.
            recognizer_id: The ID for the recognizer to create.

        Raises:
            STTNotAvailableError: If permission is denied to create the recognizer.
            Exception: For other errors during recognizer creation.
        """
        parent: str = f"projects/{self._project_id}/locations/{self._location}"
        create_request_cls = getattr(speech_types, "CreateRecognizerRequest", None)
        recognizer_cls = getattr(speech_types, "Recognizer", None)
        recognition_config_cls = getattr(speech_types, "RecognitionConfig", None)

        if recognizer_cls is not None and recognition_config_cls is not None:
            recognizer_obj = recognizer_cls(
                default_recognition_config=recognition_config_cls(
                    language_codes=[self._language],
                    model=self._model,
                    # TODO: Evaluate V2-only features such as noise suppression and audio sensitivity.
                    # These settings are still under verification.
                    # So far, they did not significantly reduce misrecognition.
                    # denoiser_config=speech_types.DenoiserConfig(
                    #     denoise_audio=True,
                    #     snr_threshold=50.0,
                    # ),
                    # If misinterpretations occur in the absence of speech, specifying noise suppression may improve
                    # the situation. However, this requires a louder audio input.
                    # Audio sensitivity
                    # snr_threshold: 0.0 = through, 10.0 = high, 20.0 = medium, 40.0 = low, 100.0 = worst
                )
            )
        else:
            recognizer_obj = None

        if create_request_cls is not None:
            create_request = create_request_cls(
                parent=parent,
                recognizer_id=recognizer_id,
                recognizer=recognizer_obj,
            )
            operation = client.create_recognizer(request=create_request)
        else:
            operation = client.create_recognizer(
                parent=parent,
                recognizer_id=recognizer_id,
                recognizer=recognizer_obj,
            )

        if hasattr(operation, "result"):
            try:
                operation.result()
            except Exception as err:  # noqa: BLE001
                if self._is_permission_denied_error(err, permission="speech.recognizers.create"):
                    msg = (
                        "Permission denied while auto-creating STT V2 recognizer. "
                        "Required IAM permission: speech.recognizers.create. "
                        "Grant the permission to the service account, or set GOOGLE_CLOUD_STT_V2_RECOGNIZER "
                        "to an existing recognizer id in twitchbot.ini."
                    )
                    raise STTNotAvailableError(msg) from err
                raise

    def _ensure_recognizer(self) -> None:
        """Ensure that a recognizer exists, creating one if necessary.

        Raises:
            STTNotAvailableError: If the recognizer cannot be created or accessed.
        """
        speech_module = cast("Any", self._speech_module)
        client = cast("Any", self._client)
        speech_types = getattr(speech_module, "types", speech_module)

        recognizer_id: str = self._resolve_recognizer_id()
        recognizer_name: str = f"projects/{self._project_id}/locations/{self._location}/recognizers/{recognizer_id}"

        # For recognizer_id="_", the backend automatically uses the built-in default recognizer.
        # Skip existence checks for this id because get_recognizer can fail for this special value.
        if recognizer_id == "_" or self._try_get_recognizer(
            client=client, speech_types=speech_types, recognizer_name=recognizer_name
        ):
            self._recognizer_name = recognizer_name
            self._recognizer = recognizer_id
            return

        self._create_recognizer(client=client, speech_types=speech_types, recognizer_id=recognizer_id)

        self._recognizer_name = recognizer_name
        self._recognizer = recognizer_id

    def _recognize_by_client(self, stt_input: STTInput, pcm_data: bytes) -> tuple[list[str], list[float]]:
        """Perform speech recognition using the client library.

        Args:
            stt_input: The STTInput containing audio and settings.
            pcm_data: The raw PCM audio data to transcribe.

        Returns:
            A tuple of (list of transcripts, list of confidence scores).

        Raises:
            STTExceptionError: If the recognition request fails.
        """
        speech_module = cast("Any", self._speech_module)
        client = cast("Any", self._client)

        recognizer_name: str = self._recognizer_name
        speech_types = getattr(speech_module, "types", speech_module)

        config = speech_types.RecognitionConfig(
            explicit_decoding_config=speech_types.ExplicitDecodingConfig(
                encoding=speech_types.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=stt_input.sample_rate,
                audio_channel_count=stt_input.channels,
            ),
            language_codes=[stt_input.language],
            model=self._model,
            features=speech_types.RecognitionFeatures(enable_automatic_punctuation=True),
        )
        request = speech_types.RecognizeRequest(
            recognizer=recognizer_name,
            config=config,
            content=pcm_data,
        )

        try:
            response = client.recognize(request=request)
            return self._extract_results(getattr(response, "results", []))
        except Exception as err:  # noqa: BLE001
            if self._is_non_retriable_google_error(err):
                msg = f"Google Cloud STT V2 non-retriable request error: {type(err).__name__}: {err}"
                raise STTNonRetriableError(msg) from err
            msg = f"Google Cloud STT V2 request failed: {err}"
            raise STTExceptionError(msg) from err

    @staticmethod
    def _is_non_retriable_google_error(err: Exception) -> bool:
        return type(err).__name__ in NON_RETRIABLE_GOOGLE_ERROR_NAMES

    @staticmethod
    def _extract_results(results: list[Any]) -> tuple[list[str], list[float]]:
        """Extract transcripts and confidence scores from recognition results.

        Args:
            results: The list of recognition results from the API response.

        Returns:
            A tuple of (list of transcripts, list of confidence scores).
        """
        transcripts: list[str] = []
        confidences: list[float] = []

        for result in results:
            alternatives = getattr(result, "alternatives", [])
            if not alternatives:
                continue

            top = alternatives[0]
            transcript = str(getattr(top, "transcript", "")).strip()
            confidence_raw = getattr(top, "confidence", 0.0)

            if transcript:
                transcripts.append(transcript)

            confidence = float(confidence_raw or 0.0)
            if confidence > 0.0:
                confidences.append(confidence)

        return transcripts, confidences

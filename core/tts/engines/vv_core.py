"""Base class for VOICEVOX-compatible text-to-speech engines.

Provides core functionality for communicating with VOICEVOX and compatible TTS APIs,
including audio query generation, speaker management, and parameter conversion.
Subclasses should implement api_command_procedure() to handle engine-specific synthesis.
"""

from __future__ import annotations

import asyncio
import json
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Final, Literal, TypeVar, overload

from marshmallow.exceptions import ValidationError

from core.tts.interface import (
    Interface,
    TTSFileError,
    TTSNotSupportedError,
)
from handlers.async_comm import AsyncCommError, AsyncCommTimeoutError, AsyncHttp
from models.voicevox_models import Speaker, _SpeakerStyle
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from dataclasses_json import DataClassJsonMixin

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["VVCore"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

RETRY_INTERVAL: Final[float] = 2.0  # Interval between retries when checking engine status
ENGINE_INITIALIZATION_TIMEOUT: Final[float] = RETRY_INTERVAL * 6 + 0.5  # Total timeout for engine initialization

T = TypeVar("T", bound="DataClassJsonMixin")


class VVCore(Interface):
    """Base class for VOICEVOX-compatible text-to-speech engines.

    Provides core functionality for communicating with VOICEVOX and compatible TTS APIs,
    including audio query generation, speaker management, and parameter conversion.
    Subclasses should implement api_command_procedure() to handle engine-specific synthesis.

    Attributes:
        PARAMETER_RANGE (dict): Valid ranges and defaults for synthesis parameters.
    """

    PARAMETER_RANGE: Final[dict[str, tuple[float, float, float]]] = {
        "speedScale": (0.50, 2.00, 1.00),
        "pitchScale": (-0.15, 0.15, 0.00),
        "intonationScale": (0.00, 2.00, 1.00),
        "volumeScale": (0.00, 2.00, 1.00),
        "prePhonemeLength": (0.00, 1.50, 0.10),
        "postPhonemeLength": (0.00, 1.50, 0.10),
    }

    def __init__(self) -> None:
        """Initialize the VVCore TTS engine.

        This constructor sets up the asynchronous HTTP client for communication with the TTS API.
        It also logs the initialization of the TTS engine.
        """
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()
        self.async_http = AsyncHttp()
        self.async_http.initialize_session()
        self.async_http.add_handler("audio/wav", lambda raw: raw)
        self._available_speakers: list[Speaker] = []
        self._id_cache: dict[str, int] = {}

    @property
    def default_speaker_id(self) -> int:
        """Get the default speaker ID.

        Returns:
            int: The default speaker ID.
        """
        return self._available_speakers[0].styles[0].id if self._available_speakers else 0

    @property
    def available_speakers(self) -> list[Speaker]:
        """Access the list of available VOICEVOX speakers.

        Returns:
            list[Speaker]: List of available VOICEVOX speakers.
        """
        return self._available_speakers

    @available_speakers.setter
    def available_speakers(self, value: list[Speaker]) -> None:
        """Set the list of available VOICEVOX speakers.

        Args:
            value (list[Speaker]): New list of available VOICEVOX speakers.
        """
        logger.debug("Updating available speakers with %d entries", len(value))
        self._available_speakers = value

    @property
    def id_cache(self) -> dict[str, int]:
        """Access the internal speaker ID cache.

        Returns:
            dict[str, int]: Mapping of cast strings to speaker IDs.
        """
        return self._id_cache

    @id_cache.setter
    def id_cache(self, value: dict[str, int]) -> None:
        """Set the internal speaker ID cache.

        Args:
            value (dict[str, int]): New mapping of cast strings to speaker IDs.
        """
        logger.debug("Updating speaker ID cache with %d entries", len(value))
        self._id_cache = value

    @staticmethod
    def fetch_engine_name() -> str:
        """Get the distinguished name of the TTS engine.

        Returns:
            str: The distinguished name of the TTS engine.
        """
        return ""

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the TTS engine with the provided configuration.

        Args:
            tts_engine (TTSEngine): The TTS engine configuration.
        Returns:
            bool: True if the setup is successful, False otherwise.
        """
        super().initialize_engine(tts_engine)
        return True

    async def async_init(self, param: UserTypeInfo) -> None:
        """Asynchronously initialize the TTS engine.

        Detects engine startup and waits until the service is accessible.

        Args:
            param (UserTypeInfo): User-specific voice configuration.
        """
        _ = param
        await self._detect_engine_startup()

    async def _detect_engine_startup(self) -> None:
        """Detect and wait for TTS engine startup with retries.

        Polls the TTS engine's version endpoint until it becomes accessible, with automatic
        retries at regular intervals. The version endpoint is used as a side-effect-free
        check for engine availability. Times out if the engine is not accessible within
        ENGINE_INITIALIZATION_TIMEOUT.

        Raises:
            (Logs error): If the TTS engine is not running or not accessible after timeout.
        """
        try:
            async with asyncio.timeout(ENGINE_INITIALIZATION_TIMEOUT):
                while True:
                    try:
                        version: str = await self._api_request(
                            method="get",
                            url=f"{self.url}/version",
                            model=None,
                            log_action="GET version",
                        )
                        logger.info("The TTS engine version %s is running and can be accessed.", version)
                    except AsyncCommTimeoutError:
                        logger.debug("The TTS engine is not running. It will try again in %.1f second.", RETRY_INTERVAL)
                        await asyncio.sleep(RETRY_INTERVAL)
                    else:
                        return
        except TimeoutError:
            msg: str = "The TTS engine is not running or is not accessible. Please check the server status."
            logger.error(msg)

    async def close(self) -> None:
        """Close the TTS engine and clean up resources."""
        await self.async_http.close()
        logger.info("%s process termination", self.__class__.__name__)

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        """Perform text-to-speech synthesis and save audio file.

        Calls the engine-specific api_command_procedure() to synthesize audio, saves the result
        to a temporary WAV file, and triggers playback via the callback.

        Args:
            ttsparam (TTSParam): The parameters for the TTS synthesis including text and voice settings.
        Raises:
            TTSFileError: If there is an error creating or saving the audio file.
            AsyncCommError: If there is a communication error with the TTS API.
            json.JSONDecodeError: If the response from the TTS API cannot be decoded as JSON.
            OSError: If there is a system error during the TTS synthesis.
            TypeError: If the API parameters have changed due to an update.
            RuntimeError: If an unexpected error occurs during the TTS process.
        """
        try:
            logger.debug("Starting TTS synthesis with parameters: %s", ttsparam)
            audio_data: bytes = await self.api_command_procedure(ttsparam)
            if not audio_data or not isinstance(audio_data, bytes):
                msg = "TTS synthesis failed: No audio data received."
                raise TTSNotSupportedError(msg)
            logger.debug("TTS synthesis completed successfully, audio data length: %d bytes", len(audio_data))

            voice_file: Path = self.create_audio_filename(suffix="wav")
            self.save_audio_file(voice_file, audio_data)
            ttsparam.filepath = voice_file
            await self.play(ttsparam)
        except (TTSFileError, AsyncCommError) as err:
            logger.error("'%s': %s", self.fetch_engine_name().upper(), err)
        except json.JSONDecodeError as err:
            logger.error("Failed to decode JSON response: %s", err)
        except OSError as err:
            logger.error("System error during TTS synthesis: %s", err)
        except TypeError as err:
            logger.error("'%s': %s", self.fetch_engine_name().upper(), err)
        except RuntimeError as err:
            logger.error("An error occurred in the TTS process: %s", err)

    @abstractmethod
    async def api_command_procedure(self, ttsparam: TTSParam) -> bytes:
        """Abstract method for handling the TTS API command procedure.

        This method should be implemented by subclasses to perform the actual
        TTS synthesis command procedure.

        Args:
            ttsparam (TTSParam): The parameters for the TTS synthesis.
        Returns:
            bytes: The synthesized audio data as bytes.
        """
        raise NotImplementedError

    @overload
    async def _api_request(
        self,
        method: str,
        url: str,
        *,
        model: type[T],
        params: dict[str, str] | None = ...,
        data: Any = ...,
        log_action: str = ...,
        total_timeout: float | None = ...,
        is_list: Literal[False] = False,
    ) -> T: ...

    @overload
    async def _api_request(
        self,
        method: str,
        url: str,
        *,
        model: type[T],
        params: dict[str, str] | None = ...,
        data: Any = ...,
        log_action: str = ...,
        total_timeout: float | None = ...,
        is_list: Literal[True],
    ) -> list[T]: ...

    @overload
    async def _api_request(
        self,
        method: str,
        url: str,
        *,
        model: None = None,
        params: dict[str, str] | None = ...,
        data: Any = ...,
        log_action: str = ...,
        total_timeout: float | None = ...,
        is_list: bool = ...,
    ) -> Any: ...

    async def _api_request(
        self,
        method: str,
        url: str,
        model: type[T] | None = None,
        params: dict[str, str] | None = None,
        data: Any = None,
        log_action: str = "",
        total_timeout: float | None = None,
        is_list: bool = False,  # noqa: FBT001, FBT002
    ) -> Any:
        """Make an asynchronous HTTP request to the TTS API.

        Args:
            method (str): The HTTP method to use (e.g., "get", "post").
            url (str): The URL to send the request to.
            model (type[T] | None): The model class to deserialize the response into.
            params (dict[str, str] | None): Query parameters for the request.
            data (Any): Data to send in the request body.
            log_action (str): Action name for logging purposes.
            total_timeout (float | None): Total timeout for the request.
            is_list (bool): Whether the response is expected to be a list of items.
        Returns:
            Any: The deserialized response data, which can be a single item, a list of items, or raw bytes.
        Raises:
            TTSCommunicationError: If the response data is invalid or if an error occurs during the request.
        """
        logger.info("'%s': '%s'", log_action or method.upper(), url)
        total_timeout = total_timeout if total_timeout is not None else self.timeout
        try:
            if method.lower() == "get":
                response = await self.async_http.get(url=url, total_timeout=total_timeout)
            elif method.lower() == "post":
                response = await self.async_http.post(url=url, params=params, data=data, total_timeout=total_timeout)
            else:
                msg = f"Unsupported HTTP method: {method}"
                raise ValueError(msg)

            if model is None:
                return response

            # Use infer_missing=True for compatibility with engines that omit optional fields
            if is_list:
                return [model.from_dict(item, infer_missing=True) for item in response]
            return model.from_dict(response, infer_missing=True)
        except (ValidationError, TypeError, AttributeError) as err:
            msg: str = f"The response data from the API is invalid: {err}"
            logger.error(msg)
            raise AsyncCommError(msg) from err
        except KeyError as err:
            msg: str = f"The response data from the API is missing expected fields: {err}"
            logger.error(msg)
            raise AsyncCommError(msg) from err

    def _convert_parameters(self, value: int | float | None, param_range: tuple[float, float, float]) -> float:  # noqa: PYI041
        """Convert and normalize TTS parameter value to float within specified range.

        Handles three input types:
        - int: Treated as percentage (divided by 100)
        - float: Used directly
        - None: Returns default value

        Args:
            value (int | float | None): The TTS parameter value to convert.
                - int values are divided by 100 (e.g., 100 -> 1.0, 150 -> 1.5)
                - float values are used directly
                - None returns the default value
            param_range (tuple[float, float, float]): (min_limit, max_limit, default_value).

        Returns:
            float: The normalized value clamped to [min_limit, max_limit], or default if value is None.
        """
        (lower_limit, upper_limit, default) = param_range

        if value is None:
            return default

        if lower_limit > upper_limit:
            lower_limit, upper_limit = upper_limit, lower_limit

        if isinstance(value, int):
            # Integer values represent percentage (100 = 1.0, 50 = 0.5)
            value = float(value) / 100.0
            return max(min(value, upper_limit), lower_limit)

        if isinstance(value, float):
            return max(min(value, upper_limit), lower_limit)

        logger.warning("Invalid type for value: %s, expected int or float", type(value).__name__)
        return default

    def _adjust_reading_speed(self, speed: float, message_length: int) -> float:
        """Adjust reading speed based on message length for natural pacing.

        When early_speech is enabled and message length exceeds 30 characters,
        applies a cubic polynomial adjustment to prevent unnaturally fast speech
        for longer messages. The adjustment factor is clamped to maximum 1.40x.

        Args:
            speed (float): The base reading speed multiplier.
            message_length (int): Length of the message in characters.

        Returns:
            float: The adjusted speed, or original speed if early_speech is disabled or length <= 30.
        """
        if self.earlyspeech and message_length > 30:
            logger.debug("Original speed value: '%.2f'", speed)
            # Cubic polynomial for smooth acceleration: 0.0000008*x^3 + 0.002*x + 1.0 (x = message_length - 30)
            speed = min(speed * (0.0000008 * (message_length - 30) ** 3.0 + 0.002 * (message_length - 30) + 1.0), 1.40)
            logger.debug("Accelerated speed value: '%.2f'", speed)
        return speed

    async def fetch_available_speakers(self) -> list[Speaker]:
        """Fetch available speakers from the TTS engine.

        Returns:
            list[Speaker]: List of available speakers with their styles and features.
        """
        speakers: list[Speaker] = await self._api_request(
            method="get",
            url=f"{self.url}/speakers",
            model=Speaker,
            is_list=True,
            log_action="GET speakers",
        )
        logger.debug("Available speakers: %s", speakers)
        return speakers

    def _get_speaker_id_from_cast(self, cast: str) -> int:
        """Retrieve speaker ID from cast string with caching.

        Supports three cast string formats with automatic caching for performance:
        1. Numeric ID: "0", "14" -> returns int directly
        2. Name|Style: "四国めたん|ノーマル" -> returns matching style ID
        3. Name only: "四国めたん" -> defaults to "ノーマル" style

        Results are cached to avoid repeated speaker list searches.

        Args:
            cast (str): The cast string in one of the supported formats.

        Returns:
            int: The speaker ID, or default_speaker_id if not found or cast is empty.
        """
        if not cast:
            logger.warning("Using default speaker ID because cast string is empty")
            return self.default_speaker_id

        if cast in self.id_cache:
            speaker_id: int = self.id_cache[cast]
            logger.debug("Retrieved cached speaker ID for cast '%s': %d", cast, speaker_id)
            return speaker_id

        if cast.isdecimal():
            self.id_cache[cast] = int(cast)
            return int(cast)

        name, style = cast.split("|", maxsplit=1) if "|" in cast else (cast, "")
        if not name:
            logger.warning("Using default speaker ID because speaker name is empty")
            self.id_cache[cast] = self.default_speaker_id
            return self.default_speaker_id

        if not style:
            style = "ノーマル"

        speaker: Speaker | None = next((s for s in self.available_speakers if s.name == name), None)
        if speaker:
            speaker_style: _SpeakerStyle | None = next((st for st in speaker.styles if st.name == style), None)
            if speaker_style:
                self.id_cache[cast] = speaker_style.id
                return speaker_style.id

        logger.warning("Using default speaker ID because speaker name '%s' or style '%s' not found", name, style)
        self.id_cache[cast] = self.default_speaker_id
        return self.default_speaker_id

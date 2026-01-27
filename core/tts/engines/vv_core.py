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
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from dataclasses_json import DataClassJsonMixin

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = ["VVCore"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

STARTUP_TIMEOUT: Final[float] = 10.0  # Timeout for TTS engine startup detection
RETRY_INTERVAL: Final[float] = 2.0  # Retry interval for checking TTS engine status

T = TypeVar("T", bound="DataClassJsonMixin")


class VVCore(Interface):
    # Parameter valid range and default values
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

    @staticmethod
    def fetch_engine_name() -> str:
        """Get the distinguished name of the TTS engine.

        Returns:
            str: The distinguished name of the TTS engine.
        """
        # return "vv_core"
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
        _ = param
        await self._detect_engine_startup()

    async def _detect_engine_startup(self) -> None:
        try:
            async with asyncio.timeout(STARTUP_TIMEOUT):
                while True:
                    try:
                        await self._api_request(
                            method="get",
                            url=self.url,
                            model=None,
                            log_action="GET",
                        )
                        logger.info("The TTS engine is running and can be accessed.")
                    except AsyncCommTimeoutError:
                        logger.debug("The TTS engine is not running. It will try again in %.1f second.", RETRY_INTERVAL)
                        await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying
                    else:
                        return  # Exit the loop if the engine is accessible
        except TimeoutError:
            msg = "The TTS engine is not running or is not accessible. Please check the server status."
            logger.error(msg)

    async def close(self) -> None:
        """Close the TTS engine and clean up resources."""
        await self.async_http.close()
        logger.info("%s process termination", self.__class__.__name__)

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        """Perform speech synthesis using the TTS parameters provided.

        Args:
            ttsparam (TTSParam): The parameters for the TTS synthesis.
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

            # Create the audio file path and save the audio data
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
            # This exception occurs if the API parameters have changed due to an update
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

    # This overload is for when a model is specified, returning a single item.
    # It is used for endpoints that return a single item, such as speaker details.
    # This is indicated by the `is_list` parameter being set to False.
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

    # This overload is for when a model is specified, returning a list of items.
    # It is used for endpoints that return multiple items, such as speaker lists.
    # This is indicated by the `is_list` parameter being set to True.
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

    # This overload is for when no model is specified, returning raw bytes.
    # It is used for endpoints that return audio data directly, such as synthesis endpoints.
    # In this case, the model parameter is None, and the return type is bytes.
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
    ) -> bytes: ...

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
                # If no model is specified, return the raw response.
                # Note: During engine initialization a GET returns text/html and a POST may return None.
                # Audio responses (audio/wav) are handled by callers that know the expected type.
                return response

            if is_list:
                return [model.from_dict(item) for item in response]
            return model.from_dict(response)
        except (ValidationError, TypeError, AttributeError) as err:
            msg: str = f"The response data from the API is invalid: {err}"
            raise AsyncCommError(msg) from err

    def _convert_parameters(self, value: int | float | None, param_range: tuple[float, float, float]) -> float:  # noqa: PYI041
        """Convert the TTS parameter value to a float within the specified range.

        Args:
            value (int | float | None): The TTS parameter value to convert.
            param_range (tuple[float, float, float]): A tuple containing the lower limit, upper limit,
                                                      and default value.
        Returns:
            float: The converted value within the specified range, or the default value if `value` is None.
        """
        (lower_limit, upper_limit, default) = param_range

        if value is None:
            return default

        if lower_limit > upper_limit:
            lower_limit, upper_limit = upper_limit, lower_limit

        if isinstance(value, int):
            # For an int type, the value is multiplied by 100.
            value = float(value) / 100.0
            return max(min(value, upper_limit), lower_limit)

        if isinstance(value, float):
            return max(min(value, upper_limit), lower_limit)

        logger.warning("Invalid type for value: %s, expected int or float", type(value).__name__)
        return default

    def _adjust_reading_speed(self, speed: float, message_length: int) -> float:
        """Adjust the reading speed based on the message length.

        Args:
            speed (float): The original reading speed.
            message_length (int): The length of the message in characters.
        Returns:
            float: The adjusted reading speed.
        """
        # If the text exceeds 30 characters, the speed will adjust accordingly
        if self.earlyspeech and message_length > 30:
            logger.debug("Original speed value: '%.2f'", speed)
            speed = min(speed * (0.0000008 * (message_length - 30) ** 3.0 + 0.002 * (message_length - 30) + 1.0), 1.40)
            logger.debug("Accelerated speed value: '%.2f'", speed)
        return speed

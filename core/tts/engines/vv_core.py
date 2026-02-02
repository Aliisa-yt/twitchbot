"""Base class for VOICEVOX-compatible text-to-speech engines.

Provides core functionality for VOICEVOX API communication, including audio query generation,
speaker management, and parameter conversion. Subclasses implement api_command_procedure().
"""

from __future__ import annotations

import asyncio
import json
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple, TypeVar, overload

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


__all__: list[str] = ["SpeakerID", "VVCore"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

RETRY_INTERVAL: Final[float] = 2.0  # Interval between retries when checking engine status
ENGINE_INITIALIZATION_TIMEOUT: Final[float] = RETRY_INTERVAL * 6 + 0.5  # Total timeout for engine initialization

T = TypeVar("T", bound="DataClassJsonMixin")


class SpeakerID(NamedTuple):
    uuid: str
    style_id: int


class VVCore(Interface):
    """Base class for VOICEVOX-compatible text-to-speech engines.

    Provides core functionality for VOICEVOX API communication, including audio query
    generation, speaker management, and parameter conversion.
    Subclasses implement api_command_procedure() for engine-specific synthesis.

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

        Sets up HTTP client, session, audio handler, and speaker cache.
        """
        logger.debug("%s initializing", self.__class__.__name__)
        super().__init__()
        self.async_http = AsyncHttp()
        self.async_http.initialize_session()
        self.async_http.add_handler("audio/wav", lambda raw: raw)
        self._id_cache: dict[str, SpeakerID] = {}
        self._check_status_command: str = "/version"

    @property
    def id_cache(self) -> dict[str, SpeakerID]:
        """Get the internal speaker ID cache.

        Returns:
            dict[str, SpeakerID]: Mapping of cast strings to speaker IDs.
        """
        return self._id_cache

    @staticmethod
    def fetch_engine_name() -> str:
        """Get the engine identifier.

        Returns:
            str: Empty string (to be overridden by subclasses).
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

        Waits for engine startup before returning.

        Args:
            param (UserTypeInfo): User-specific voice configuration.
        """
        _ = param
        await self._detect_engine_startup()

    @property
    def check_status_command(self) -> str:
        """Get the command to check TTS engine startup status.

        Returns:
            str: The command string to check engine status.
        """
        return self._check_status_command

    @check_status_command.setter
    def check_status_command(self, value: str) -> None:
        """Set the command to check TTS engine startup status.

        This command verifies whether the TTS engine can be controlled externally.
        Therefore, any command without side effects will suffice.

        Args:
            value (str): The command string to set.
        """
        self._check_status_command = value

    async def _detect_engine_startup(self) -> None:
        """Wait for TTS engine to be accessible with retries.

        Polls the version endpoint until accessible within ENGINE_INITIALIZATION_TIMEOUT.
        Logs errors if engine is not accessible after timeout.
        """
        try:
            async with asyncio.timeout(ENGINE_INITIALIZATION_TIMEOUT):
                while True:
                    try:
                        version: str = await self._api_request(
                            method="get",
                            url=f"{self.url}{self.check_status_command}",
                            model=None,
                            log_action="Startup status check",
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
        """Perform text-to-speech synthesis and queue playback.

        Synthesizes audio via api_command_procedure(), saves to file, and triggers playback.
        Catches and logs all exceptions without re-raising.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters.
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
        """Execute TTS API request to synthesize audio.

        Must be implemented by subclasses.

        Args:
            ttsparam (TTSParam): Text-to-speech parameters.

        Returns:
            bytes: Synthesized audio data.
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
            method (str): HTTP method ("get" or "post").
            url (str): Request URL.
            model (type[T] | None): Model class for deserialization.
            params (dict[str, str] | None): Query parameters.
            data (Any): Request body data.
            log_action (str): Action name for logging.
            total_timeout (float | None): Request timeout.
            is_list (bool): Whether response is a list.
        Returns:
            Any: Deserialized response (single item, list, or raw bytes).
        Raises:
            AsyncCommError: If response is invalid or request fails.
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
        """Convert and normalize TTS parameter value to float.

        Converts int as percentage (int/100), uses float directly, returns default for None.
        Clamps result to [min_limit, max_limit].

        Args:
            value (int | float | None): Parameter value (int as percentage, None for default).
            param_range (tuple[float, float, float]): (min, max, default).

        Returns:
            float: Normalized value clamped to range.
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

        When earlyspeech is enabled and message length > 30, applies cubic polynomial
        adjustment (clamped to max 1.40x).

        Args:
            speed (float): Base reading speed multiplier.
            message_length (int): Message length in characters.

        Returns:
            float: Adjusted speed, or original if earlyspeech disabled or length <= 30.
        """
        if self.earlyspeech and message_length > 30:
            logger.debug("Original speed value: '%.2f'", speed)
            # Cubic polynomial for smooth acceleration: 0.0000008*x^3 + 0.002*x + 1.0 (x = message_length - 30)
            speed_factor: float = 0.0000008 * (message_length - 30) ** 3.0 + 0.002 * (message_length - 30) + 1.0
            speed = min(speed * speed_factor, 1.40)
            logger.debug("Accelerated speed value: '%.2f'", speed)
        return speed

    def get_speaker_id_from_cast(self, cast: str, available_speakers: dict[str, dict[str, SpeakerID]]) -> SpeakerID:
        """Retrieve speaker ID from cast string with caching.

        Supports three formats:
        1. Numeric ID: "0", "14"
        2. Name|Style: "四国めたん|ノーマル"
        3. Name only: "四国めたん" (defaults to "ノーマル")

        Results are cached for performance.

        Args:
            cast (str): Cast string in supported format.

        Returns:
            SpeakerID: Speaker ID, or default_speaker_id if not found or cast empty.
        """

        def default_speaker_id() -> SpeakerID:
            """Get the default speaker ID.

            Returns:
                SpeakerID: The default speaker ID.
            """
            default_value = SpeakerID(uuid="", style_id=0)
            if not available_speakers:
                logger.warning("No available speakers found, defaulting to speaker ID 0")
                return default_value
            return next(iter(available_speakers.values())).get("ノーマル", default_value)

        if not cast:
            logger.warning("Using default speaker ID because cast string is empty")
            return default_speaker_id()

        if cast in self.id_cache:
            cached_id: SpeakerID = self.id_cache[cast]
            logger.debug("Retrieved cached speaker ID for cast '%s': %s", cast, cached_id)
            return cached_id

        if cast.isdecimal():
            logger.debug("Using numeric speaker ID from cast '%s'", cast)
            style_id = int(cast)
            uuid: str = self.get_speaker_uuid_from_style_id(style_id, available_speakers)
            speaker_id: SpeakerID = SpeakerID(uuid=uuid, style_id=style_id)
            self.id_cache[cast] = speaker_id
            return speaker_id

        name, style = cast.split("|", maxsplit=1) if "|" in cast else (cast, "")
        if not name:
            logger.warning("Using default speaker ID because speaker name is empty")
            speaker_id: SpeakerID = default_speaker_id()
            self.id_cache[cast] = speaker_id
            return speaker_id

        if not style:
            style = "ノーマル"

        speaker_style_id: SpeakerID | None = available_speakers.get(name, {}).get(style)

        if speaker_style_id is not None:
            self.id_cache[cast] = speaker_style_id
            return speaker_style_id

        logger.warning("Using default speaker ID because speaker name '%s' or style '%s' not found", name, style)
        speaker_id: SpeakerID = default_speaker_id()
        self.id_cache[cast] = speaker_id
        return speaker_id

    def get_speaker_name_from_style_id(self, style_id: int, available_speakers: dict[str, dict[str, SpeakerID]]) -> str:
        """Retrieve speaker name from style ID.

        Searches available_speakers to find the speaker name and style corresponding to the given style_id.

        Args:
            style_id (int): The style ID to search for.
            available_speakers (dict[str, dict[str, SpeakerID]]): Speaker information organized by name and style.

        Returns:
            str: Speaker name and style in format "name|style", or empty string if not found.
        """
        for speaker_name, styles in available_speakers.items():
            for style_name, speaker_id in styles.items():
                if speaker_id.style_id == style_id:
                    logger.debug(
                        "Found speaker '%s' with style '%s' for style_id %d", speaker_name, style_name, style_id
                    )
                    return f"{speaker_name}|{style_name}"
        logger.warning("No speaker found for style_id %d", style_id)
        return ""

    def get_speaker_uuid_from_style_id(self, style_id: int, available_speakers: dict[str, dict[str, SpeakerID]]) -> str:
        """Retrieve speaker UUID from style ID.

        Searches available_speakers to find the UUID corresponding to the given style_id.

        Args:
            style_id (int): The style ID to search for.
            available_speakers (dict[str, dict[str, SpeakerID]]): Speaker information organized by name and style.

        Returns:
            str: Speaker UUID, or empty string if not found.
        """
        for speaker_name, styles in available_speakers.items():
            for style_name, speaker_id in styles.items():
                if speaker_id.style_id == style_id:
                    logger.debug(
                        "Found UUID '%s' for style_id %d (speaker: '%s', style: '%s')",
                        speaker_id.uuid,
                        style_id,
                        speaker_name,
                        style_name,
                    )
                    return speaker_id.uuid
        logger.warning("No UUID found for style_id %d, returning empty string", style_id)
        return ""

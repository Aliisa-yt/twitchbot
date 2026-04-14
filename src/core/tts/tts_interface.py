import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar, Final, override

from core.tts._tts_engine_config import (
    DEFAULT_PORT_RANGE,
    DEFAULT_PROTOCOL,
    DEFAULT_TIMEOUT,
    TTSConfig,
    TTSExceptionError,
    protocol_type,
)
from core.tts._tts_process_mixin import ProcessMixin
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = [
    "DEFAULT_PORT_RANGE",
    "DEFAULT_PROTOCOL",
    "DEFAULT_TIMEOUT",
    "EngineContext",
    "EngineHandler",
    "Interface",
    "TTSConfig",
    "TTSExceptionError",
    "TTSFileCreateError",
    "TTSFileError",
    "TTSFileExistsError",
    "TTSNotSupportedError",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# Supported audio formats
SUPPORTED_FORMATS: Final[list[str]] = ["wav", "mp3"]


class TTSFileError(TTSExceptionError):
    """Parent class of file operation related exceptions.

    This class is used for exceptions related to file operations in TTS engines.
    It inherits from TTSExceptionError and provides a base for file-related exceptions.
    """


class TTSFileExistsError(TTSFileError):
    """File used by TTS already exists.

    This exception is raised when attempting to create a file that already exists.
    It inherits from TTSFileError and provides a specific error for file existence conflicts.
    """


class TTSFileCreateError(TTSFileError):
    """File creation by TTS failed.

    This exception is raised when the TTS engine fails to create a file.
    It inherits from TTSFileError and provides a specific error for file creation failures.
    """


class TTSNotSupportedError(TTSExceptionError):
    """Passed parameters not supported by TTS.

    This exception is raised when the parameters passed to the TTS engine are not supported.
    It inherits from TTSExceptionError and provides a specific error for unsupported parameters.
    """


@dataclass(frozen=True)
class EngineHandler:
    """Handler for TTS engine operations

    This class provides methods for executing TTS engine operations, including initialization,
    speech synthesis, and process termination.

    Attributes:
        execute (Callable[[], Awaitable[None]]): Method to execute the TTS engine
        ainit (Callable[[UserTypeInfo], Awaitable[None]]): Method for asynchronous initialization
        synthesis (Callable[[TTSParam], Awaitable[None]]): Method for speech synthesis
        close (Callable[[], Awaitable[None]]): Method to close the TTS engine
        termination (Callable[[], Awaitable[None]]): Method to terminate the TTS engine process
    """

    execute: Callable[[], Awaitable[None]]
    ainit: Callable[[UserTypeInfo], Awaitable[None]]
    synthesis: Callable[[TTSParam], Awaitable[None]]
    close: Callable[[], Awaitable[None]]
    termination: Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class EngineContext:
    """Runtime context passed to each TTS engine at initialization.

    Attributes:
        audio_save_directory (Path): Directory where audio files are saved.
        play_callback (Callable[[TTSParam], Awaitable[None]]):
            Coroutine to enqueue a synthesized TTSParam for playback.
    """

    audio_save_directory: Path
    play_callback: Callable[[TTSParam], Awaitable[None]]


class Interface(ProcessMixin, ABC):
    """Base class for TTS engine interface

    This class defines the interface for TTS engines, including methods for initialization,
    speech synthesis, and audio playback.
    It also provides methods for managing TTS parameters and audio file handling.

    Attributes:
        process (asyncio.subprocess.Process | None): The subprocess running the TTS engine.

    Properties:
        protocol (protocol_type): The protocol used by the TTS engine (e.g., "http", "https").
        host (str): The host address of the TTS engine.
        port (int): The port number on which the TTS engine is listening.
        url (str): The full URL of the TTS engine (constructed from protocol, host, and port).
        address (tuple[str, int]): The host and port as a tuple.
        timeout (float): The timeout duration for TTS engine operations.
        earlyspeech (bool): Whether the TTS engine supports early speech playback.
        linkedstartup (bool): Whether the TTS engine should be started with the main application.
        exec_path (Path | None): The file path to the TTS engine executable, if applicable.
    """

    _registered_engines: ClassVar[dict[str, type[Interface]]] = {}

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self._tts_config: TTSConfig = TTSConfig()
        self._context: EngineContext | None = None

    async def async_init(self, _param: UserTypeInfo) -> None:
        """Asynchronous initialization process (override if necessary)

        This method is called after the TTS engine is started and the process is ready to accept requests.
        It is used to set up the internal state of the TTS engine.
        Args:
            _param (UserTypeInfo): User type information
        """
        logger.info("%s process initialised", self.__class__.__name__)

    async def close(self) -> None:
        """Termination process (override if necessary)"""
        logger.info("%s process termination", self.__class__.__name__)

    @property
    def audio_save_directory(self) -> Path:
        """Get the base directory for saving audio files."""
        if self._context is None:
            msg = "Engine context is not initialized. Call initialize_engine() first."
            raise RuntimeError(msg)
        return self._context.audio_save_directory

    @property
    def play_callback(self) -> Callable[[TTSParam], Awaitable[None]]:
        """Get the audio playback callback function."""
        if self._context is None:
            msg = "Engine context is not initialized. Call initialize_engine() first."
            raise RuntimeError(msg)
        return self._context.play_callback

    @property
    def handler(self) -> EngineHandler:
        return EngineHandler(
            execute=self._execute,
            ainit=self.async_init,
            synthesis=self.speech_synthesis,
            close=self.close,
            termination=self._kill,
        )

    @classmethod
    def get_registered(cls) -> dict[str, type[Interface]]:
        """Get all registered TTS engine classes"""
        return cls._registered_engines

    @classmethod
    def register_engine(cls, engine_cls: type[Interface]) -> None:
        """Register a new TTS engine class"""
        name: str = engine_cls.fetch_engine_name()
        if not issubclass(engine_cls, cls):
            msg = "Must be a subclass of Interface"
            raise TypeError(msg)
        cls._registered_engines[name] = engine_cls
        logger.debug("Registered engine: %s", name)

    @classmethod
    def get_engine(cls, name: str) -> type[Interface]:
        """Retrieve a registered engine class by name"""
        try:
            return cls._registered_engines[name]
        except KeyError:
            msg: str = f"No such engine registered: {name}"
            raise ValueError(msg) from None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.register_engine(cls)
        # Although it appears possible to register subclass information with '__init__',
        # '__init__' is called using subclass information registered with '__init_subclass__'.
        # Therefore '__init_subclass__' must be used.

    @abstractmethod
    def initialize_engine(self, tts_engine: TTSEngine, context: EngineContext) -> bool:
        """Initialize the TTS engine with the given configuration and runtime context.

        This method is called when the TTS engine is started.
        It reads the configuration from the TTSEngine model and sets up the TTS engine accordingly.
        This method must be implemented by subclasses.

        Args:
            tts_engine (TTSEngine): Configuration for the TTS engine.
            context (EngineContext): Runtime context containing audio directory and playback callback.
        Returns:
            bool: True if initialization is successful, False otherwise.
        """
        self._tts_config = TTSConfig.from_config(tts_engine)
        self._context = context
        return True

    @property
    def protocol(self) -> protocol_type:
        return self._tts_config.protocol

    @property
    def host(self) -> str:
        return self._tts_config.host

    @property
    def port(self) -> int:
        return self._tts_config.port

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def address(self) -> tuple[str, int]:
        return (self.host, self.port)

    @property
    def timeout(self) -> float:
        return self._tts_config.timeout

    @property
    def earlyspeech(self) -> bool:
        return self._tts_config.earlyspeech

    @property
    @override
    def linkedstartup(self) -> bool:
        return self._tts_config.linkedstartup

    @property
    @override
    def exec_path(self) -> Path | None:
        return self._tts_config.exec_path

    @staticmethod
    @abstractmethod
    def fetch_engine_name() -> str:
        """Get the distinguished name of the TTS engine.

        Returns:
            str: The distinguished name of the TTS engine.
        """
        raise NotImplementedError

    @abstractmethod
    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        """Asynchronous method to process speech synthesis requests

        Args:
            ttsparam (TTSParam):
                TTSParam: Parameters required for speech synthesis

        Raises:
            NotImplementedError: This is a required method and must be overridden
        """
        raise NotImplementedError

    def create_audio_filename(self, *, prefix: str | None = None, suffix: str = "wav") -> Path:
        """Create a unique audio file name

        This method generates a unique file name for audio files based on the TTS engine name and a UUID.
        The file name will be in the format: "{prefix}_{unique_identifier}.{suffix}".

        Args:
            prefix (str | None): Prefix for the file name. If None, the engine name is used.
            suffix (str): File extension (default is "wav")
        Returns:
            Path: Path object representing the unique audio file name
        Raises:
            TTSNotSupportedError: If the suffix is not a supported audio format
        """
        if suffix.lower() not in SUPPORTED_FORMATS:
            msg: str = f"'{suffix}' is an unsupported audio format"
            raise TTSNotSupportedError(msg)

        prefix = prefix or self.fetch_engine_name()
        unique_identifier: str = "{" + str(uuid.uuid4()) + "}"

        return self.audio_save_directory.joinpath(f"{prefix}_{unique_identifier}.{suffix}")

    def save_audio_file(self, filepath: Path, data: bytes | BytesIO) -> None:
        """Save audio data to a file

        This method saves the given audio data to the specified file path.

        Args:
            filepath (Path): Path to the file where the audio data will be saved
            data (bytes | BytesIO): Audio data to be saved
        Raises:
            TTSFileExistsError: If the file already exists
            TTSFileCreateError: If there is an error creating the file
            TTSNotSupportedError: If the data format is not supported
        """
        if isinstance(data, BytesIO):
            data = data.getvalue()
        elif not isinstance(data, bytes):
            msg: str = f"Data format not supported. type='{type(data)}'"
            raise TTSNotSupportedError(msg)

        try:
            with filepath.open(mode="xb") as fhdl:
                fhdl.write(data)
                fhdl.flush()
        except FileExistsError as err:
            msg = f"File already exists: '{filepath}'"
            raise TTSFileExistsError(msg) from err
        except PermissionError as err:
            msg = f"Permission denied: '{filepath}'"
            raise TTSFileCreateError(msg) from err
        except OSError as err:
            msg = f"Could not create file: '{filepath}'"
            raise TTSFileCreateError(msg) from err

    async def play(self, ttsparam: TTSParam) -> None:
        """Add audio playback request to the playback queue.

        Args:
            ttsparam (TTSParam): Parameters required for audio generation.
        Raises:
            RuntimeError: If the engine context is not initialized.
        """
        if self._context is None:
            msg = "Engine context is not initialized. Call initialize_engine() first."
            raise RuntimeError(msg)
        await self._context.play_callback(ttsparam)

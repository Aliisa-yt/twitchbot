from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final

from core.tts._tts_engine_config import (
    DEFAULT_PORT_RANGE,
    DEFAULT_PROTOCOL,
    DEFAULT_TIMEOUT,
    TTSExceptionError,
    _TTSConfig,
    protocol_type,
)
from core.tts._tts_process_mixin import ProcessMixin
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Awaitable, Callable

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = [
    "DEFAULT_PORT_RANGE",
    "DEFAULT_PROTOCOL",
    "DEFAULT_TIMEOUT",
    "EngineHandler",
    "Interface",
    "TTSExceptionError",
    "TTSFileCreateError",
    "TTSFileError",
    "TTSFileExistsError",
    "TTSNotSupportedError",
    "_TTSConfig",
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


class Interface(ProcessMixin, ABC):
    """Base class for TTS engine interface

    This class defines the interface for TTS engines, including methods for initialization,
    speech synthesis, and audio playback.
    It also provides methods for managing TTS parameters and audio file handling.

    Attributes:
        _registered_engines (dict[str, type[Interface]]): Dictionary of registered TTS engine classes
        _play_callback (Callable[[TTSParam], Awaitable[None]]):
            Callback function for audio playback
        _base_directory (Path): Base directory for saving audio files
    """

    _registered_engines: ClassVar[dict[str, type[Interface]]] = {}
    _play_callback: ClassVar[Callable[[TTSParam], Awaitable[None]]]
    _base_directory: ClassVar[Path | None] = None

    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.__tts_config: _TTSConfig = _TTSConfig()

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
        """Get the base directory for saving audio files"""
        if Interface._base_directory is None:
            msg = "Base directory is not set"
            raise RuntimeError(msg)
        return Interface._base_directory

    @audio_save_directory.setter
    def audio_save_directory(self, path: Path | None) -> None:
        """Set the base directory for saving audio files (can only be set once)"""
        if path is None or not isinstance(path, Path):
            msg = f"Expected 'path' to be of type Path, got {type(path)}"
            raise TypeError(msg)

        if not path.is_dir():
            msg = f"'{path}' is not a directory"
            raise ValueError(msg)

        if Interface._base_directory is not None:
            msg = "'base_directory' is already set and cannot be changed"
            raise RuntimeError(msg)

        Interface._base_directory = path
        logger.debug("Base directory set to: %s", path)

    @property
    def play_callback(self) -> Callable[[TTSParam], Awaitable[None]]:
        """Get the audio playback callback function"""
        if not hasattr(Interface, "_play_callback"):
            msg = "Play callback is not set"
            raise RuntimeError(msg)
        return Interface._play_callback

    @play_callback.setter
    def play_callback(self, callback: Callable[[TTSParam], Awaitable[None]]) -> None:
        """Set the audio playback callback function (can only be set once)"""
        if not callable(callback):
            msg = "Play callback must be a callable"
            raise TypeError(msg)
        if hasattr(Interface, "_play_callback"):
            msg = "Play callback is already set and cannot be changed"
            raise RuntimeError(msg)
        Interface._play_callback = callback

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

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls.register_engine(cls)
        # Although it appears possible to register subclass information with '__init__',
        # '__init__' is called using subclass information registered with '__init_subclass__'.
        # Therefore '__init_subclass__' must be used.

    @abstractmethod
    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        """Initialize the TTS engine with the given configuration

        This method is called when the TTS engine is started.
        It reads the configuration from the TTSEngine model and sets up the TTS engine accordingly.
        This method must be implemented by subclasses.

        Args:
            tts_engine (TTSEngine): Configuration for the TTS engine
        Returns:
            bool: True if initialization is successful, False otherwise
        """
        self.__tts_config = _TTSConfig.from_config(tts_engine)
        return True

    @property
    def protocol(self) -> protocol_type:
        return self.__tts_config.protocol

    @property
    def host(self) -> str:
        return self.__tts_config.host

    @property
    def port(self) -> int:
        return self.__tts_config.port

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}"

    @property
    def address(self) -> tuple[str, int]:
        return (self.host, self.port)

    @property
    def timeout(self) -> float:
        return self.__tts_config.timeout

    @property
    def earlyspeech(self) -> bool:
        return self.__tts_config.earlyspeech

    @property
    def linkedstartup(self) -> bool:
        return self.__tts_config.linkedstartup

    @property
    def exec_path(self) -> Path | None:
        return self.__tts_config.exec_path

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
        """Add audio playback request to the playback queue

        Args:
            ttsparam (TTSParam): Parameters required for audio generation (only the file path is actually used)
        Raises:
            RuntimeError: If the play callback is not set
        """
        if not hasattr(Interface, "play_callback"):
            msg = "Play callback is not set"
            raise RuntimeError(msg)
        await self.play_callback(ttsparam)

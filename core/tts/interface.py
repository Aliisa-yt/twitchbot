from __future__ import annotations

import asyncio
import contextlib
import os
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Self, cast

from models.re_models import SERVER_CONFIG_PATTERN
from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable
    from re import Match

    from models.config_models import TTSEngine
    from models.voice_models import TTSParam, UserTypeInfo


__all__: list[str] = [
    "EngineHandler",
    "Interface",
    "TTSExceptionError",
    "TTSFileCreateError",
    "TTSFileError",
    "TTSFileExistsError",
    "TTSNotSupportedError",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

WINDOWS: Final[bool] = os.name == "nt"
KILL_TIMEOUT: Final[float] = 3.0  # Timeout for process termination

protocol_type = Literal["http", "https"]

DEFAULT_PROTOCOL: Final[protocol_type] = "http"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 65535
DEFAULT_TIMEOUT: Final[float] = 10.0

# Port range for TTS server
# The default range is 49152-65535, which is the range for dynamic/private ports
DEFAULT_PORT_RANGE: Final[tuple[int, int]] = (49152, 65535)
# Supported audio formats
SUPPORTED_FORMATS: Final[list[str]] = ["wav", "mp3"]


class TTSExceptionError(Exception):
    """Base class for TTS exceptions.

    This class is used as a base for all exceptions related to TTS operations.
    It inherits from the built-in Exception class and does not add any additional functionality.
    It serves as a common parent class for more specific TTS-related exceptions.
    """


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


@dataclass
class _TTSConfig:
    """Configuration for TTS engine

    This class holds the configuration settings for a TTS engine, including server settings,
    timeout, early speech, linked startup, and executable path.

    Attributes:
        protocol (protocol_type): Protocol used for the TTS server (http or https)
        host (str): Host address of the TTS server
        port (int): Port number of the TTS server
        timeout (float): Timeout for TTS requests in seconds
        earlyspeech (bool): Whether early speech is enabled
        linkedstartup (bool): Whether linked startup is enabled
        exec_path (Path | None): Path to the TTS engine executable
    """

    protocol: protocol_type = DEFAULT_PROTOCOL
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT
    earlyspeech: bool = False
    linkedstartup: bool = False
    exec_path: Path | None = None

    @classmethod
    def from_config(cls, tts_engine: TTSEngine) -> _TTSConfig:
        """Create a TTSConfig instance from TTSEngine configuration.

        Reads the configuration from the TTSEngine model and initializes a _TTSConfig instance.
        """
        tts_config: Self = cls()
        # SERVER setting
        server_str: str | None = getattr(tts_engine, "SERVER", None)
        if server_str:
            try:
                tts_config.protocol, tts_config.host, tts_config.port = cls._parse_server_config(server_str)
            except TTSExceptionError as err:
                logger.error("Invalid server configuration: %s", err)
                raise

        # TIMEOUT setting
        tts_config.timeout = cls._parse_timeout(getattr(tts_engine, "TIMEOUT", DEFAULT_TIMEOUT))

        # Other settings
        tts_config.earlyspeech = getattr(tts_engine, "EARLY_SPEECH", False)
        tts_config.linkedstartup = getattr(tts_engine, "AUTO_STARTUP", False)

        exec_path_str: str | None = getattr(tts_engine, "EXECUTE_PATH", None)
        if exec_path_str:
            tts_config.exec_path = FileUtils.resolve_path(exec_path_str)

        return tts_config

    @staticmethod
    def _parse_server_config(
        server_str: str, port_range: tuple[int, int] = DEFAULT_PORT_RANGE
    ) -> tuple[protocol_type, str, int]:
        """Parse server settings and retrieve host and port"""
        try:
            match: Match[str] | None = re.match(SERVER_CONFIG_PATTERN, server_str)
            if not match:
                msg = "Invalid server configuration format."
                raise ValueError(msg)

            protocol_str: str = match.group("protocol")
            host: str = match.group("host")
            port: int = int(match.group("port"))

            if protocol_str:
                if protocol_str not in ("http", "https"):
                    msg: str = f"Invalid protocol '{protocol_str}'. Expected 'http' or 'https'."
                    raise ValueError(msg)
            else:
                protocol_str = DEFAULT_PROTOCOL

            protocol: protocol_type = cast("protocol_type", protocol_str.lower())

            if not (port_range[0] <= port <= port_range[1]):
                msg: str = f"Port number must be in range {port_range}."
                raise ValueError(msg)
        except (ValueError, TypeError) as err:
            msg: str = "Invalid server configuration."
            raise TTSExceptionError(msg) from err
        else:
            return protocol, host, port

    @staticmethod
    def _parse_timeout(timeout_value: float) -> float:
        """Parse timeout value and retrieve the appropriate value"""
        try:
            timeout: float = float(timeout_value)
            if timeout <= 0:
                error_message = "Timeout must be a positive number."
                raise ValueError(error_message)
        except ValueError:
            logger.warning("Invalid timeout setting; using default value %s", DEFAULT_TIMEOUT)
            return DEFAULT_TIMEOUT
        else:
            return timeout


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


class Interface(ABC):
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

    process: asyncio.subprocess.Process | None

    def __init__(self) -> None:
        self.process = None
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
            msg: str = f"Expected 'path' to be of type Path, got {type(path)}"
            raise TypeError(msg)

        if not path.is_dir():
            msg: str = f"'{path}' is not a directory"
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

    async def _execute(self) -> None:
        """Asynchronously start an external process if linked startup setting is enabled

        This method is invoked when the TTS engine starts up.
        If the linked startup setting is enabled, it attempts to start the executable specified in the
        exec_path variable. If exec_path is not set or the file does not exist, an error is logged.
        If the process starts successfully, the subprocess object is assigned to self.process.
        If the linked startup setting is disabled, this method does nothing.
        """
        if self.linkedstartup and self.exec_path is not None:
            try:
                self.process = await asyncio.create_subprocess_exec(
                    str(self.exec_path), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                logger.debug("Execution '%s' started successfully.", self.exec_path)
            except FileNotFoundError:
                logger.error("Executable file not found: '%s'", self.exec_path)
            except OSError as err:
                logger.error("Failed to execute file '%s': %s", self.exec_path, err)

    async def _kill(self) -> None:
        """Asynchronously terminate the process started with linked startup.

        If the process does not exit within the timeout period, it will be terminated forcefully.
        This method is invoked when the TTS engine is shut down.
        If the process is not running, the method simply returns.
        """
        if not (self.linkedstartup and self.process):
            return

        # Attempt to terminate the process gracefully
        with contextlib.suppress(ProcessLookupError):
            try:
                logger.info("Terminating process %s", self.process.pid)
                self.process.terminate()
            except PermissionError as exc:
                logger.error("Failed to terminate process %s: %s", self.process.pid, exc)
                return

        if await self._wait_for_exit(KILL_TIMEOUT):
            self._cleanup()
            return

        if WINDOWS:
            # In Windows, the terminate() and kill() functions perform the same operation,
            # meaning the two-step termination process is not required.
            logger.error("Timeout while terminating process %s on Windows", self.process.pid)
            self._cleanup()
            return

        # If the process did not exit within the timeout, force kill it
        with contextlib.suppress(ProcessLookupError):
            try:
                logger.warning("Termination timed out; force killing process %s", self.process.pid)
                self.process.kill()
            except PermissionError as exc:
                logger.error("Failed to force kill process %s: %s", self.process.pid, exc)
                self._cleanup()
                return

        if not await self._wait_for_exit(KILL_TIMEOUT):
            logger.error("Force kill also timed out for process %s", self.process.pid)

        self._cleanup()

    def _cleanup(self) -> None:
        """Cleanup after process termination"""
        self.process = None

    async def _wait_for_exit(self, wait_timeout: float) -> bool:
        """Wait for the process to exit.

        Args:
            wait_timeout (float): Timeout in seconds to wait for the process to exit.

        Returns:
            bool: True if the process exited within the timeout, False otherwise.
        """
        if not self.process:
            logger.debug("No process to wait for exit")
            return True

        try:
            await asyncio.wait_for(self.process.wait(), timeout=wait_timeout)
        except TimeoutError:
            return False
        else:
            return True

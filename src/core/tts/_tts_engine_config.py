"""TTS engine configuration parsing module.

Defines the _TTSConfig dataclass that holds and parses TTS engine settings
(server, timeout, startup path, etc.) and TTSExceptionError as the base exception class.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from models.re_models import SERVER_CONFIG_PATTERN
from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path
    from re import Match

    from models.config_models import TTSEngine


__all__: list[str] = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "DEFAULT_PORT_RANGE",
    "DEFAULT_PROTOCOL",
    "DEFAULT_TIMEOUT",
    "TTSExceptionError",
    "_TTSConfig",
    "protocol_type",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

protocol_type = Literal["http", "https"]

DEFAULT_PROTOCOL: Final[protocol_type] = "http"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 65535
DEFAULT_TIMEOUT: Final[float] = 10.0

# TTS server port range (dynamic/private ports: 49152-65535)
DEFAULT_PORT_RANGE: Final[tuple[int, int]] = (49152, 65535)


class TTSExceptionError(Exception):
    """Base class for all TTS-related exceptions."""


@dataclass
class _TTSConfig:
    """Dataclass holding TTS engine configuration.

    Attributes:
        protocol (protocol_type): Protocol for the TTS server (http or https).
        host (str): Host address of the TTS server.
        port (int): Port number of the TTS server.
        timeout (float): Request timeout in seconds.
        earlyspeech (bool): Whether early speech mode is enabled.
        linkedstartup (bool): Whether linked startup is enabled.
        exec_path (Path | None): Path to the TTS engine executable.
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
        """Create a _TTSConfig instance from a TTSEngine configuration object.

        Reads settings from the TTSEngine model and initialises a _TTSConfig instance.
        """
        tts_config: _TTSConfig = cls()
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
        """Parse a server configuration string and return the protocol, host, and port."""
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
                    msg = f"Invalid protocol '{protocol_str}'. Expected 'http' or 'https'."
                    raise ValueError(msg)
            else:
                protocol_str = DEFAULT_PROTOCOL

            protocol: protocol_type = cast("protocol_type", protocol_str.lower())

            if not (port_range[0] <= port <= port_range[1]):
                msg = f"Port number must be in range {port_range}."
                raise ValueError(msg)
        except (ValueError, TypeError) as err:
            msg = "Invalid server configuration."
            raise TTSExceptionError(msg) from err
        else:
            return protocol, host, port

    @staticmethod
    def _parse_timeout(timeout_value: float) -> float:
        """Parse a timeout value and return a valid positive float, falling back to the default."""
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

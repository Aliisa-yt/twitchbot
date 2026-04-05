from __future__ import annotations

import logging
import sys
import warnings
from logging import Formatter, NullHandler, StreamHandler
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING, ClassVar, Final, Literal, NamedTuple, Self, TextIO

if TYPE_CHECKING:
    from pathlib import Path

__all__: list[str] = ["LoggerUtils"]

type LevelType = Literal[
    "NOTSET",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]

_LOG_FILE_SIZE: Final[int] = 2 * 1024 * 1024  # 2MB
_LOG_BACKUP_COUNT: Final[int] = 2  # Number of backup files to keep

DEFAULT_LOG_LEVEL: Final[int] = logging.INFO
DEFAULT_NAMESPACE: Final[str] = "TwitchBot"


class LogLevel(NamedTuple):
    """Represents a logging level with both name and numeric value.

    Attributes:
        name (str): The name of the logging level (e.g., 'INFO', 'DEBUG').
        value (int): The numeric value of the logging level.
    """

    name: str
    value: int


class LoggerUtils:
    """LoggerUtils is a singleton class that provides logging utilities.

    It allows for configuring logging to both console and file, setting log levels,
    and retrieving loggers with a specified namespace.

    Attributes:
        _LOGGER_NAMESPACE (str): The namespace for the logger.
        _configured (bool): Indicates whether the logger has been configured.
        _instance (LoggerUtils | None): The singleton instance of LoggerUtils.
    """

    _LOGGER_NAMESPACE: ClassVar[str] = DEFAULT_NAMESPACE
    _configured: ClassVar[bool] = False  # reconfiguration-proof
    _instance: ClassVar[Self | None] = None  # Singleton instance

    def __new__(cls, *args, **kwargs) -> Self:
        """Create or reuse the singleton instance.

        Extra args/kwargs are accepted to mirror ``__init__`` and avoid TypeError
        during construction with keyword parameters.

        Returns:
            Self: The singleton instance of LoggerUtils.
        """
        _ = args, kwargs
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, filename: str | Path, *, use_null_console: bool = False) -> None:
        """Initialize the logger with the specified filename.

        If the logger is already configured, this method does nothing.

        Args:
            filename (str | Path): The log file name is specified by absolute path.
                                   If empty, logging to a file is not performed.
            use_null_console (bool): If True, uses NullHandler instead of StreamHandler for console output.

        Note:
            The file name must be specified as an absolute path.
            Although both relative and absolute paths are normally supported,
            converting to an absolute path using the conversion function causes circular import.
            Therefore, the caller must convert to an absolute path before passing parameters.
        """
        if LoggerUtils._configured:
            return

        self.root_logger: logging.Logger = logging.getLogger(self._LOGGER_NAMESPACE)
        self._use_null_console: bool = bool(use_null_console) or sys.stderr is None
        filename = str(filename)  # Unify with str type.
        # must be set to a lower level than the level set in the handler
        # otherwise, logs will not be output
        self.root_logger.setLevel(DEFAULT_LOG_LEVEL)

        self._console_logging()
        if filename.strip():
            self._file_logging(filename)
        else:
            self.root_logger.warning("Log file name is empty. Logging to the file is not performed.")

        warnings.showwarning = self.warning_to_log
        LoggerUtils._configured = True

    def warning_to_log(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        """Convert warnings to log messages.

        This method is used to redirect warnings to the logger instead of printing them to stderr.
        Conforms to the signature required by warnings.showwarning.

        Args:
            message (Warning | str): The warning message or Warning instance.
            category (type[Warning]): The category (class) of the warning.
            filename (str): The name of the file where the warning occurred.
            lineno (int): The line number where the warning occurred.
            file (TextIO | None): File object to write warning (unused, kept for compatibility).
            line (str | None): Source code line (unused, kept for compatibility).
        """
        # Parameters 'file' and 'line' are intentionally unused but required by the warnings module signature
        _ = file, line
        self.root_logger.warning("%s:%d: %s: %s", filename, lineno, category.__name__, message)

    @classmethod
    def initialize(cls, namespace: str) -> None:
        """Initialize the logger with a specified namespace.

        This method sets the namespace for the logger. If the logger is already configured,
        it does nothing.

        Args:
            namespace (str): The namespace to set for the logger.
        Raises:
            RuntimeError: If the logger is already configured.
        """
        if cls._configured:
            msg = "LoggerUtils is already configured. Reinitialization is not allowed."
            raise RuntimeError(msg)

        cls._LOGGER_NAMESPACE = namespace

    def _console_logging(self) -> None:
        """Configure log output to console.

        Console output is set to WARNING level or above for ease of viewing.
        Messages are kept minimal for better readability.
        """
        if self._use_null_console:
            if self._has_handler(NullHandler):
                self.root_logger.warning("Console logging is already configured.")
                return
            self.root_logger.addHandler(NullHandler())
            return

        if self._has_handler(StreamHandler):
            self.root_logger.warning("Console logging is already configured.")
            return

        console_handler: StreamHandler[TextIO] = StreamHandler(sys.stderr)
        console_handler.setLevel(logging.WARNING)
        console_formatter = Formatter("%(message)s")
        console_handler.setFormatter(console_formatter)
        self.root_logger.addHandler(console_handler)

    def _file_logging(self, filename: str) -> None:
        """Configure log output to file.

        Sets UTF-8 encoding to support multi-byte characters.
        Uses RotatingFileHandler to prevent log file bloat.

        Args:
            filename (str): Absolute path to the log file.
        """
        if self._has_handler(RotatingFileHandler):
            self.root_logger.warning("File logging is already configured.")
            return

        try:
            file_handler = RotatingFileHandler(
                filename=filename,
                maxBytes=_LOG_FILE_SIZE,
                backupCount=_LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except (FileNotFoundError, PermissionError):
            self.root_logger.error("Incorrect log file name: %s\nLogging to the file is not performed.", filename)
            return

        file_handler.setLevel(logging.DEBUG)
        file_formatter = Formatter(
            "%(asctime)s %(levelname)-8s %(process)5d %(thread)5d %(lineno)4d %(name)-38s\t%(funcName)s\t%(message)s"
        )
        file_handler.setFormatter(file_formatter)
        self.root_logger.addHandler(file_handler)

    def _has_handler(self, handler_type: type) -> bool:
        """Check if a handler of the specified type is already configured.

        Args:
            handler_type (type): The type of handler to check for.

        Returns:
            bool: True if a handler of the specified type exists, False otherwise.
        """
        return any(isinstance(h, handler_type) for h in self.root_logger.handlers)

    def set_level(self, level: LevelType) -> None:
        """Set the logging level for the root logger.

        If an unknown level is specified, the logging level is set to 'INFO' and a warning is logged.

        Args:
            level (LevelType): The logging level to set. Must be one of the defined levels.
        """
        level_map: dict[str, int] = logging.getLevelNamesMapping()
        try:
            self.root_logger.setLevel(level_map[level.upper()])
        except KeyError:
            self.root_logger.setLevel(DEFAULT_LOG_LEVEL)
            self.root_logger.warning("Unknown logging level '%s' specified.\nLogging level set to 'INFO'.", level)

    def get_level(self) -> LogLevel:
        """Get the current logging level of the root logger.

        Returns:
            LogLevel: A named tuple containing the logging level name and its numeric value.
        """
        level_value: int = self.root_logger.getEffectiveLevel()
        level_name: str = logging.getLevelName(level_value)
        return LogLevel(name=level_name, value=level_value)

    @staticmethod
    def get_logger(name: str | None = None) -> logging.Logger:
        """Get a logger with the specified name.

        If no name is provided, the root logger in the namespace specified by the '_LOGGER_NAMESPACE'
        variable is returned.

        Args:
            name (str | None): The name of the logger.
                               If None, the root logger in the namespace specified by '_LOGGER_NAMESPACE' is returned.
        Returns:
            logging.Logger: The logger instance.
        """
        full_name: str | None
        if LoggerUtils._LOGGER_NAMESPACE:
            full_name = f"{LoggerUtils._LOGGER_NAMESPACE}.{name}" if name else LoggerUtils._LOGGER_NAMESPACE
        else:
            full_name = name or None
        return logging.getLogger(full_name)

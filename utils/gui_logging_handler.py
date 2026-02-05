"""GUI logging handler for tkinter Text widget.

This module provides a custom logging handler that outputs log messages to a tkinter Text widget.
It maintains a buffer of the most recent log lines (20-30 by default) and applies color formatting
based on log level (WARNING and above are colored).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    from tkinter import Text

try:
    from tkinter import TclError
except ImportError:
    TclError = RuntimeError

logger: logging.Logger = LoggerUtils.get_logger(__name__)

__all__: list[str] = ["GUILoggingHandler"]

# Define colors for different log levels (web colors)
WARNING_COLOR: Final[str] = "#FFD700"  # Gold
ERROR_COLOR: Final[str] = "#FF7F50"  # Coral
CRITICAL_COLOR: Final[str] = "#FF0000"  # Red


class GUILoggingHandler(logging.Handler):
    """Custom logging handler for tkinter Text widget.

    Outputs log messages to a tkinter Text widget with optional color formatting.
    Maintains a buffer of recent log lines for memory efficiency.

    Attributes:
        text_widget (Text): The tkinter Text widget to output to.
        max_lines (int): Maximum number of lines to keep in the buffer.
        log_colors (dict[int, str]): Mapping of log levels to color tags.
    """

    def __init__(self, text_widget: Text, max_lines: int = 30) -> None:
        """Initialize the GUILoggingHandler.

        Args:
            text_widget (Text): The tkinter Text widget to output to.
            max_lines (int): Maximum number of lines to keep in the buffer (default: 30).
        """
        super().__init__()
        # Set handler level to WARNING to match console behavior
        self.setLevel(logging.WARNING)
        self.text_widget: Text = text_widget
        self.max_lines: int = max_lines

        # Define color tags for different log levels
        self.log_colors: dict[int, str] = {
            logging.WARNING: "warning_tag",
            logging.ERROR: "error_tag",
            logging.CRITICAL: "critical_tag",
        }

        # Configure text widget tags for colors
        self._setup_tags()

    def _setup_tags(self) -> None:
        """Set up text widget color tags for different log levels."""
        try:
            self.text_widget.tag_config("warning_tag", foreground=WARNING_COLOR)
            self.text_widget.tag_config("error_tag", foreground=ERROR_COLOR)
            self.text_widget.tag_config("critical_tag", foreground=CRITICAL_COLOR)
        except (AttributeError, RuntimeError) as err:
            # If text widget is not yet initialized, tags will be set later
            logger.debug("Failed to configure text widget tags: %s", err)

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to the text widget.

        Args:
            record (LogRecord): The log record to emit.
        """
        try:
            msg: str = self.format(record)
            tag: str | None = self.log_colors.get(record.levelno)

            # Insert message into text widget
            self.text_widget.config(state="normal")
            if tag:
                self.text_widget.insert("end", msg + "\n", tag)
            else:
                self.text_widget.insert("end", msg + "\n")

            # Keep only the most recent lines
            self._trim_lines()

            # Auto-scroll to the end
            self.text_widget.see("end")
            self.text_widget.config(state="disabled")
        except (AttributeError, RuntimeError, TclError):
            logger.exception("Failed to emit log record to GUI")
            self.handleError(record)

    def _trim_lines(self) -> None:
        """Trim the text widget to keep only the most recent max_lines lines."""
        content: str = self.text_widget.get("1.0", "end-1c")
        lines: list[str] = content.split("\n")

        if len(lines) > self.max_lines:
            # Calculate how many lines to remove
            lines_to_remove: int = len(lines) - self.max_lines
            # Delete from the beginning
            end_index: str = f"{lines_to_remove + 1}.0"
            self.text_widget.delete("1.0", end_index)

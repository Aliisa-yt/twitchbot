"""GUI application for twitchbot with tkinter.

This module provides a GUI interface for the twitchbot using tkinter,
integrating asyncio event loop with tkinter's event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import sys
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING, Any, Final

from utils.gui_logging_handler import GUILoggingHandler
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from core.bot import Bot

__all__: list[str] = ["GUIApp", "StreamRedirector"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# GUI color constants (web colors)
TEXT_COLOR: Final[str] = "#FFFAF0"  # Floral White
STATUS_WAKEUP_COLOR: Final[str] = "#2F4F4F"  # Dark Slate Gray
STATUS_RUNNING_COLOR: Final[str] = "#2E8B57"  # Sea Green
STATUS_ERROR_COLOR: Final[str] = "#DC143C"  # Crimson
BUTTON_BG_COLOR: Final[str] = "#FF6347"  # Tomato
TEXT_WIDGET_BG: Final[str] = "#1E1E1E"  # Dark background
TEXT_WIDGET_FG: Final[str] = "#00FF00"  # Green text


class StreamRedirector(io.StringIO):
    """Redirect stdout/stderr to a tkinter Text widget while preserving standard output.

    This class extends io.StringIO to capture text output and display it in a tkinter Text widget
    in real-time, while simultaneously writing to the original stdout/stderr stream.
    """

    def __init__(self, text_widget: scrolledtext.ScrolledText, original_stream: Any, max_lines: int = 30) -> None:
        """Initialize the StreamRedirector.

        Args:
            text_widget (scrolledtext.ScrolledText): The tkinter Text widget to write to.
            original_stream (Any): The original stdout/stderr stream to preserve.
            max_lines (int): Maximum number of lines to keep in the buffer.
        """
        super().__init__()
        self.text_widget: scrolledtext.ScrolledText = text_widget
        self.original_stream: Any = original_stream
        self.max_lines: int = max_lines

    def write(self, msg: str) -> int:
        """Write message to both the text widget and the original stream.

        Args:
            msg (str): The message to write.

        Returns:
            int: Number of characters written.
        """
        if msg == "":
            return 0

        # Write to original stdout/stderr
        try:
            self.original_stream.write(msg)
            self.original_stream.flush()
        except (OSError, AttributeError, ValueError):
            # Original stream may be closed or unavailable
            pass

        try:
            # Write to text widget
            self.text_widget.config(state="normal", fg=TEXT_COLOR)
            self.text_widget.insert("end", msg)

            # Trim lines if necessary
            self._trim_lines()

            # Auto-scroll to the end
            self.text_widget.see("end")
            self.text_widget.config(state="disabled")
        except tk.TclError:
            # Window was closed or text widget is not available
            pass

        # Also write to buffer
        return super().write(msg)

    def _trim_lines(self) -> None:
        """Trim the text widget to keep only the most recent max_lines lines."""
        content: str = self.text_widget.get("1.0", "end-1c")
        lines: list[str] = content.split("\n")

        if len(lines) > self.max_lines:
            lines_to_remove: int = len(lines) - self.max_lines
            end_index: str = f"{lines_to_remove + 1}.0"
            self.text_widget.delete("1.0", end_index)

    def flush(self) -> None:
        """Flush both the original stream and the buffer."""
        with contextlib.suppress(OSError, AttributeError, ValueError):
            self.original_stream.flush()
        super().flush()


class GUIApp:
    """GUI application for twitchbot.

    Provides a tkinter-based GUI interface with integrated console output.
    Manages the integration between asyncio event loop and tkinter event loop.

    Attributes:
        root (tk.Tk): The root tkinter window.
        text_widget (scrolledtext.ScrolledText): The text widget for log output.
        bot (Bot | None): The bot instance.
        running (bool): Whether the bot is currently running.
        gui_handler (GUILoggingHandler): The custom logging handler for GUI output.
    """

    def __init__(self, window_title: str = "Twitchbot", geometry: str = "640x320") -> None:
        """Initialize the GUI application.

        Args:
            window_title (str): The title of the window.
            geometry (str): The geometry of the window (format: "WIDTHxHEIGHT").
        """
        self.root: tk.Tk = tk.Tk()
        self.root.title(window_title)
        self.root.geometry(geometry)

        self.bot: Bot | None = None
        self.running: bool = False
        self.bot_task: asyncio.Task | None = None
        self.shutdown_event: asyncio.Event | None = None
        # Store original stdout/stderr for restoration
        self.stream_redirector: StreamRedirector | None = None

        # Create GUI components
        self._create_widgets()

        # Create stream redirector for stdout/stderr (dual output to GUI and console)
        self.stream_redirector = StreamRedirector(self.text_widget, sys.__stdout__, max_lines=50)

        # Create and configure logging handler
        self.gui_handler: GUILoggingHandler = GUILoggingHandler(self.text_widget, max_lines=50)
        # Try to get the root logger's formatter if available
        root_logger: logging.Logger = logging.getLogger()
        if root_logger.handlers:
            formatter: logging.Formatter | None = root_logger.handlers[0].formatter
            if formatter:
                self.gui_handler.setFormatter(formatter)
        else:
            # Use a simple format if no formatter is available
            self.gui_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

        # Handle window close button
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_widgets(self) -> None:
        """Create the GUI widgets."""
        style = ttk.Style(self.root)
        style.configure("Twitchbot.TButton", font=("Arial", 10, "bold"))
        style.configure("Twitchbot.TLabel", font=("Arial", 10, "bold"), foreground=STATUS_WAKEUP_COLOR)

        # Create frame for buttons
        button_frame: ttk.Frame = ttk.Frame(self.root)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)

        # Create exit button
        self.exit_button: ttk.Button = ttk.Button(
            button_frame,
            text="Close",
            command=self._on_closing,
            style="Twitchbot.TButton",
        )
        self.exit_button.pack(side=tk.RIGHT, padx=5)

        # Create status label
        self.status_label: ttk.Label = ttk.Label(button_frame, text="Starting...", style="Twitchbot.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # Create scrolled text widget for console output
        self.text_widget: scrolledtext.ScrolledText = scrolledtext.ScrolledText(
            self.root, state="disabled", wrap=tk.WORD, font=("Courier", 10), bg=TEXT_WIDGET_BG, fg=TEXT_WIDGET_FG
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _on_closing(self) -> None:
        """Handle window close button."""
        logger.info("Shutdown signal received from GUI")
        self.running = False
        # Signal shutdown
        if self.shutdown_event and not self.shutdown_event.is_set():
            self.shutdown_event.set()

    def add_logging_handler(self) -> None:
        """Add the GUI logging handler to the root logger."""
        root_logger: logging.Logger = logging.getLogger()
        root_logger.addHandler(self.gui_handler)
        # Redirect stdout and stderr to GUI
        if self.stream_redirector:
            sys.stdout = self.stream_redirector
            sys.stderr = self.stream_redirector
        logger.debug("GUI logging handler added")

    def remove_logging_handler(self) -> None:
        """Remove the GUI logging handler from the root logger."""
        # Restore stdout and stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        root_logger: logging.Logger = logging.getLogger()
        root_logger.removeHandler(self.gui_handler)
        logger.debug("GUI logging handler removed")

    def update_status(self, status: str, color: str = "#2ECC71") -> None:
        """Update the status label.

        Args:
            status (str): The status text to display.
            color (str): The color of the status text.
        """
        self.status_label.config(text=status, foreground=color)
        self.root.update_idletasks()

    def show_error_dialog(self, title: str, message: str) -> None:
        """Show an error dialog.

        Args:
            title (str): The title of the error dialog.
            message (str): The error message to display.
        """
        messagebox.showerror(title, message, parent=self.root)

    def show_info_dialog(self, title: str, message: str) -> None:
        """Show an info dialog.

        Args:
            title (str): The title of the info dialog.
            message (str): The info message to display.
        """
        messagebox.showinfo(title, message, parent=self.root)

    async def run_with_bot(self, bot_coro: Awaitable) -> None:
        """Run the GUI application with the bot.

        Args:
            bot_coro: The bot coroutine to run.
        """
        self.running = True
        self.shutdown_event = asyncio.Event()
        self.add_logging_handler()

        try:
            self.update_status("Bot running...", STATUS_RUNNING_COLOR)

            # Create a task for the bot
            self.bot_task = asyncio.ensure_future(bot_coro)

            # Run the tkinter event loop with asyncio integration
            while self.running:
                try:
                    self.root.update()
                except tk.TclError:
                    # Window was closed
                    break

                # Check if bot task is done
                if self.bot_task.done():
                    try:
                        await self.bot_task
                    except asyncio.CancelledError:
                        logger.debug("Bot task cancelled")
                    except Exception as err:
                        logger.exception("Error in bot coroutine")
                        self.update_status(f"Error: {err}", STATUS_ERROR_COLOR)
                    break

                # Process asyncio events
                await asyncio.sleep(0.01)

            # Cancel the bot task if still running
            if self.bot_task and not self.bot_task.done():
                self.bot_task.cancel()
                try:
                    await self.bot_task
                except asyncio.CancelledError:
                    logger.debug("Bot task cancelled")

        except Exception as err:
            logger.exception("Error in GUI application")
            self.update_status(f"Error: {err}", STATUS_ERROR_COLOR)
        finally:
            self.running = False
            self.remove_logging_handler()
            with contextlib.suppress(Exception):
                self.root.destroy()

    @staticmethod
    async def run_app_with_bot_async(bot) -> None:
        """Run the GUI application with an existing bot instance.

        This method integrates the GUI with an existing asyncio event loop
        and bot instance, suitable for use within an async context.

        Args:
            bot: The bot instance to manage.
        """
        title: str = f"{bot.config.GENERAL.SCRIPT_NAME} - ver. {bot.config.GENERAL.VERSION}"
        app: GUIApp = GUIApp(window_title=title)
        app.bot = bot

        try:
            await app.run_with_bot(bot.start(with_adapter=False))
        except Exception:
            logger.exception("Error running GUI application with bot")
            raise

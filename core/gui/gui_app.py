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
from dataclasses import dataclass
from tkinter import messagebox, scrolledtext, ttk
from typing import TYPE_CHECKING, Any, Final

from core.gui.gui_logging_handler import GUILoggingHandler
from utils.logger_utils import LoggerUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from core.bot import Bot
    from core.stt.manager import STTManager
    from core.stt.recorder import STTLevelEvent

__all__: list[str] = ["GUIApp", "StreamRedirector"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# GUI color constants
TEXT_COLOR: Final[str] = "#FFFAF0"  # Floral White
STATUS_WAKEUP_COLOR: Final[str] = "#5CC8EB"  # Light Blue
STATUS_RUNNING_COLOR: Final[str] = "#00D000"  # Green
STATUS_ERROR_COLOR: Final[str] = "#FF2A04"  # Red
BUTTON_BG_COLOR: Final[str] = "#FF6347"  # Tomato
TEXT_WIDGET_BG: Final[str] = "#0F0F0F"  # Dark background
TEXT_WIDGET_FG: Final[str] = "#56F000"  # Green text
BACKGROUND_COLOR: Final[str] = "#F0F0F0"  # Light background for the whole app

# Styles for ttk widgets
BUTTON_STYLE: Final[str] = "Twitchbot.TButton"
MUTE_BUTTON_MUTED_STYLE: Final[str] = "Twitchbot.Muted.TButton"
MUTE_BUTTON_UNMUTED_STYLE: Final[str] = "Twitchbot.Unmuted.TButton"
LABEL_STYLE: Final[str] = "Twitchbot.TLabel"
FRAME_STYLE: Final[str] = "Twitchbot.TFrame"
LABEL_FRAME_STYLE: Final[str] = "Twitchbot.TLabelframe"
LABEL_FRAME_LABEL_STYLE: Final[str] = "Twitchbot.TLabelframe.Label"
VAD_MODE_LEVEL: Final[str] = "level"
VAD_MODE_SILERO_ONNX: Final[str] = "silero_onnx"
STT_SILERO_UNUSED_LABEL_TEXT: Final[str] = "Unused"
STT_SILERO_UNUSED_VALUE_TEXT: Final[str] = "--"

# Maximum lines to keep in the scrolled text widget
MAX_SCROLLED_LINES: Final[int] = 50

# STT level meter thresholds
STT_LEVEL_WARNING_THRESHOLD: Final[float] = -20  # dB
STT_LEVEL_DANGER_THRESHOLD: Final[float] = -8  # dB
STT_FLOOR_LEVEL_DB: Final[float] = -60  # dB

# STT level meter colors
STT_LEVEL_SAFE_COLOR: Final[str] = "#37D247"  # Green
STT_LEVEL_WARNING_COLOR: Final[str] = "#E5AF24"  # Orange
STT_LEVEL_DANGER_COLOR: Final[str] = "#E33B57"  # Red
STT_LEVEL_BG_COLOR: Final[str] = "#0F0F0F"  # Dark background for level meter

# Mute button color
MUTE_BUTTON_MUTED_COLOR: Final[str] = "#FF5537"  # Red
MUTE_BUTTON_MUTED_ACTIVE_COLOR: Final[str] = "#FF806A"  # Red
MUTE_BUTTON_UNMUTED_COLOR: Final[str] = "#6DEC7A"  # Green
MUTE_BUTTON_UNMUTED_ACTIVE_COLOR: Final[str] = "#9CECA4"  # Green


@dataclass(slots=True)
class STTSectionWidgets:
    """Container for STT section widgets.

    Keeping STT widgets grouped in one structure reduces coupling inside GUIApp
    while maintaining compatibility through legacy attribute bindings.
    """

    level_meter: tk.Canvas
    level_meter_fill_id: int
    level_meter_peak_id: int
    level_meter_length: int
    level_meter_height: int
    start_text_label: ttk.Label
    start_scale: ttk.Scale
    start_value_label: ttk.Label
    stop_text_label: ttk.Label
    stop_scale: ttk.Scale
    stop_value_label: ttk.Label
    mute_button: ttk.Button
    state_label: ttk.Label


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
        line_count: int = int(self.text_widget.index("end-1c").split(".")[0])
        if line_count > self.max_lines:
            end_index: str = f"{line_count - self.max_lines + 1}.0"
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

    # Smoothing factor for STT level meter width update (EMA)
    STT_LEVEL_EMA_RESPONSE_TIME: Final[float] = 0.300
    STT_LEVEL_EMA_ALPHA_DEFAULT: Final[float] = 1.0 / (1.0 + STT_LEVEL_EMA_RESPONSE_TIME * 10.0)

    def __init__(self, window_title: str = "Twitchbot", geometry: str = "800x336") -> None:
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
        self._updating_stt_thresholds: bool = False
        self._stt_vad_mode: str = VAD_MODE_LEVEL
        self._stt_smoothed_rms: float | None = None
        self._stt_smoothed_peak: float | None = None
        self._stt_widgets: STTSectionWidgets | None = None
        # Store original stdout/stderr for restoration
        self.stream_redirector: StreamRedirector | None = None
        self.ema_alpha: float = self.STT_LEVEL_EMA_ALPHA_DEFAULT

        # Create GUI components
        try:
            self._create_widgets()
        except tk.TclError as err:
            logger.exception("Error creating GUI widgets")
            msg: str = f"Failed to create GUI widgets: {err}"
            raise RuntimeError(msg) from err

        # Create stream redirector for stdout/stderr (dual output to GUI and console)
        self.stream_redirector = StreamRedirector(self.text_widget, sys.__stdout__, max_lines=MAX_SCROLLED_LINES)

        # Create and configure logging handler
        self.gui_handler: GUILoggingHandler = GUILoggingHandler(self.text_widget, max_lines=MAX_SCROLLED_LINES)
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
        self.root.configure(bg=BACKGROUND_COLOR)
        self._configure_styles()

        # Top block: status + close button
        status_frame: ttk.Frame = ttk.Frame(self.root, style=FRAME_STYLE)
        status_frame.pack(side=tk.TOP, fill=tk.X, padx=8, pady=(8, 4))

        # Create status label
        self.status_label: ttk.Label = ttk.Label(status_frame, text="Starting...", style=LABEL_STYLE)
        self.status_label.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 8))

        # Create exit button
        self.exit_button: ttk.Button = ttk.Button(
            status_frame,
            text="Close",
            command=self._on_closing,
            style=BUTTON_STYLE,
        )
        self.exit_button.pack(side=tk.RIGHT, padx=4)

        separator: ttk.Separator = ttk.Separator(self.root, orient="horizontal")
        separator.pack(side=tk.TOP, fill="x", padx=8, pady=(0, 6))

        # Middle area: message block + STT block
        content_frame: ttk.Frame = ttk.Frame(self.root, style=FRAME_STYLE)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.stt_section(content_frame)
        self.message_section(content_frame)

    def message_section(self, parent_frame: ttk.Frame) -> None:
        """Create the message display section in the GUI.

        Args:
            parent_frame (ttk.Frame): The parent frame for the message section.
        """
        message_frame: ttk.LabelFrame = ttk.LabelFrame(parent_frame, text="Messages", style=LABEL_FRAME_STYLE)
        message_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self.text_widget: scrolledtext.ScrolledText = scrolledtext.ScrolledText(
            message_frame,
            state="disabled",
            wrap=tk.WORD,
            font=("Courier", 10),
            bg=TEXT_WIDGET_BG,
            fg=TEXT_WIDGET_FG,
            relief=tk.SUNKEN,
            borderwidth=2,
        )
        self.text_widget.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def stt_section(self, parent_frame: ttk.Frame) -> None:
        widgets: STTSectionWidgets = self._create_stt_section_widgets(parent_frame)
        self._stt_widgets = widgets
        self._bind_stt_legacy_attributes(widgets)

    def _create_stt_section_widgets(self, parent_frame: ttk.Frame) -> STTSectionWidgets:
        """Create and return all widgets used by the STT section."""
        stt_inner: ttk.Frame = self._create_section_frame(parent_frame, "STT")

        level_meter, level_meter_fill_id, peak_id, level_meter_length, level_meter_height = self._level_meter(
            stt_inner,
            length=150,
            height=24,
        )

        start_text_label, start_scale, start_value_label = self._labeled_scale(
            stt_inner,
            text="Start Threshold",
            from_=STT_FLOOR_LEVEL_DB,
            to=0.0,
            initial_value=-20.0,
            command=self._on_stt_threshold_changed,
        )

        stop_text_label, stop_scale, stop_value_label = self._labeled_scale(
            stt_inner,
            text="Stop Threshold",
            from_=STT_FLOOR_LEVEL_DB,
            to=0.0,
            initial_value=-40.0,
            command=self._on_stt_threshold_changed,
        )

        mute_button = ttk.Button(
            stt_inner,
            text="Mute",
            style=BUTTON_STYLE,
            command=self._on_stt_mute_button_clicked,
        )
        mute_button.pack(fill=tk.X, pady=(12, 6))
        mute_button.state(["disabled"])

        state_label = ttk.Label(
            stt_inner,
            text="Status: Not connected",
            background=BACKGROUND_COLOR,
        )
        state_label.pack(anchor=tk.W)

        return STTSectionWidgets(
            level_meter=level_meter,
            level_meter_fill_id=level_meter_fill_id,
            level_meter_peak_id=peak_id,
            level_meter_length=level_meter_length,
            level_meter_height=level_meter_height,
            start_text_label=start_text_label,
            start_scale=start_scale,
            start_value_label=start_value_label,
            stop_text_label=stop_text_label,
            stop_scale=stop_scale,
            stop_value_label=stop_value_label,
            mute_button=mute_button,
            state_label=state_label,
        )

    def _bind_stt_legacy_attributes(self, widgets: STTSectionWidgets) -> None:
        """Bind legacy GUIApp attributes for external compatibility.

        Other modules and tests access these attributes directly, so this method
        keeps backward compatibility while allowing internal STT encapsulation.
        """
        self.stt_level_meter: tk.Canvas = widgets.level_meter
        self.stt_start_scale: ttk.Scale = widgets.start_scale
        self.stt_start_value_label: ttk.Label = widgets.start_value_label
        self.stt_stop_scale: ttk.Scale = widgets.stop_scale
        self.stt_stop_value_label: ttk.Label = widgets.stop_value_label
        self.stt_mute_button: ttk.Button = widgets.mute_button
        self.stt_state_label: ttk.Label = widgets.state_label

    def _require_stt_widgets(self) -> STTSectionWidgets:
        """Return STT widgets container.

        Raises:
            RuntimeError: If STT widgets are not initialized.
        """
        if self._stt_widgets is None:
            msg: str = "STT widgets are not initialized"
            raise RuntimeError(msg)
        return self._stt_widgets

    def _level_meter(
        self, parent: ttk.Frame, *, length: int = 180, height: int = 14
    ) -> tuple[tk.Canvas, int, int, int, int]:
        """Create a level meter widget.

        Args:
            parent (ttk.Frame): The parent frame for the level meter.
            length (int, optional): The length of the progress bar. Defaults to 180.
            height (int, optional): The height of the level meter. Defaults to 14.

        Returns:
            tuple[tk.Canvas, int, int, int, int]:
                Canvas widget, rectangle id, peak id, meter length, and meter height.
        """
        # Use Canvas instead of ttk.Progressbar so level color can be controlled across platforms/themes.
        level_label = ttk.Label(parent, text="Input Level", background=BACKGROUND_COLOR)
        level_label.pack(anchor=tk.W)

        level_meter = tk.Canvas(
            parent,
            width=length,
            height=height,
            bg=STT_LEVEL_BG_COLOR,
            highlightthickness=0,
            bd=1,
            relief=tk.SUNKEN,
        )
        level_meter.pack(fill=tk.X, pady=(4, 10))
        fill_id: int = level_meter.create_rectangle(0, 0, 0, height, fill=STT_LEVEL_SAFE_COLOR, width=0)
        peak_id: int = level_meter.create_line(0, 0, 0, height, fill=STT_LEVEL_SAFE_COLOR, width=2)
        return level_meter, fill_id, peak_id, length, height

    def _create_section_frame(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        frame: ttk.LabelFrame = ttk.LabelFrame(parent, text=title, style=LABEL_FRAME_STYLE)
        frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 6))

        inner: ttk.Frame = ttk.Frame(frame, style=FRAME_STYLE)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        return inner

    def _labeled_scale(
        self,
        parent: ttk.Frame,
        *,
        text: str,
        from_: float = 0.0,
        to: float = 1.0,
        initial_value: float = 0.0,
        command: str | Callable[[str], None] = "",
    ) -> tuple[ttk.Label, ttk.Scale, ttk.Label]:
        """Create a labeled scale row (Label + Scale + Value Label)."""

        label_frame = ttk.Frame(parent, style=FRAME_STYLE)
        label_frame.pack(fill=tk.X, pady=(4, 0))

        label = ttk.Label(label_frame, text=text, background=BACKGROUND_COLOR)
        label.pack(side=tk.LEFT)

        value_label = ttk.Label(label_frame, text=f"{initial_value:.1f}dB", background=BACKGROUND_COLOR)
        value_label.pack(side=tk.RIGHT)

        row = ttk.Frame(parent, style=FRAME_STYLE)
        row.pack(fill=tk.X, pady=(4, 4))

        scale = ttk.Scale(row, from_=from_, to=to, command=command)
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True)

        scale.set(initial_value)
        scale.state(["disabled"])

        return label, scale, value_label

    @staticmethod
    def _normalize_vad_mode(vad_mode: str) -> str:
        normalized: str = vad_mode.strip().lower()
        if normalized == VAD_MODE_SILERO_ONNX:
            return VAD_MODE_SILERO_ONNX
        return VAD_MODE_LEVEL

    @staticmethod
    def _clamp_vad_threshold(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _format_vad_threshold_value(value: float) -> str:
        return f"{max(0.0, min(1.0, float(value))):.2f}"

    def configure_stt_vad_mode(self, *, vad_mode: str, vad_threshold: float) -> None:
        """Configure STT slider presentation for the selected VAD mode.

        Args:
            vad_mode (str): VAD mode text from configuration.
            vad_threshold (float): Silero VAD threshold in the range 0.0-1.0.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()
        self._stt_vad_mode = self._normalize_vad_mode(vad_mode)

        if self._stt_vad_mode == VAD_MODE_SILERO_ONNX:
            widgets.start_text_label.config(text="VAD Threshold")
            widgets.stop_text_label.config(text=STT_SILERO_UNUSED_LABEL_TEXT, foreground="#808080")
            widgets.start_scale.configure(from_=0.0, to=1.0)
            widgets.stop_scale.configure(from_=STT_FLOOR_LEVEL_DB, to=0.0)
            self._updating_stt_thresholds = True
            try:
                widgets.start_scale.set(self._clamp_vad_threshold(vad_threshold))
            finally:
                self._updating_stt_thresholds = False
            widgets.stop_scale.state(["disabled"])
            self._update_stt_threshold_value_labels(widgets.start_scale.get(), 0.0)
            self.root.update_idletasks()
            return

        widgets.start_text_label.config(text="Start Threshold")
        widgets.stop_text_label.config(text="Stop Threshold", foreground="")
        widgets.start_scale.configure(from_=STT_FLOOR_LEVEL_DB, to=0.0)
        widgets.stop_scale.configure(from_=STT_FLOOR_LEVEL_DB, to=0.0)
        self._update_stt_threshold_value_labels(widgets.start_scale.get(), widgets.stop_scale.get())
        self.root.update_idletasks()

    def _configure_styles(self) -> None:
        """Configure ttk widget styles for the GUI."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(BUTTON_STYLE, font=("Arial", 10, "bold"))
        style.configure(
            LABEL_STYLE,
            font=("Arial", 10, "bold"),
            foreground=STATUS_WAKEUP_COLOR,
            background=BACKGROUND_COLOR,
        )
        style.configure(FRAME_STYLE, background=BACKGROUND_COLOR)
        style.configure(LABEL_FRAME_STYLE, background=BACKGROUND_COLOR)
        style.configure(LABEL_FRAME_LABEL_STYLE, background=BACKGROUND_COLOR)
        style.configure(MUTE_BUTTON_MUTED_STYLE, background=MUTE_BUTTON_MUTED_COLOR, font=("Arial", 10, "bold"))
        style.map(MUTE_BUTTON_MUTED_STYLE, background=[("active", MUTE_BUTTON_MUTED_ACTIVE_COLOR)])
        style.configure(MUTE_BUTTON_UNMUTED_STYLE, background=MUTE_BUTTON_UNMUTED_COLOR, font=("Arial", 10, "bold"))
        style.map(MUTE_BUTTON_UNMUTED_STYLE, background=[("active", MUTE_BUTTON_UNMUTED_ACTIVE_COLOR)])

    @staticmethod
    def _resolve_stt_level_color(level_db: float) -> str:
        """Resolve STT level meter color based on current RMS value.

        Args:
            level_db (float): Current RMS level in dB.

        Returns:
            str: Color representing the STT level.
        """
        if level_db >= STT_LEVEL_DANGER_THRESHOLD:
            return STT_LEVEL_DANGER_COLOR
        if level_db >= STT_LEVEL_WARNING_THRESHOLD:
            return STT_LEVEL_WARNING_COLOR
        return STT_LEVEL_SAFE_COLOR

    @staticmethod
    def _apply_ema_smoothing(
        smoothed_data: float | None, raw_data: float, ema_alpha: float = STT_LEVEL_EMA_ALPHA_DEFAULT
    ) -> float:
        """Apply lightweight EMA smoothing for STT level meter width.

        The first sample is used as-is to avoid delayed initial rendering.
        """
        if smoothed_data is None:
            return raw_data

        # If the level is rising, update immediately for responsiveness. If falling, apply smoothing to avoid jitter.
        if raw_data > smoothed_data:
            return raw_data

        return (ema_alpha * raw_data) + ((1.0 - ema_alpha) * smoothed_data)

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

    @staticmethod
    def _clamp_percent(value: float) -> float:
        """Clamp a numeric value to the 0.0-1.0 range.

        Args:
            value (float): Input value.

        Returns:
            float: Clamped value.
        """
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _scale_db_to_meter_position(level_db: float, meter_length: int) -> float:
        """Scale a dB value to STT meter x-coordinate.

        Args:
            level_db (float): Input level in dB.
            meter_length (int): Meter width in pixels.

        Returns:
            float: Meter position clamped to keep a minimum visible width.
        """
        meter_position: float = (meter_length + 2) * (level_db - STT_FLOOR_LEVEL_DB) / (-STT_FLOOR_LEVEL_DB)
        return max(meter_position, 1.0)

    def _calculate_stt_meter_state(self, rms: float, peak: float, meter_length: int) -> tuple[float, float, str, str]:
        """Calculate smoothed meter geometry and colors for STT levels.

        Args:
            rms (float): Current RMS level in 0.0-1.0.
            peak (float): Current peak level in 0.0-1.0.
            meter_length (int): Meter width in pixels.

        Returns:
            tuple[float, float, str, str]: fill width, peak x-coordinate, fill color, peak color.
        """
        rms_raw: float = self._clamp_percent(rms)
        self._stt_smoothed_rms = self._apply_ema_smoothing(
            smoothed_data=self._stt_smoothed_rms,
            raw_data=rms_raw,
            ema_alpha=self.ema_alpha,
        )
        rms_db: float = TTSUtils.linear_to_log(self._stt_smoothed_rms, floor_db=STT_FLOOR_LEVEL_DB)

        peak_raw: float = self._clamp_percent(peak)
        # Drop peak hold more slowly than attack to keep transients visible.
        self._stt_smoothed_peak = self._apply_ema_smoothing(
            smoothed_data=self._stt_smoothed_peak,
            raw_data=peak_raw,
            ema_alpha=self.ema_alpha * 0.5,
        )
        peak_db: float = TTSUtils.linear_to_log(self._stt_smoothed_peak, floor_db=STT_FLOOR_LEVEL_DB)

        fill_width: float = self._scale_db_to_meter_position(rms_db, meter_length)
        peak_x: float = self._scale_db_to_meter_position(peak_db, meter_length)

        fill_color: str = self._resolve_stt_level_color(rms_db)
        peak_color: str = self._resolve_stt_level_color(peak_db)
        return fill_width, peak_x, fill_color, peak_color

    def update_stt_level(self, rms: float, peak: float) -> None:
        """Update the STT input level meter.

        Args:
            rms (float): Current RMS value in the range 0.0-1.0.
            peak (float): Peak level in the range 0.0-1.0.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()

        fill_width, peak_x, fill_color, peak_color = self._calculate_stt_meter_state(
            rms=rms,
            peak=peak,
            meter_length=widgets.level_meter_length,
        )

        widgets.level_meter.coords(
            widgets.level_meter_fill_id,
            1,
            2,
            fill_width,
            widgets.level_meter_height,
        )

        widgets.level_meter.coords(
            widgets.level_meter_peak_id,
            peak_x,
            2,
            peak_x,
            widgets.level_meter_height,
        )

        widgets.level_meter.itemconfigure(
            widgets.level_meter_fill_id,
            fill=fill_color,
        )

        widgets.level_meter.itemconfigure(
            widgets.level_meter_peak_id,
            fill=peak_color,
        )

        self.root.update_idletasks()

    def apply_stt_level_event(self, event: STTLevelEvent) -> None:
        """Apply recorder input-level event to STT widgets.

        Args:
            event (STTLevelEvent): Input level event emitted by STT recorder.
        """
        self.update_stt_level(event.rms, event.peak)
        self.set_stt_mute_state(is_muted=event.muted)

    def update_stt_thresholds(self, start_level_db: float, stop_level_db: float) -> None:
        """Update the visual values of STT start/stop thresholds.

        Args:
            start_level_db (float): Start threshold in the range dB.
            stop_level_db (float): Stop threshold in the range dB.
        """
        self._updating_stt_thresholds = True
        widgets: STTSectionWidgets = self._require_stt_widgets()
        try:
            clamped_start, clamped_stop = self._normalize_stt_threshold_pair(start_level_db, stop_level_db)
            widgets.start_scale.set(clamped_start)
            widgets.stop_scale.set(clamped_stop)
        finally:
            self._updating_stt_thresholds = False
        self._update_stt_threshold_value_labels(clamped_start, clamped_stop)
        self.root.update_idletasks()

    def set_stt_status(self, status: str) -> None:
        """Update STT status text in the preview panel.

        Args:
            status (str): Status string to display.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()
        widgets.state_label.config(text=f"Status: {status}")
        self.root.update_idletasks()

    def set_stt_controls_enabled(self, *, enabled: bool) -> None:
        """Set STT preview controls enabled/disabled state.

        Args:
            enabled (bool): True to enable controls, False to disable.
        """
        state: list[str] = ["!disabled"] if enabled else ["disabled"]
        widgets: STTSectionWidgets = self._require_stt_widgets()
        widgets.start_scale.state(state)
        if self._stt_vad_mode == VAD_MODE_SILERO_ONNX:
            widgets.stop_scale.state(["disabled"])
        else:
            widgets.stop_scale.state(state)
        widgets.mute_button.state(state)
        self.root.update_idletasks()

    def update_stt_vad_threshold(self, threshold: float) -> None:
        """Update the visual value of Silero VAD threshold slider.

        Args:
            threshold (float): VAD threshold in the range 0.0-1.0.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()
        self._updating_stt_thresholds = True
        try:
            widgets.start_scale.set(self._clamp_vad_threshold(threshold))
        finally:
            self._updating_stt_thresholds = False
        self._update_stt_threshold_value_labels(widgets.start_scale.get(), 0.0)
        self.root.update_idletasks()

    def set_stt_mute_state(self, *, is_muted: bool) -> None:
        """Update STT mute button label.

        Args:
            is_muted (bool): True if muted.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()
        if is_muted:
            widgets.mute_button.config(text="Unmute", style=MUTE_BUTTON_MUTED_STYLE)
        else:
            widgets.mute_button.config(text="Mute", style=MUTE_BUTTON_UNMUTED_STYLE)

        self.root.update_idletasks()

    def _on_stt_mute_button_clicked(self) -> None:
        """Handle STT mute button click event."""
        if self.bot is None:
            logger.debug("STT mute toggle skipped because bot is not attached")
            return

        stt_manager: STTManager | None = getattr(self.bot.shared_data, "stt_manager", None)
        if stt_manager is None:
            logger.debug("STT mute toggle skipped because STT manager is unavailable")
            return

        is_muted: bool = stt_manager.toggle_mute()
        self.set_stt_mute_state(is_muted=is_muted)
        self.set_stt_status("Muted" if is_muted else "Input monitoring")

    @staticmethod
    def _clamp_level(value: float) -> float:
        """Clamp STT threshold level to the valid range."""
        return max(STT_FLOOR_LEVEL_DB, min(0.0, float(value)))

    @staticmethod
    def _format_level_value(value: float) -> str:
        """Format threshold level value for GUI label."""
        return f"{max(STT_FLOOR_LEVEL_DB, min(0.0, float(value))):.1f}dB"

    def _update_stt_threshold_value_labels(self, start_level_db: float, stop_level_db: float) -> None:
        """Update STT threshold numeric labels.

        Args:
            start_level_db (float): Start threshold in dB.
            stop_level_db (float): Stop threshold in dB.
        """
        widgets: STTSectionWidgets = self._require_stt_widgets()
        if self._stt_vad_mode == VAD_MODE_SILERO_ONNX:
            widgets.start_value_label.config(text=self._format_vad_threshold_value(start_level_db))
            widgets.stop_value_label.config(text=STT_SILERO_UNUSED_VALUE_TEXT, foreground="#808080")
            return
        widgets.start_value_label.config(text=self._format_level_value(start_level_db))
        widgets.stop_value_label.config(text=self._format_level_value(stop_level_db), foreground="")

    def _normalize_stt_threshold_pair(self, start_level_db: float, stop_level_db: float) -> tuple[float, float]:
        clamped_start: float = self._clamp_level(start_level_db)
        clamped_stop: float = self._clamp_level(stop_level_db)
        if clamped_start < clamped_stop:
            return clamped_stop, clamped_start
        return clamped_start, clamped_stop

    def _on_stt_threshold_changed(self, _value: str) -> None:
        """Handle STT threshold slider changes and apply to recorder thresholds."""
        if self._updating_stt_thresholds:
            return

        if self.bot is None:
            return

        stt_manager: STTManager | None = getattr(self.bot.shared_data, "stt_manager", None)
        if stt_manager is None:
            return

        try:
            widgets: STTSectionWidgets = self._require_stt_widgets()

            if self._stt_vad_mode == VAD_MODE_SILERO_ONNX:
                selected_threshold: float = self._clamp_vad_threshold(float(widgets.start_scale.get()))
                applied_threshold: float = stt_manager.set_vad_threshold(threshold=selected_threshold)
                self.update_stt_vad_threshold(applied_threshold)
                return

            start_level_db: float = float(widgets.start_scale.get())
            stop_level_db: float = float(widgets.stop_scale.get())
            normalized_start, normalized_stop = self._normalize_stt_threshold_pair(start_level_db, stop_level_db)

            applied_start, applied_stop = stt_manager.set_thresholds(
                start_level_db=normalized_start,
                stop_level_db=normalized_stop,
            )
            self._update_stt_threshold_value_labels(applied_start, applied_stop)
        except (AttributeError, RuntimeError, ValueError, TypeError) as err:
            logger.debug("Failed to apply STT thresholds from GUI sliders: %s", err)
            return

        self.update_stt_thresholds(start_level_db=applied_start, stop_level_db=applied_stop)

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

    async def run_with_bot(self, bot_coro: Coroutine[Any, Any, None]) -> None:  # noqa: C901
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
            self.bot_task = asyncio.create_task(bot_coro, name="BotTask")

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
            try:
                self.root.destroy()
            except (tk.TclError, RuntimeError) as err:
                logger.debug("GUI root destroy skipped during shutdown: %s", err)
            except Exception as err:  # noqa: BLE001
                logger.warning("Unexpected error while destroying GUI root: %s", err)

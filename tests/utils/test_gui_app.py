"""Unit tests for core.gui.gui_app module."""

from __future__ import annotations

import asyncio
import io
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from core.gui import gui_app as gui_module
from core.stt.recorder import STTLevelEvent

if TYPE_CHECKING:
    from logging import Logger
    from tkinter.scrolledtext import ScrolledText


class DummyTextWidget:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        self.state = "disabled"
        self._content: str = ""
        self._tags: dict[str, dict[str, Any]] = {}
        self.fg: str | None = None

    def config(self, **kwargs: Any) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]
        if "fg" in kwargs:
            self.fg = kwargs["fg"]

    def insert(self, _index: str, text: str, _tag: str | None = None) -> None:
        self._content += text

    def get(self, _start: str, _end: str) -> str:
        if _end == "end-1c" and self._content.endswith("\n"):
            return self._content[:-1]
        return self._content

    def delete(self, _start: str, _end: str) -> None:
        lines: list[str] = self._content.split("\n")
        if not lines:
            self._content = ""
            return

        end_line: int = 1
        if isinstance(_end, str) and "." in _end:
            try:
                end_line = int(_end.split(".", maxsplit=1)[0])
            except ValueError:
                end_line = 1

        lines_to_remove: int = max(end_line - 1, 0)
        if lines_to_remove <= 0:
            return

        self._content = "\n".join(lines[lines_to_remove:])

    def index(self, idx: str) -> str:
        if idx == "end-1c":
            lines = self._content.split("\n")
            line_count = len(lines) - (1 if self._content.endswith("\n") else 0)
            return f"{line_count}.0"
        return "1.0"

    def see(self, _index: str) -> None:
        return None

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def tag_config(self, tag_name: str, **kwargs: Any) -> None:
        self._tags[tag_name] = kwargs


class DummyLabel:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args
        self.last_config: dict[str, Any] = {}
        self.text: str = str(kwargs.get("text", ""))

    def config(self, **kwargs: Any) -> None:
        self.last_config = kwargs
        if "text" in kwargs:
            self.text = str(kwargs["text"])

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyButton:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args
        self.command = kwargs.get("command")
        self.last_config: dict[str, Any] = {}
        self.states: list[list[str]] = []

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def config(self, **kwargs: Any) -> None:
        self.last_config = kwargs

    def state(self, state: list[str]) -> None:
        self.states.append(state)

    def invoke(self) -> None:
        if self.command is not None:
            self.command()


class DummyFrame:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyCanvas:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args
        self.width: int = int(kwargs.get("width", 0))
        self.height: int = int(kwargs.get("height", 0))
        self.next_item_id: int = 1
        self.coords_map: dict[int, tuple[float, float, float, float]] = {}
        self.item_config_map: dict[int, dict[str, Any]] = {}

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def create_rectangle(self, x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> int:
        item_id = self.next_item_id
        self.next_item_id += 1
        self.coords_map[item_id] = (x1, y1, x2, y2)
        self.item_config_map[item_id] = kwargs
        return item_id

    def create_line(self, x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> int:
        item_id = self.next_item_id
        self.next_item_id += 1
        self.coords_map[item_id] = (x1, y1, x2, y2)
        self.item_config_map[item_id] = kwargs
        return item_id

    def coords(self, item_id: int, x1: float, y1: float, x2: float, y2: float) -> None:
        self.coords_map[item_id] = (x1, y1, x2, y2)

    def itemconfigure(self, item_id: int, **kwargs: Any) -> None:
        if item_id not in self.item_config_map:
            self.item_config_map[item_id] = {}
        self.item_config_map[item_id].update(kwargs)


class DummyScale:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args
        self.value: float = 0.0
        self.states: list[list[str]] = []
        self.command = kwargs.get("command")
        self.from_: float = float(kwargs.get("from_", 0.0))
        self.to: float = float(kwargs.get("to", 1.0))

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def set(self, value: float) -> None:
        self.value = value
        if self.command is not None:
            self.command(str(self.value))

    def get(self) -> float:
        return self.value

    def state(self, state: list[str]) -> None:
        self.states.append(state)

    def configure(self, **kwargs: Any) -> None:
        if "from_" in kwargs:
            self.from_ = float(kwargs["from_"])
        if "to" in kwargs:
            self.to = float(kwargs["to"])

    def invoke(self) -> None:
        if self.command is not None:
            self.command(str(self.value))


class DummySeparator:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyStyle:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        self.theme: str | None = None

    def configure(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def theme_use(self, theme_name: str) -> None:
        self.theme = theme_name

    def map(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyRoot:
    def __init__(self) -> None:
        self.protocols: list[tuple[str, Any]] = []
        self.titles: list[str] = []
        self.geometries: list[str] = []
        self.updated = 0
        self.destroyed = False

    def title(self, value: str) -> None:
        self.titles.append(value)

    def geometry(self, value: str) -> None:
        self.geometries.append(value)

    def protocol(self, name: str, handler: Any) -> None:
        self.protocols.append((name, handler))

    def update(self) -> None:
        msg = "closed"
        raise gui_module.tk.TclError(msg)

    def update_idletasks(self) -> None:
        self.updated += 1

    def destroy(self) -> None:
        self.destroyed = True

    def configure(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


@pytest.fixture
def patched_gui(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(gui_module.tk, "Tk", DummyRoot)
    monkeypatch.setattr(gui_module.ttk, "Style", DummyStyle)
    monkeypatch.setattr(gui_module.ttk, "Frame", DummyFrame)
    monkeypatch.setattr(gui_module.ttk, "LabelFrame", DummyFrame)
    monkeypatch.setattr(gui_module.ttk, "Separator", DummySeparator)
    monkeypatch.setattr(gui_module.ttk, "Button", DummyButton)
    monkeypatch.setattr(gui_module.ttk, "Label", DummyLabel)
    monkeypatch.setattr(gui_module.tk, "Canvas", DummyCanvas)
    monkeypatch.setattr(gui_module.ttk, "Scale", DummyScale)
    monkeypatch.setattr(gui_module.scrolledtext, "ScrolledText", DummyTextWidget)

    show_info_calls: list[tuple[str, str]] = []
    show_error_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(gui_module.messagebox, "showinfo", lambda title, msg, **_: show_info_calls.append((title, msg)))
    monkeypatch.setattr(
        gui_module.messagebox, "showerror", lambda title, msg, **_: show_error_calls.append((title, msg))
    )

    return SimpleNamespace(info_calls=show_info_calls, error_calls=show_error_calls)


def test_stream_redirector_trims_lines() -> None:
    widget: ScrolledText = cast("ScrolledText", DummyTextWidget())
    original = io.StringIO()
    redirector = gui_module.StreamRedirector(widget, original, max_lines=2)

    redirector.write("line1\n")
    redirector.write("line2\n")
    redirector.write("line3\n")

    content: str = widget.get("1.0", "end-1c")
    assert "line1" not in content
    assert "line2" in content
    assert "line3" in content


def test_add_and_remove_logging_handler(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()
    root_logger: Logger = gui_module.logging.getLogger()

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    app.add_logging_handler()

    assert app.gui_handler in root_logger.handlers
    assert sys.stdout is app.stream_redirector
    assert sys.stderr is app.stream_redirector

    app.remove_logging_handler()

    assert app.gui_handler not in root_logger.handlers
    assert sys.stdout is sys.__stdout__
    assert sys.stderr is sys.__stderr__

    sys.stdout = original_stdout
    sys.stderr = original_stderr


def test_update_status_updates_label(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    app.update_status("Running", "#123456")

    assert cast("DummyLabel", app.status_label).last_config == {"text": "Running", "foreground": "#123456"}
    assert cast("DummyRoot", app.root).updated == 1


def test_update_stt_level_updates_meter_style_by_level(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    meter = cast("DummyCanvas", app.stt_level_meter)
    widgets = app._require_stt_widgets()
    fill_id = widgets.level_meter_fill_id

    app.update_stt_level(0.2, 0.0)
    x1, y1, x2, y2 = meter.coords_map[fill_id]
    assert (x1, y1, y2) == (1, 2, 24)
    assert x2 == pytest.approx(116.58552)
    assert meter.item_config_map[fill_id]["fill"] == gui_module.STT_LEVEL_WARNING_COLOR

    app.update_stt_level(0.7, 0.0)
    x1, y1, x2, y2 = meter.coords_map[fill_id]
    assert (x1, y1, y2) == (1, 2, 24)
    assert x2 == pytest.approx(144.15163)
    assert meter.item_config_map[fill_id]["fill"] == gui_module.STT_LEVEL_DANGER_COLOR

    app.update_stt_level(0.95, 0.0)
    x1, y1, x2, y2 = meter.coords_map[fill_id]
    assert (x1, y1, y2) == (1, 2, 24)
    assert x2 == pytest.approx(150.87133)
    assert meter.item_config_map[fill_id]["fill"] == gui_module.STT_LEVEL_DANGER_COLOR


def test_apply_stt_level_event_updates_meter_and_mute_button(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    event = STTLevelEvent(rms=0.7, peak=0.2, muted=True, timestamp=0.0)
    app.apply_stt_level_event(event)

    button = cast("DummyButton", app.stt_mute_button)
    meter = cast("DummyCanvas", app.stt_level_meter)
    widgets = app._require_stt_widgets()
    fill_id = widgets.level_meter_fill_id

    assert meter.coords_map[fill_id][2] == pytest.approx(144.15163)
    assert button.last_config.get("text") == "Unmute"


def test_dialog_helpers_call_messagebox(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    app.show_info_dialog("Title", "Info")
    app.show_error_dialog("Oops", "Error")

    assert patched_gui.info_calls == [("Title", "Info")]
    assert patched_gui.error_calls == [("Oops", "Error")]


@pytest.mark.asyncio
async def test_run_with_bot_handles_close(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    async def bot_coro() -> None:
        await asyncio.sleep(0.5)

    await app.run_with_bot(bot_coro())

    assert app.running is False
    assert cast("DummyRoot", app.root).destroyed is True


def test_stt_mute_button_toggles_manager_state(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    class DummySTTManager:
        def __init__(self) -> None:
            self.muted = False

        def toggle_mute(self) -> bool:
            self.muted = not self.muted
            return self.muted

    stt_manager = DummySTTManager()
    app.bot = cast("Any", SimpleNamespace(shared_data=SimpleNamespace(stt_manager=stt_manager)))

    button = cast("DummyButton", app.stt_mute_button)
    button.invoke()

    assert stt_manager.muted is True
    assert button.last_config.get("text") == "Unmute"
    assert cast("DummyLabel", app.stt_state_label).last_config == {"text": "Status: Muted"}

    button.invoke()

    assert stt_manager.muted is False
    assert button.last_config.get("text") == "Mute"
    assert cast("DummyLabel", app.stt_state_label).last_config == {"text": "Status: Input monitoring"}


def test_stt_threshold_slider_applies_manager_thresholds(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    class DummySTTManager:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float]] = []

        def set_thresholds(self, *, start_level_db: float, stop_level_db: float) -> tuple[float, float]:
            self.calls.append((start_level_db, stop_level_db))
            return start_level_db, stop_level_db

    stt_manager = DummySTTManager()
    app.bot = cast("Any", SimpleNamespace(shared_data=SimpleNamespace(stt_manager=stt_manager)))

    start_scale = cast("DummyScale", app.stt_start_scale)
    stop_scale = cast("DummyScale", app.stt_stop_scale)
    stop_scale.set(-10.0)
    stt_manager.calls.clear()
    start_scale.set(-40.0)

    assert stt_manager.calls == [(-20.0, -40.0)]
    assert start_scale.value == -20.0
    assert stop_scale.value == -40.0
    assert cast("DummyLabel", app.stt_start_value_label).text == "-20.0dB"
    assert cast("DummyLabel", app.stt_stop_value_label).text == "-40.0dB"


def test_update_stt_thresholds_does_not_reenter_threshold_callback(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    class DummySTTManager:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float]] = []

        def set_thresholds(self, *, start_level_db: float, stop_level_db: float) -> tuple[float, float]:
            self.calls.append((start_level_db, stop_level_db))
            return start_level_db, stop_level_db

    stt_manager = DummySTTManager()
    app.bot = cast("Any", SimpleNamespace(shared_data=SimpleNamespace(stt_manager=stt_manager)))

    app.update_stt_thresholds(-20, -40)

    assert stt_manager.calls == []
    assert cast("DummyLabel", app.stt_start_value_label).text == "-20.0dB"
    assert cast("DummyLabel", app.stt_stop_value_label).text == "-40.0dB"


def test_configure_stt_vad_mode_silero_updates_slider_layout(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()

    app.configure_stt_vad_mode(vad_mode="silero_onnx", vad_threshold=0.42)

    start_scale = cast("DummyScale", app.stt_start_scale)
    stop_scale = cast("DummyScale", app.stt_stop_scale)
    assert start_scale.from_ == pytest.approx(0.0)
    assert start_scale.to == pytest.approx(1.0)
    assert stop_scale.states[-1] == ["disabled"]
    assert cast("DummyLabel", app.stt_start_value_label).text == "0.42"
    assert cast("DummyLabel", app.stt_stop_value_label).text == "--"


def test_stt_threshold_slider_applies_silero_vad_threshold(patched_gui: SimpleNamespace) -> None:
    _ = patched_gui
    app = gui_module.GUIApp()
    app.configure_stt_vad_mode(vad_mode="silero_onnx", vad_threshold=0.5)

    class DummySTTManager:
        def __init__(self) -> None:
            self.calls: list[float] = []

        def set_vad_threshold(self, *, threshold: float) -> float:
            self.calls.append(threshold)
            return threshold

    stt_manager = DummySTTManager()
    app.bot = cast("Any", SimpleNamespace(shared_data=SimpleNamespace(stt_manager=stt_manager)))

    start_scale = cast("DummyScale", app.stt_start_scale)
    start_scale.set(0.63)

    assert stt_manager.calls == [pytest.approx(0.63)]
    assert cast("DummyLabel", app.stt_start_value_label).text == "0.63"
    assert cast("DummyLabel", app.stt_stop_value_label).text == "--"

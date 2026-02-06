"""Unit tests for utils.gui_app module."""

from __future__ import annotations

import asyncio
import io
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from utils import gui_app as gui_module

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

    def see(self, _index: str) -> None:
        return None

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def tag_config(self, tag_name: str, **kwargs: Any) -> None:
        self._tags[tag_name] = kwargs


class DummyLabel:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        self.last_config: dict[str, Any] = {}

    def config(self, **kwargs: Any) -> None:
        self.last_config = kwargs

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyButton:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyFrame:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def pack(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs


class DummyStyle:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs

    def configure(self, *args: Any, **kwargs: Any) -> None:
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


@pytest.fixture
def patched_gui(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setattr(gui_module.tk, "Tk", DummyRoot)
    monkeypatch.setattr(gui_module.ttk, "Style", DummyStyle)
    monkeypatch.setattr(gui_module.ttk, "Frame", DummyFrame)
    monkeypatch.setattr(gui_module.ttk, "Button", DummyButton)
    monkeypatch.setattr(gui_module.ttk, "Label", DummyLabel)
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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from core.gui.gui_logging_handler import GUILoggingHandler

if TYPE_CHECKING:
    from tkinter import Text


class _DummyTextWidget:
    def __init__(self) -> None:
        self.records: list[tuple[str, str, str | None]] = []

    def tag_config(self, _tag_name: str, **_kwargs: Any) -> None:
        return None

    def config(self, **_kwargs: Any) -> None:
        return None

    def insert(self, _index: str, text: str, tag: str | None = None) -> None:
        self.records.append(("insert", text, tag))

    def see(self, _index: str) -> None:
        return None

    def get(self, _start: str, _end: str) -> str:
        return ""


class _FailingTextWidget(_DummyTextWidget):
    def insert(self, _index: str, text: str, tag: str | None = None) -> None:
        _ = text, tag
        msg = "widget unavailable"
        raise RuntimeError(msg)


def test_emit_writes_to_widget_on_main_thread() -> None:
    widget = _DummyTextWidget()
    handler = GUILoggingHandler(cast("Text", widget))
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="sample",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    assert widget.records
    assert widget.records[0][1] == "ERROR:sample\n"


def test_emit_falls_back_without_raising_when_widget_write_fails() -> None:
    widget = _FailingTextWidget()
    handler = GUILoggingHandler(cast("Text", widget))
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="broken",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

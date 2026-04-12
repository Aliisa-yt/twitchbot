"""Unit tests for CevioAI and CevioCS7 thin wrapper engines."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

pythoncom = pytest.importorskip("pythoncom")
pytest.importorskip("win32com.client")

cevio_ai_module: ModuleType = importlib.import_module("core.tts.engines.cevio_ai")
cevio_cs7_module: ModuleType = importlib.import_module("core.tts.engines.cevio_cs7")
CevioAI = cevio_ai_module.CevioAI
CevioCS7 = cevio_cs7_module.CevioCS7


# ---------------------------------------------------------------------------
# CevioAI
# ---------------------------------------------------------------------------


def test_cevio_ai_fetch_engine_name() -> None:
    assert CevioAI.fetch_engine_name() == "cevio_ai"


def test_cevio_ai_initializes_with_ai_type() -> None:
    engine = CevioAI()
    assert engine.cevio_type == "AI"


# ---------------------------------------------------------------------------
# CevioCS7
# ---------------------------------------------------------------------------


def test_cevio_cs7_fetch_engine_name() -> None:
    assert CevioCS7.fetch_engine_name() == "cevio_cs7"


def test_cevio_cs7_initializes_with_cs7_type() -> None:
    engine = CevioCS7()
    assert engine.cevio_type == "CS7"

"""Unit tests for async_google_translate module."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.trans.engines import async_google_translate as agt


class DummySession:
    def __init__(self, *args, **kwargs) -> None:
        _ = args, kwargs
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def patch_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agt.aiohttp, "ClientSession", DummySession)


def _make_response(decoded_data: list[Any]) -> str:
    line: str = json.dumps([["MkEWBc", None, json.dumps(decoded_data)]])
    return f"ignored\n{line}"


def test_check_langcode_accepts_known_code() -> None:
    result: str = agt.AsyncTranslator._check_langcode("EN")

    assert result.lower() == "en"


def test_check_langcode_raises_when_sensitive() -> None:
    with pytest.raises(agt.InvalidLanguageCodeError):
        agt.AsyncTranslator._check_langcode("zz", sensitive=True)


def test_validate_languages_falls_back_to_auto() -> None:
    translator = agt.AsyncTranslator()

    src, tgt = translator._validate_languages("zz", "en")

    assert src == "auto"
    assert tgt.lower() == "en"


def test_validate_text_length_rejects_empty() -> None:
    translator = agt.AsyncTranslator()

    with pytest.raises(agt.GoogleError):
        translator._validate_text_length("")


def test_validate_text_length_rejects_too_long() -> None:
    translator = agt.AsyncTranslator()
    long_text: str = "a" * 5000

    with pytest.raises(agt.GoogleError):
        translator._validate_text_length(long_text)


def test_process_response_single_translation() -> None:
    translator = agt.AsyncTranslator(return_list=True)
    decoded_data = [
        ["src", None],
        [
            [[None, "ja", None, None, None, [["Hello", None], ["World", None]]]],
            None,
            None,
            "en",
        ],
    ]

    result: agt.TextResult = translator._process_response(_make_response(decoded_data))

    assert result.text == "Hello World"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "google", "type": "single translation"}


def test_process_response_multiple_translations() -> None:
    translator = agt.AsyncTranslator(return_list=True)
    decoded_data = [
        ["src", None],
        [
            [["Hello", "ja"], ["World", "ja"]],
            None,
            None,
            "en",
        ],
    ]

    result: agt.TextResult = translator._process_response(_make_response(decoded_data))

    assert result.text == "Hello World"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "google", "type": "multiple translation"}


def test_process_response_raises_on_missing_marker() -> None:
    translator = agt.AsyncTranslator()

    with pytest.raises(agt.ResponseFormatError):
        translator._process_response("no marker here")

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from core.trans.engines import googletrans_wrapper as wrapper


class DummyClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class DummyTranslator:
    result: object = SimpleNamespace(text="translated", src="en")
    error: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, str, str]] = []
        self.client = DummyClient()

    async def translate(self, text: str, *, dest: str, src: str) -> object:
        self.calls.append((text, dest, src))
        if type(self).error is not None:
            raise type(self).error
        return type(self).result


@pytest.fixture(autouse=True)
def dummy_googletrans(monkeypatch: pytest.MonkeyPatch) -> None:
    DummyTranslator.result = SimpleNamespace(text="translated", src="en")
    DummyTranslator.error = None
    monkeypatch.setattr(wrapper, "Translator", DummyTranslator)


def test_initialization_normalizes_suffix_and_enables_strict_errors() -> None:
    translator = wrapper.AsyncTranslator(url_suffix="co.jp", timeout=12.5)

    assert translator.url_suffix == "co.jp"
    assert translator.service_url == "translate.google.co.jp"
    assert translator._translator.kwargs["service_urls"] == ["translate.google.co.jp"]
    assert translator._translator.kwargs["raise_exception"] is True
    assert translator._translator.kwargs["timeout"] == httpx.Timeout(12.5)


def test_initialization_falls_back_to_com_for_unknown_suffix() -> None:
    translator = wrapper.AsyncTranslator(url_suffix="invalid")

    assert translator.url_suffix == "com"
    assert translator.service_url == "translate.google.com"


@pytest.mark.asyncio
async def test_translate_normalizes_googletrans_result() -> None:
    translator = wrapper.AsyncTranslator()

    result = await translator.translate("hello", lang_tgt="ja", lang_src=None)

    assert translator._translator.calls == [("hello", "ja", "auto")]
    assert result.text == "translated"
    assert result.detected_source_lang == "en"
    assert result.metadata == {"engine": "google", "service_url": "translate.google.com"}


@pytest.mark.asyncio
async def test_translate_maps_invalid_language_error() -> None:
    DummyTranslator.error = ValueError("invalid destination language")
    translator = wrapper.AsyncTranslator()

    with pytest.raises(wrapper.InvalidLanguageCodeError):
        await translator.translate("hello", lang_tgt="invalid")


@pytest.mark.asyncio
async def test_translate_maps_network_and_timeout_errors() -> None:
    translator = wrapper.AsyncTranslator()
    DummyTranslator.error = httpx.ConnectError("offline")

    with pytest.raises(wrapper.HTTPConnectionError):
        await translator.translate("hello", lang_tgt="ja")

    DummyTranslator.error = httpx.ReadTimeout("slow")
    with pytest.raises(wrapper.HTTPTimeoutError):
        await translator.translate("hello", lang_tgt="ja")


@pytest.mark.asyncio
async def test_translate_maps_googletrans_status_error() -> None:
    DummyTranslator.error = Exception('Unexpected status code "429" from [\'translate.google.com\']')
    translator = wrapper.AsyncTranslator()

    with pytest.raises(wrapper.HTTPTooManyRequests):
        await translator.translate("hello", lang_tgt="ja")


@pytest.mark.asyncio
async def test_translate_rejects_invalid_result_and_releases_client() -> None:
    DummyTranslator.result = SimpleNamespace(text=None, src="en")
    translator = wrapper.AsyncTranslator()

    with pytest.raises(wrapper.ResponseFormatError):
        await translator.translate("hello", lang_tgt="ja")

    await translator.close()
    assert translator._translator.client.closed is True

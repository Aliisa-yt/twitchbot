from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import numpy as np
import pytest

from core.tts.engines import g_tts as g_tts_module
from models.voice_models import TTSInfo, TTSParam, Voice


def test_ensure_float32_array_accepts_float32() -> None:
    data = np.array([0.0, 1.0], dtype=np.float32)
    result = g_tts_module._ensure_float32_array(data, "test data")
    assert result is data


@pytest.mark.parametrize(
    "value",
    [
        [1.0, 2.0],
        "not-array",
        1,
    ],
)
def test_ensure_float32_array_rejects_non_ndarray(value: Any) -> None:
    msg = "Expected ndarray for test data"
    with pytest.raises(TypeError, match=msg):
        g_tts_module._ensure_float32_array(value, "test data")


def test_ensure_float32_array_rejects_wrong_dtype() -> None:
    data = np.array([0.0, 1.0], dtype=np.float64)
    msg = "Expected float32 for test data"
    with pytest.raises(TypeError, match=msg):
        g_tts_module._ensure_float32_array(data, "test data")


def test_audio_data_rejects_invalid_types() -> None:
    msg = "Expected ndarray for raw_pcm"
    with pytest.raises(TypeError, match=msg):
        g_tts_module._AudioData(raw_pcm=cast("np.ndarray[Any, Any]", "bad"), samplerate=48000)

    msg = "Expected int for samplerate"
    with pytest.raises(TypeError, match=msg):
        g_tts_module._AudioData(raw_pcm=np.array([0.0], dtype=np.float32), samplerate=cast("int", "bad"))


@pytest.mark.asyncio
async def test_speech_synthesis_writes_audio_and_plays(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = g_tts_module.GoogleText2Speech()

    class FakeGTTS:
        def __init__(self, text: str, lang: str) -> None:
            self.text: str = text
            self.lang: str = lang

        def write_to_fp(self, fp) -> None:
            fp.write(b"fake")

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    raw_pcm = np.array([0.5, -0.5], dtype=np.float32)
    written: dict[str, Any] = {}

    def fake_read(_fp: Any, dtype: Any = None) -> tuple[np.ndarray[Any, Any], int]:
        _ = dtype
        return raw_pcm.copy(), 24000

    def fake_write(file_path: Any, data: Any, samplerate: int, subtype: Any = None, format: Any = None) -> None:  # noqa: A002
        _ = subtype, format
        written["path"] = file_path
        written["data"] = data
        written["samplerate"] = samplerate

    monkeypatch.setattr(g_tts_module, "gTTS", FakeGTTS)
    monkeypatch.setattr(g_tts_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(g_tts_module.soundfile, "read", fake_read)
    monkeypatch.setattr(g_tts_module.soundfile, "write", fake_write)
    monkeypatch.setattr(engine, "create_audio_filename", lambda **_kwargs: Path("voice.wav"))
    engine.play = AsyncMock()

    tts_info = TTSInfo(voice=Voice(volume=150))
    tts_param = TTSParam(content="hello", content_lang="en", tts_info=tts_info)

    await engine.speech_synthesis(tts_param)

    expected = raw_pcm * 1.5
    np.testing.assert_allclose(written["data"], expected, rtol=1e-6, atol=1e-6)
    assert written["samplerate"] == 24000
    assert written["path"] == Path("voice.wav")
    assert tts_param.filepath == Path("voice.wav")
    engine.play.assert_called_once_with(tts_param)


@pytest.mark.asyncio
async def test_speech_synthesis_skips_when_language_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = g_tts_module.GoogleText2Speech()

    gtts_mock = AsyncMock()
    monkeypatch.setattr(g_tts_module, "gTTS", gtts_mock)
    monkeypatch.setattr(engine, "create_audio_filename", lambda **_kwargs: Path("voice.wav"))
    engine.play = AsyncMock()

    tts_param = TTSParam(content="hello", content_lang=None)

    await engine.speech_synthesis(tts_param)

    assert gtts_mock.call_count == 0
    engine.play.assert_not_called()


@pytest.mark.asyncio
async def test_speech_synthesis_no_volume_adjustment(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = g_tts_module.GoogleText2Speech()

    class FakeGTTS:
        def __init__(self, text: str, lang: str) -> None:
            self.text = text
            self.lang = lang

        def write_to_fp(self, fp) -> None:
            fp.write(b"fake")

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    raw_pcm = np.array([0.25, -0.25], dtype=np.float32)
    written: dict[str, Any] = {}

    def fake_read(_fp: Any, dtype: Any = None) -> tuple[np.ndarray[Any, Any], int]:
        _ = dtype
        return raw_pcm.copy(), 22050

    def fake_write(_file_path: Any, data: Any, samplerate: int, subtype: Any = None, format: Any = None) -> None:  # noqa: A002
        _ = _file_path, subtype, format
        written["data"] = data
        written["samplerate"] = samplerate

    monkeypatch.setattr(g_tts_module, "gTTS", FakeGTTS)
    monkeypatch.setattr(g_tts_module.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(g_tts_module.soundfile, "read", fake_read)
    monkeypatch.setattr(g_tts_module.soundfile, "write", fake_write)
    monkeypatch.setattr(engine, "create_audio_filename", lambda **_kwargs: Path("voice.wav"))
    engine.play = AsyncMock()

    tts_info = TTSInfo(voice=Voice(volume=100))
    tts_param = TTSParam(content="hello", content_lang="en", tts_info=tts_info)

    await engine.speech_synthesis(tts_param)

    np.testing.assert_allclose(written["data"], raw_pcm, rtol=1e-6, atol=1e-6)
    assert written["samplerate"] == 22050
    engine.play.assert_called_once_with(tts_param)

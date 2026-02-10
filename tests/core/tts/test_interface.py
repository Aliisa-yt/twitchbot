"""Unit tests for core.tts.interface module."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock

import pytest

from core.tts.interface import (
    DEFAULT_PROTOCOL,
    DEFAULT_TIMEOUT,
    Interface,
    TTSExceptionError,
    TTSFileExistsError,
    TTSNotSupportedError,
    _TTSConfig,
)
from models.voice_models import TTSParam

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator
    from pathlib import Path

    from models.config_models import TTSEngine


@pytest.fixture
def reset_interface_state() -> Iterator[None]:
    prev_registry: dict[str, type[Interface]] = dict(Interface._registered_engines)
    prev_base_dir = getattr(Interface, "_base_directory", None)
    had_callback: bool = hasattr(Interface, "_play_callback")
    prev_callback: Callable[[TTSParam], Awaitable[None]] | None = getattr(Interface, "_play_callback", None)

    Interface._registered_engines = {}
    Interface._base_directory = None
    if hasattr(Interface, "_play_callback"):
        delattr(Interface, "_play_callback")

    yield

    Interface._registered_engines = prev_registry
    Interface._base_directory = prev_base_dir
    if had_callback and prev_callback is not None:
        Interface._play_callback = prev_callback
    elif hasattr(Interface, "_play_callback"):
        delattr(Interface, "_play_callback")


class DummyEngine(Interface):
    @staticmethod
    def fetch_engine_name() -> str:
        return "dummy"

    def initialize_engine(self, tts_engine: TTSEngine) -> bool:
        return super().initialize_engine(tts_engine)

    async def speech_synthesis(self, ttsparam: TTSParam) -> None:
        _ = ttsparam


def test_parse_server_config_with_protocol() -> None:
    protocol, host, port = _TTSConfig._parse_server_config("http://example.com:50000")

    assert protocol == "http"
    assert host == "example.com"
    assert port == 50000


def test_parse_server_config_defaults_protocol() -> None:
    protocol, host, port = _TTSConfig._parse_server_config("example.com:50001")

    assert protocol == DEFAULT_PROTOCOL
    assert host == "example.com"
    assert port == 50001


def test_parse_server_config_rejects_bad_protocol() -> None:
    with pytest.raises(TTSExceptionError):
        _TTSConfig._parse_server_config("ftp://example.com:50000")


def test_parse_server_config_rejects_port_out_of_range() -> None:
    with pytest.raises(TTSExceptionError):
        _TTSConfig._parse_server_config("http://example.com:1")


def test_parse_timeout_invalid_returns_default() -> None:
    assert _TTSConfig._parse_timeout(cast("float", "bad")) == DEFAULT_TIMEOUT
    assert _TTSConfig._parse_timeout(0) == DEFAULT_TIMEOUT


def test_initialize_engine_reads_config(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    exec_path: Path = tmp_path / "dummy.exe"
    tts_engine = SimpleNamespace(
        SERVER="https://example.com:50010",
        TIMEOUT=4.5,
        EARLY_SPEECH=True,
        AUTO_STARTUP=True,
        EXECUTE_PATH=str(exec_path),
    )

    assert engine.initialize_engine(cast("TTSEngine", tts_engine)) is True
    assert engine.protocol == "https"
    assert engine.host == "example.com"
    assert engine.port == 50010
    assert engine.timeout == 4.5
    assert engine.earlyspeech is True
    assert engine.linkedstartup is True
    assert engine.exec_path == exec_path.resolve()


def test_audio_save_directory_set_once(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    engine.audio_save_directory = tmp_path

    assert engine.audio_save_directory == tmp_path
    with pytest.raises(RuntimeError, match="already set"):
        engine.audio_save_directory = tmp_path


def test_play_callback_set_once(reset_interface_state: Iterator[None]) -> None:
    _ = reset_interface_state
    engine = DummyEngine()

    async def callback(_param: TTSParam) -> None:
        return None

    engine.play_callback = callback
    assert engine.play_callback is callback

    with pytest.raises(RuntimeError, match="already set"):
        engine.play_callback = callback


@pytest.mark.asyncio
async def test_play_delegates_to_callback(reset_interface_state: Iterator[None]) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    callback = AsyncMock()
    engine.play_callback = callback

    tts_param = TTSParam(content="hello")
    await engine.play(tts_param)

    callback.assert_awaited_once_with(tts_param)


def test_get_engine_returns_registered_class(reset_interface_state: Iterator[None]) -> None:
    _ = reset_interface_state
    Interface.register_engine(DummyEngine)
    assert Interface.get_engine("dummy") is DummyEngine


def test_create_audio_filename_uses_prefix_and_suffix(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    engine.audio_save_directory = tmp_path

    path = engine.create_audio_filename(prefix="custom", suffix="mp3")

    assert path.parent == tmp_path
    assert path.suffix == ".mp3"
    assert re.match(r"^custom_\{[0-9a-f-]{36}\}\.mp3$", path.name)


def test_create_audio_filename_rejects_format(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    engine.audio_save_directory = tmp_path

    with pytest.raises(TTSNotSupportedError):
        engine.create_audio_filename(suffix="flac")


def test_save_audio_file_accepts_bytes(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    file_path = tmp_path / "voice.wav"

    engine.save_audio_file(file_path, b"data")

    assert file_path.read_bytes() == b"data"


def test_save_audio_file_accepts_bytesio(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    file_path = tmp_path / "voice.wav"

    engine.save_audio_file(file_path, BytesIO(b"data"))

    assert file_path.read_bytes() == b"data"


def test_save_audio_file_rejects_existing_file(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    file_path = tmp_path / "voice.wav"
    file_path.write_bytes(b"existing")

    with pytest.raises(TTSFileExistsError):
        engine.save_audio_file(file_path, b"data")


def test_save_audio_file_rejects_bad_type(reset_interface_state: Iterator[None], tmp_path: Path) -> None:
    _ = reset_interface_state
    engine = DummyEngine()
    file_path: Path = tmp_path / "voice.wav"

    with pytest.raises(TTSNotSupportedError):
        engine.save_audio_file(file_path, cast("bytes", "bad"))

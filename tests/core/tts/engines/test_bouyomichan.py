"""Unit tests for bouyomichan TTS engine."""

import struct
from typing import override

import pytest

from core.tts.engines import bouyomichan as bmc
from handlers.async_comm import AsyncCommError
from models.voice_models import TTSInfo, TTSParam, Voice


class DummySocket:
    last_instance: DummySocket | None = None

    def __init__(self, timeout: float, buffer: int) -> None:
        self.timeout: float = timeout
        self.buffer: int = buffer
        self.connected: bool = False
        self.closed: bool = False
        self.sent: bytes | None = None
        self.address: tuple[str, int] | None = None
        type(self).last_instance = self

    async def connect(self, address: tuple[str, int]) -> None:
        self.connected = True
        self.address = address

    async def send(self, data: bytes) -> None:
        self.sent = data

    async def close(self) -> None:
        self.closed = True


class DummySocketFailure(DummySocket):
    @override
    async def connect(self, address: tuple[str, int]) -> None:
        _ = address
        msg = "connect failed"
        raise AsyncCommError(msg)


def _make_tts_param(*, content: str = "hello", voice: Voice | None = None) -> TTSParam:
    tts_info = TTSInfo(voice=voice or Voice())
    return TTSParam(content=content, tts_info=tts_info)


def test_command_generation_talk_clamps_values() -> None:
    voice = Voice(cast="99999", volume=120, speed=20, tone=10)
    tts_param: TTSParam = _make_tts_param(content="hi", voice=voice)

    command = bmc.BouyomiChanCommand()
    message: bytes = command.generation("talk", tts_param)

    header: bytes = message[:15]
    (cmd, speed, tone, volume, voice_id, char_code, msg_len) = struct.unpack("<HhhhHbI", header)

    assert cmd == bmc.C_TALK
    assert speed == 50
    assert tone == 50
    assert volume == 100
    assert voice_id == 65535
    assert char_code == 0
    assert msg_len == 2
    assert message[15:] == b"hi"


def test_command_generation_invalid_command_raises() -> None:
    tts_param: TTSParam = _make_tts_param()
    command = bmc.BouyomiChanCommand()

    with pytest.raises(bmc.BouyomiChanCommandError):
        command.generation("bad", tts_param)


def test_command_generation_invalid_voice_defaults_to_zero() -> None:
    voice = Voice(cast="bad")
    tts_param: TTSParam = _make_tts_param(content="ok", voice=voice)
    command = bmc.BouyomiChanCommand()

    message: bytes = command.generation("talk", tts_param)
    header: bytes = message[:15]
    (_, _, _, _, voice_id, _, _) = struct.unpack("<HhhhHbI", header)

    assert voice_id == 0


@pytest.mark.asyncio
async def test_speech_synthesis_sends_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bmc, "AsyncSocket", DummySocket)
    engine = bmc.BouyomiChanSocket()

    tts_param: TTSParam = _make_tts_param(content="hello", voice=Voice(cast="1"))

    await engine.speech_synthesis(tts_param)

    instance: DummySocket | None = DummySocket.last_instance
    assert instance is not None
    assert instance.connected is True
    assert instance.sent is not None
    assert instance.closed is True


@pytest.mark.asyncio
async def test_speech_synthesis_handles_socket_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bmc, "AsyncSocket", DummySocketFailure)
    engine = bmc.BouyomiChanSocket()

    tts_param: TTSParam = _make_tts_param(content="hello", voice=Voice(cast="1"))

    await engine.speech_synthesis(tts_param)

    instance: DummySocket | None = DummySocketFailure.last_instance
    assert instance is not None
    assert instance.connected is False
    assert instance.sent is None
    assert instance.closed is True


def test_check_voice_with_none_returns_zero() -> None:
    command = bmc.BouyomiChanCommand()
    assert command._check_voice(None) == 0


def test_command_generation_talk_default_sentinels_pass_through() -> None:
    # speed/tone/volume set to -1 (engine default sentinel): must NOT be clamped
    voice = Voice(speed=-1, tone=-1, volume=-1)
    tts_param: TTSParam = _make_tts_param(content="ok", voice=voice)

    command = bmc.BouyomiChanCommand()
    message: bytes = command.generation("talk", tts_param)

    (_, speed, tone, volume, _, _, _) = struct.unpack("<HhhhHbI", message[:15])

    assert speed == -1
    assert tone == -1
    assert volume == -1


@pytest.mark.asyncio
async def test_speech_synthesis_handles_bad_command_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulate BouyomiChanCommandError raised from generation()
    # Reset class variable to isolate this test from previous socket tests
    DummySocket.last_instance = None
    monkeypatch.setattr(bmc, "AsyncSocket", DummySocket)
    engine = bmc.BouyomiChanSocket()

    def _raise_command_error(self, command: str, ttsparam: TTSParam) -> bytes:  # noqa: ARG001
        msg = "bad command"
        raise bmc.BouyomiChanCommandError(msg)

    monkeypatch.setattr(bmc.BouyomiChanCommand, "generation", _raise_command_error)

    tts_param: TTSParam = _make_tts_param(content="hello")

    # Must not raise; error is logged and function returns early before any socket is created
    await engine.speech_synthesis(tts_param)

    assert DummySocket.last_instance is None


@pytest.mark.asyncio
async def test_speech_synthesis_never_calls_play(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock  # noqa: PLC0415

    monkeypatch.setattr(bmc, "AsyncSocket", DummySocket)
    engine = bmc.BouyomiChanSocket()
    engine.play = AsyncMock()  # type: ignore[method-assign]

    tts_param: TTSParam = _make_tts_param(content="hello", voice=Voice(cast="1"))

    await engine.speech_synthesis(tts_param)

    engine.play.assert_not_called()

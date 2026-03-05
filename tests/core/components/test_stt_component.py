"""Unit tests for core.components.stt_component module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.components.stt_component import STTServiceComponent
from core.stt.interface import STTResult

if TYPE_CHECKING:
    from pathlib import Path

    from models.message_models import ChatMessageDTO


@pytest.fixture
def stt_bundle() -> SimpleNamespace:
    stt_manager = MagicMock()
    stt_manager.async_init = AsyncMock()
    stt_manager.close = AsyncMock()

    tts_manager = MagicMock()
    tts_manager.prepare_tts_content = MagicMock()
    tts_manager.enqueue_tts_synthesis = AsyncMock()

    shared = MagicMock()
    shared.config = MagicMock()
    shared.config.STT = MagicMock()
    shared.config.STT.ENABLED = False
    shared.config.STT.FORWARD_TO_TTS = False
    shared.config.TWITCH = MagicMock()
    shared.config.TWITCH.OWNER_NAME = "owner_name"
    shared.config.BOT = MagicMock()
    shared.config.BOT.BOT_NAME = "bot_name"
    shared.stt_manager = stt_manager
    shared.tts_manager = tts_manager

    class ChatEventsManager:
        def __init__(self) -> None:
            self.enqueue_external_message = AsyncMock()

    chat_events = ChatEventsManager()

    bot = MagicMock()
    bot.shared_data = shared
    bot.owner_id = "owner"
    bot.attached_components = [chat_events]

    component = STTServiceComponent(bot)
    component._stt_result_ignore_words = []

    return SimpleNamespace(
        component=component,
        bot=bot,
        shared=shared,
        stt_manager=stt_manager,
        tts_manager=tts_manager,
        chat_events=chat_events,
    )


@pytest.mark.asyncio
async def test_component_load_initializes_stt_when_enabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.ENABLED = True

    await stt_bundle.component.component_load()

    stt_bundle.stt_manager.async_init.assert_awaited_once()
    await_args = stt_bundle.stt_manager.async_init.await_args
    assert await_args is not None
    assert await_args.kwargs["on_result"] == stt_bundle.component._on_stt_result


@pytest.mark.asyncio
async def test_component_load_skips_stt_init_when_disabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.ENABLED = False

    await stt_bundle.component.component_load()

    stt_bundle.stt_manager.async_init.assert_not_called()


@pytest.mark.asyncio
async def test_component_teardown_closes_stt_manager(stt_bundle: SimpleNamespace) -> None:
    await stt_bundle.component.component_teardown()

    stt_bundle.stt_manager.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_stt_result_ignores_blank_text(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()

    await stt_bundle.component._on_stt_result(STTResult(text="   ", language="ja-JP"))

    stt_bundle.component.send_chat_message.assert_not_called()
    stt_bundle.component.print_console_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_stt_result_prints_console_when_chat_disabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()
    stt_bundle.component._forward_stt_result_to_chat_events = AsyncMock()

    with patch("core.components.stt_component.STT_CHAT_SEND_ENABLED", True):
        await stt_bundle.component._on_stt_result(STTResult(text=" recognized text ", language="ja-JP"))

    stt_bundle.component.send_chat_message.assert_awaited_once_with("recognized text", sender="owner")
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.component._forward_stt_result_to_chat_events.assert_awaited_once_with(text="recognized text")


@pytest.mark.asyncio
async def test_on_stt_result_sends_chat_when_enabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()
    stt_bundle.component._forward_stt_result_to_chat_events = AsyncMock()

    with patch("core.components.stt_component.STT_CHAT_SEND_ENABLED", True):
        await stt_bundle.component._on_stt_result(STTResult(text="recognized text", language="ja-JP"))

    stt_bundle.component.send_chat_message.assert_awaited_once_with("recognized text", sender="owner")
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.component._forward_stt_result_to_chat_events.assert_awaited_once_with(text="recognized text")


@pytest.mark.asyncio
async def test_forward_stt_result_to_chat_events_skips_when_disabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.FORWARD_TO_TTS = False

    await stt_bundle.component._forward_stt_result_to_chat_events(text="hello")

    stt_bundle.chat_events.enqueue_external_message.assert_not_called()


@pytest.mark.asyncio
async def test_forward_stt_result_to_chat_events_enqueues_when_enabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.FORWARD_TO_TTS = True
    await stt_bundle.component._forward_stt_result_to_chat_events(text="recognized text")

    stt_bundle.chat_events.enqueue_external_message.assert_awaited_once()
    dto: ChatMessageDTO = stt_bundle.chat_events.enqueue_external_message.await_args.args[0]
    assert dto.content == "recognized text"
    assert dto.text == "recognized text"
    assert dto.author.name == "owner_name"
    assert dto.author.display_name == "owner_name"
    assert dto.author.broadcaster is True
    assert dto.fragments[0].type == "text"
    assert dto.fragments[0].text == "recognized text"


@pytest.mark.asyncio
async def test_forward_stt_result_to_chat_events_skips_when_manager_unavailable(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.FORWARD_TO_TTS = True
    stt_bundle.bot.attached_components = []

    await stt_bundle.component._forward_stt_result_to_chat_events(text="recognized text")

    stt_bundle.chat_events.enqueue_external_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_stt_result_does_not_enqueue_when_forward_disabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.FORWARD_TO_TTS = False
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()

    with patch("core.components.stt_component.STT_CHAT_SEND_ENABLED", True):
        await stt_bundle.component._on_stt_result(STTResult(text="recognized text", language="ja-JP"))

    stt_bundle.component.send_chat_message.assert_awaited_once_with("recognized text", sender="owner")
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.chat_events.enqueue_external_message.assert_not_called()


@pytest.mark.asyncio
async def test_on_stt_result_enqueues_when_forward_enabled(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.shared.config.STT.FORWARD_TO_TTS = True
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()

    with patch("core.components.stt_component.STT_CHAT_SEND_ENABLED", True):
        await stt_bundle.component._on_stt_result(STTResult(text="recognized text", language="ja-JP"))

    stt_bundle.component.send_chat_message.assert_awaited_once_with("recognized text", sender="owner")
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.chat_events.enqueue_external_message.assert_awaited_once()


def test_load_stt_result_ignore_words_reads_non_comment_lines(tmp_path: Path, stt_bundle: SimpleNamespace) -> None:
    dictionary_file = tmp_path / "stt_result_ignore_words.dic"
    dictionary_file.write_text("# comment\n\n12345678910\n  えっと、それでは、  \n", encoding="utf-8")
    stt_bundle.shared.config.DICTIONARY = MagicMock()
    stt_bundle.shared.config.DICTIONARY.PATH = str(tmp_path)

    loaded = stt_bundle.component._load_stt_result_ignore_words()

    assert loaded == ["12345678910", "えっと、それでは、"]


@pytest.mark.asyncio
async def test_on_stt_result_ignores_by_confidence_threshold(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()
    stt_bundle.component._forward_stt_result_to_chat_events = AsyncMock()

    with patch("core.components.stt_component.STT_CONFIDENCE_THRESHOLD", 0.9):
        await stt_bundle.component._on_stt_result(STTResult(text="recognized text", language="ja-JP", confidence=0.5))

    stt_bundle.component.send_chat_message.assert_not_called()
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.component._forward_stt_result_to_chat_events.assert_not_called()


@pytest.mark.asyncio
async def test_on_stt_result_ignores_phrase_from_dictionary(stt_bundle: SimpleNamespace) -> None:
    stt_bundle.component.send_chat_message = AsyncMock()
    stt_bundle.component.print_console_message = MagicMock()
    stt_bundle.component._forward_stt_result_to_chat_events = AsyncMock()
    stt_bundle.component._stt_result_ignore_words = ["noise marker"]

    await stt_bundle.component._on_stt_result(STTResult(text="abc noise marker xyz", language="ja-JP", confidence=0.99))

    stt_bundle.component.send_chat_message.assert_not_called()
    stt_bundle.component.print_console_message.assert_not_called()
    stt_bundle.component._forward_stt_result_to_chat_events.assert_not_called()

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from models.message_models import ChatMessageDTO

if TYPE_CHECKING:
    from twitchio import ChatMessage as TwitchMessage


def _make_twitch_message(*, text: str, fragments: list[SimpleNamespace], reply) -> SimpleNamespace:
    chatter = SimpleNamespace(
        id="123",
        name="alice",
        display_name="Alice",
        broadcaster=False,
        moderator=True,
        vip=False,
        subscriber=True,
    )
    return SimpleNamespace(
        text=text,
        fragments=fragments,
        reply=reply,
        chatter=chatter,
        id="msg-1",
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_chat_message_dto_from_twitch_message() -> None:
    fragments: list[SimpleNamespace] = [
        SimpleNamespace(type="text", text="Hello "),
        SimpleNamespace(type="emote", text="Kappa"),
        SimpleNamespace(type="text", text="world"),
    ]
    reply = SimpleNamespace(
        parent_message_body="@bob:en:ja:hi",
        parent_user=SimpleNamespace(display_name="Bob", name="bob"),
    )
    message: SimpleNamespace = _make_twitch_message(text="Hello Kappa world", fragments=fragments, reply=reply)

    dto: ChatMessageDTO = ChatMessageDTO.from_twitch_message(cast("TwitchMessage", message))

    assert dto.message_id == "msg-1"
    assert dto.content == "Hello Kappa world"
    assert dto.text == "Hello world"
    assert [frag.type for frag in dto.fragments] == ["text", "emote", "text"]
    assert dto.author.name == "alice"
    assert dto.author.display_name == "Alice"
    assert dto.author.moderator is True
    assert dto.author.subscriber is True
    assert dto.reply is not None
    assert dto.reply.parent_message_body == "@bob:en:ja:hi"
    assert dto.reply.parent_user_display_name == "Bob"
    assert dto.reply.parent_user_name == "bob"

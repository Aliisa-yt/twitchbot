from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from handlers.fragment_handler import EmoteHandler, Mention, MentionHandler
from models.message_models import ChatMessage
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    from models.message_models import ChatMessage


def _make_fragments(parts: list[tuple[str, str]]) -> list[SimpleNamespace]:
    return [SimpleNamespace(type=frag_type, text=text) for frag_type, text in parts]


def _make_message(parts: list[tuple[str, str]], *, is_replying: bool = False) -> ChatMessage:
    content: str = "".join(text for _frag_type, text in parts)
    fragments: list[SimpleNamespace] = _make_fragments(parts)
    return cast("ChatMessage", SimpleNamespace(content=content, fragments=fragments, is_replying=is_replying))


def test_emote_handler_limits_and_remove() -> None:
    parts: list[tuple[str, str]] = [
        ("text", "Hi "),
        ("emote", "Kappa"),
        ("text", " "),
        ("emote", "Kappa"),
        ("text", " "),
        ("emote", "Pog"),
    ]
    message: ChatMessage = _make_message(parts)

    handler = EmoteHandler(message)
    handler.set_same_emote_limit(1)
    handler.set_total_emotes_limit(2)
    handler.parse()

    assert handler.get_emote_strings() == "Kappa Pog"

    expected: str = StringUtils.replace_blanks(message.content, 9, 14)
    assert handler.remove(message.content) == expected

    expected_all: str = message.content
    expected_all = StringUtils.replace_blanks(expected_all, 3, 8)
    expected_all = StringUtils.replace_blanks(expected_all, 9, 14)
    expected_all = StringUtils.replace_blanks(expected_all, 15, 18)
    assert handler.remove_all(message.content) == expected_all


def test_emote_handler_total_limit_marks_excess() -> None:
    parts: list[tuple[str, str]] = [
        ("emote", "A"),
        ("text", " "),
        ("emote", "B"),
        ("text", " "),
        ("emote", "C"),
    ]
    message: ChatMessage = _make_message(parts)
    handler = EmoteHandler(message)
    handler.set_total_emotes_limit(2)
    handler.parse()

    assert handler.get_emote_strings() == "A B"
    assert handler.has_valid_emotes is True

    expected: str = StringUtils.replace_blanks(message.content, 4, 5)
    assert handler.remove(message.content) == expected


def test_emote_handler_limit_setters_reject_invalid() -> None:
    message: ChatMessage = _make_message([("text", "no emotes")])
    handler = EmoteHandler(message)

    with pytest.raises(ValueError, match=r"Invalid same_emote_limit value: -1\. Must be a non-negative integer\."):
        handler.set_same_emote_limit(-1)

    with pytest.raises(ValueError, match=r"Invalid total_emotes_limit value: -1\. Must be a non-negative integer\."):
        handler.set_total_emotes_limit(-1)

    handler.parse()

    with pytest.raises(RuntimeError):
        handler.set_same_emote_limit(1)

    with pytest.raises(RuntimeError):
        handler.set_total_emotes_limit(1)


def test_mention_handler_dedup_and_strings() -> None:
    parts: list[tuple[str, str]] = [
        ("text", "Hi "),
        ("mention", "@alice"),
        ("text", " "),
        ("mention", "@bob"),
        ("text", " "),
        ("mention", "@alice"),
    ]
    message: ChatMessage = _make_message(parts)
    original_content: str = message.content
    handler = MentionHandler(message)
    handler.parse()

    expected: str = StringUtils.replace_blanks(original_content, 15, 21)
    assert message.content == expected

    assert handler.get_mentions_strings() == "@alice @bob"
    assert handler.get_mentions_strings(is_speak=True) == "alice bob"

    message_reply: ChatMessage = _make_message(parts, is_replying=True)
    reply_handler = MentionHandler(message_reply)
    reply_handler.parse()
    assert reply_handler.get_mentions_strings() == "@bob"


def test_mention_handler_strip_and_shift() -> None:
    parts: list[tuple[str, str]] = [
        ("text", "Hi "),
        ("mention", "@alice"),
        ("text", " "),
        ("mention", "@bob"),
        ("text", " done"),
    ]
    message: ChatMessage = _make_message(parts)
    handler = MentionHandler(message)
    handler.parse()

    expected: str = StringUtils.replace_blanks(message.content, 3, 9)
    expected = StringUtils.replace_blanks(expected, 10, 14)
    assert handler.strip_mentions(message.content) == expected

    expected_atsign: str = StringUtils.replace_blanks(message.content, 3, 4)
    expected_atsign = StringUtils.replace_blanks(expected_atsign, 10, 11)
    assert handler.strip_mentions(message.content, atsign_only=True) == expected_atsign

    assert handler.strip_mention_at(message.content, 99) == message.content

    first: Mention | None = handler.shift_mention()
    assert first is not None
    assert first.name == "@alice"
    assert handler.get_mentions_strings() == "@bob"

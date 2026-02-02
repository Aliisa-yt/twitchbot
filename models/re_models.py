"""Regular expressions for Twitch bot message parsing.

Patterns for IRC message formats, commands, URLs, mentions, replies, and language designations.
"""

from __future__ import annotations

import re
from re import Pattern
from typing import Final

__all__: list[str] = [
    "CLEARCHAT_PATTERN",
    "CLEARMSG_PATTERN",
    "COMMAND_PATTERN",
    "MENTION_PATTERN",
    "ONE_LANGUAGE_DESIGNATION_PATTERN",
    "REPLY_PATTERN",
    "SERVER_CONFIG_PATTERN",
    "TWO_LANGUAGE_DESIGNATIONS_PATTERN",
    "URL_PATTERN",
]

# CLEARCHAT regular expression (extract channel and optional username)
# Example: ":tmi.twitch.tv CLEARCHAT #channel :username"
CLEARCHAT_PATTERN: Final[Pattern[str]] = re.compile(
    r"""
    :tmi\.twitch\.tv\s+
    (?P<command>CLEARCHAT)\s+
    \#(?P<channel>\w+)
    (?:\s+:(?P<username>\w+))?
""",
    re.VERBOSE,
)

# CLEARMSG regular expression (extract message ID)
# Example: "target-msg-id=abc123-456def-789ghi tmi-sent-ts=1618884477000"
CLEARMSG_PATTERN: Final[Pattern[str]] = re.compile(
    r"target-msg-id=(?P<msg_id>[a-zA-Z0-9\-]+).*tmi-sent-ts=(?P<msg_ts>[0-9]+)"
)

# Command pattern matching Twitch bot command templates
# Example: "{a-1, i2, s-3, t0, v1}"
COMMAND_PATTERN: Final[Pattern[str]] = re.compile(r"\{\s*((?:[aistv]-?\d+(?:,\s*|\s+))*[aistv]-?\d+)\s*\}")

# Regular expressions that match URLs and URL-like appearances
# Examples: "http://example.com", "https://www.example.com/path", "www.example.com", "example.com/path"
URL_PATTERN: Final[Pattern[str]] = re.compile(
    r"((?:(?:https?://)?(?:www\.)?)"
    r"[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)+"
    r"(?:/[^\s]*)?)"
)

# Regular expression that matches mentions in the format of @username
# Username rules:
# - 4 to 25 characters long
# - Alphanumeric characters and underscores only
# - Case insensitive
# - Non-ASCII usernames: 2 to 12 characters long, excluding '@' and non-word characters
MENTION_PATTERN: Final[Pattern[str]] = re.compile(
    r"(?:^|\s)(?P<mention>@(?:\w{4,25}|[^\W@]{2,12}))(?=\s|$)", flags=re.ASCII
)

# Regular expression that matches the reply format in the chat
# Matches the following patterns:
#   message [by display_name (name)] (src_lang > tgt_lang)
#   message [by display_name (name)]
#   message [by display_name] (src_lang > tgt_lang)
#   message [by display_name]
REPLY_PATTERN: Final[Pattern[str]] = re.compile(
    r"\[by\s+(?P<display_name>\w+)(?:\s+\((?P<name>\w+)\))?\]"
    r"(?:\s+\((?P<src_lang>[\w-]+)\s*>\s*(?P<tgt_lang>[\w-]+)\))?$"
)

# Regular expression that matches single language designation patterns
# Example: "en:" or "ja:"
ONE_LANGUAGE_DESIGNATION_PATTERN: Final[Pattern[str]] = re.compile(r"(?:^|\s)(?P<lang>[A-Za-z]{2,3}(?:-[A-Za-z]{2})?):")

# Regular expression that matches two language designation patterns
# Example: "en:ja:" or "fr:de:"
TWO_LANGUAGE_DESIGNATIONS_PATTERN: Final[Pattern[str]] = re.compile(
    r"(?:^|\s)(?P<lang1>[A-Za-z]{2,3}(?:-[A-Za-z]{2})?):(?P<lang2>[A-Za-z]{2,3}(?:-[A-Za-z]{2})?):"
)

# Regular expression that matches server configuration strings
# Example: "http://example.com:8080" or "example.com:8080"
# The protocol is optional, and the port must be a number.
SERVER_CONFIG_PATTERN: Final[Pattern[str]] = re.compile(
    r"^(?:(?P<protocol>[a-zA-Z][a-zA-Z0-9+.-]*)://)?(?P<host>[^:/?#]+):(?P<port>\d+)$"
)

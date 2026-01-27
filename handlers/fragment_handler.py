"""Handler for message fragments, providing parsing and manipulation of emotes and mentions.

This module defines handlers for analyzing and processing Twitch message fragments,
including emotes (Twitch-specific emotes) and mentions (@username references).
Both handlers extract elements from message fragments, apply restrictions, and provide
methods to manipulate these elements in message text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, NamedTuple

from utils.logger_utils import LoggerUtils
from utils.string_utils import StringUtils

if TYPE_CHECKING:
    import logging

    from models.message_models import ChatMessage


__all__: list[str] = ["EmoteHandler", "Mention", "MentionHandler", "Span"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class Span(NamedTuple):
    """Represents a character position range within a message.

    Attributes:
        start (int): The starting position (inclusive).
        end (int): The ending position (exclusive).
    """

    start: int
    end: int


# ============================================================================


@dataclass
class EmoteInfo:
    """Stores aggregated information for a single emote type.

    This class groups all occurrences of the same emote within a message,
    storing the emote name and all positions where it appears.

    Attributes:
        name (str): The name/identifier of the emote.
        spans (list[Span]): List of character positions for each occurrence of this emote.
    """

    name: str = ""
    spans: list[Span] = field(default_factory=list)


@dataclass
class Emote:
    """Stores detailed information about a single emote occurrence.

    Attributes:
        order (int): Position-based sort order. Set to MARKED_FOR_REMOVAL (-1) if restricted by limits.
        name (str): The name/identifier of the emote.
        span (Span): The character position range of this emote occurrence in the message.
    """

    order: int = -1
    name: str = ""
    span: Span = field(default=Span(start=0, end=0))


# Type alias for dictionary mapping emote names to their information
EmotesInfoDict = dict[str, EmoteInfo]


class EmoteHandler:
    """Analyzes and restricts emotes from Twitch chat messages.

    This class extracts emote information from message fragments, applies
    configurable limits to restrict emotes, and provides methods to retrieve
    or remove emotes from messages. Emotes can be limited by count per emote type
    or by total number across all emotes.
    """

    # Constant to mark emotes for removal due to limit restrictions
    MARKED_FOR_REMOVAL: Final[int] = -1

    def __init__(self, message: ChatMessage) -> None:
        """Initialize the EmoteHandler with a chat message.

        Args:
            message (ChatMessage): The chat message to analyze for emotes.
        """
        self._message: ChatMessage = message
        self._emote_list: list[Emote] = []
        self.same_limit: int = 0
        self.total_limit: int = 0
        self._parsed: bool = False

    def set_same_emote_limit(self, same_limit: int = 0) -> None:
        """Set a limit for the maximum occurrences of each emote.

        When set, emotes exceeding this limit will be marked for removal.
        Must be called before parse().

        Args:
            same_limit (int): Maximum number of times each emote can appear. 0 means no limit.

        Raises:
            ValueError: If same_limit is negative or not an integer.
            RuntimeError: If called after parse() has been invoked.
        """
        if not isinstance(same_limit, int) or same_limit < 0:
            msg: str = f"Invalid same_emote_limit value: {same_limit}. Must be a non-negative integer."
            raise ValueError(msg)
        if self._parsed:
            msg = "Cannot set limit after parsing. Set limits before calling parse()."
            raise RuntimeError(msg)
        self.same_limit = same_limit

    def set_total_emotes_limit(self, total_limit: int = 0) -> None:
        """Set a limit for the maximum total number of emotes in the message.

        When set, emotes beyond this total count will be marked for removal.
        Must be called before parse().

        Args:
            total_limit (int): Maximum total number of emotes allowed. 0 means no limit.

        Raises:
            ValueError: If total_limit is negative or not an integer.
            RuntimeError: If called after parse() has been invoked.
        """
        if not isinstance(total_limit, int) or total_limit < 0:
            msg: str = f"Invalid total_emotes_limit value: {total_limit}. Must be a non-negative integer."
            raise ValueError(msg)
        if self._parsed:
            msg = "Cannot set limit after parsing. Set limits before calling parse()."
            raise RuntimeError(msg)
        self.total_limit = total_limit

    def parse(self) -> None:
        """Parse emotes from the message and apply configured limits.

        Extracts emotes from message fragments and applies same_limit and total_limit
        restrictions. Must be called only once. Call this after setting limits via
        same_emote_limit() and total_emotes_limit().

        Raises:
            RuntimeError: If called more than once.
        """
        if self._parsed:
            logger.warning("Emote already parsed. Skipping re-parse.")
            return
        self._parse(self._message)
        self._parsed = True

    def get_emote_strings(self) -> str:
        """Get all valid (non-restricted) emotes as a space-separated string.

        Excludes emotes marked for removal by the configured limits.

        Returns:
            str: Space-separated string of valid emote names. Empty string if no valid emotes.
        """
        joined_strings: str = " ".join(e.name for e in self._emote_list if e.order != self.MARKED_FOR_REMOVAL)
        logger.debug("Concatenated emotes: %s", joined_strings)
        return joined_strings

    def _parse(self, message: ChatMessage) -> None:
        """Extract emote information from message fragments.

        Iterates through all fragments in the message, identifies emotes,
        and stores their information and positions. Then applies configured limits.

        Args:
            message (ChatMessage): The message to parse for emotes.
        """
        logger.debug("Message content: %s", message.content)

        self._emote_list.clear()
        emotes_info: EmotesInfoDict = {}
        current_pos: int = 0
        for fragment in message.fragments:
            fragment_length: int = len(fragment.text)
            if fragment.type == "emote":
                emote_name: str = fragment.text
                span: Span = Span(start=current_pos, end=current_pos + fragment_length)
                if emote_name not in emotes_info:
                    emotes_info[emote_name] = EmoteInfo(name=emote_name)
                emotes_info[emote_name].spans.append(span)
            current_pos += fragment_length
        logger.debug("Parsed emotes: %s", emotes_info)
        self._limit(emotes_info)

    def _limit(self, emotes_info: EmotesInfoDict) -> None:
        """Apply configured limits to emotes.

        Sequentially applies same-emote limits and total emote limits.

        Args:
            emotes_info (EmotesInfoDict): Dictionary mapping emote names to their information.
        """
        self._apply_same_limit(emotes_info)
        self._apply_total_limit()
        logger.debug("Limited emotes: %s", self._emote_list)

    def _apply_same_limit(self, emotes_info: EmotesInfoDict) -> None:
        """Apply per-emote occurrence limits.

        For each emote type, marks occurrences beyond same_limit as MARKED_FOR_REMOVAL.
        Sorts the result by position to maintain message order.

        Args:
            emotes_info (EmotesInfoDict): Dictionary mapping emote names to their information.
        """
        for info in emotes_info.values():
            for i, span in enumerate(info.spans):
                # Mark emotes beyond the limit for removal
                order: int = span.start if not self.same_limit or i < self.same_limit else self.MARKED_FOR_REMOVAL
                self._emote_list.append(Emote(order=order, name=info.name, span=span))
        # Sort by position to maintain the order of emotes in the message
        self._emote_list = sorted(self._emote_list, key=lambda e: e.span.start)

    def _apply_total_limit(self) -> None:
        """Apply total emote count limit.

        Marks emotes beyond the total_limit as MARKED_FOR_REMOVAL, excluding
        those already restricted by per-emote limits.
        """
        if self.total_limit:
            # Get list of emotes not already restricted by per-emote limits
            valid_emotes: list[Emote] = [e for e in self._emote_list if e.order != self.MARKED_FOR_REMOVAL]
            # Mark excess emotes for removal
            for emote in valid_emotes[self.total_limit :]:
                emote.order = self.MARKED_FOR_REMOVAL

    def remove_all(self, message: str) -> str:
        """Remove all emotes from the message.

        Args:
            message (str): The message text from which to remove emotes.

        Returns:
            str: The message with all emote positions replaced by spaces.
        """
        return self.remove(message, is_remove_all=True)

    def remove(self, message: str, *, is_remove_all: bool = False) -> str:
        """Replace emote positions in the message with spaces.

        Args:
            message (str): The message text from which to remove emotes.
            is_remove_all (bool): If True, remove all emotes. If False, remove only
                those marked for removal by the configured limits. Defaults to False.

        Returns:
            str: The message with emote positions replaced by spaces.

        Raises:
            IndexError: Logged as error but not raised (indicates corrupted data from Twitch).
        """
        message_list: list[str] = list(message)
        for emote in self._emote_list:
            if is_remove_all or emote.order == self.MARKED_FOR_REMOVAL:
                try:
                    for i in range(emote.span.start, emote.span.end):
                        message_list[i] = " "
                except IndexError:
                    # Unless the data from Twitch has been corrupted, there should be no exceptions.
                    logger.error("Index out of range for emote: %s", emote)
        result: str = "".join(message_list)
        logger.debug("Message after emote removal: '%s'", result)
        return result

    def __repr__(self) -> str:
        """Return string representation of the emote list.

        Returns:
            str: String representation of internal emote list.
        """
        return str(self._emote_list)

    @property
    def has_valid_emotes(self) -> bool:
        """Check if there are any emotes that are not marked for removal.

        Returns:
            bool: True if there are emotes not marked for removal, False otherwise.
        """
        return any(emote.order != self.MARKED_FOR_REMOVAL for emote in self._emote_list)


# ============================================================================


@dataclass
class Mention:
    """Stores information about a mention in a message.

    Attributes:
        name (str): The username of the mentioned user, prefixed with '@'.
        span (Span): The character position of the mention in the message.
    """

    name: str = ""
    span: Span = field(default=Span(start=0, end=0))


class MentionHandler:
    """Handles parsing and manipulation of mentions in chat messages.

    This class extracts mentions from message fragments, de-duplicate them,
    and provides methods to retrieve or remove mentions from messages.
    """

    def __init__(self, message: ChatMessage) -> None:
        """Initialize the MentionHandler with a chat message.

        Args:
            message (ChatMessage): The chat message to process for mentions.
        """
        self._message: ChatMessage = message
        self._mention_list: list[Mention] = []
        self._parsed: bool = False

    def parse(self) -> None:
        """Parse mentions from the message.

        Must be called explicitly to extract mentions.
        """
        if self._parsed:
            logger.warning("Mention already parsed. Skipping re-parse.")
            return
        self._parse()
        self._parsed = True

    def _parse(self) -> None:
        """Extract mentions, de-duplicate, and blank out duplicates in message content."""
        logger.debug("Message content before parsing: %s", self._message.content)

        seen_mentions: set[str] = set()
        current_pos: int = 0
        content: str = self._message.content

        for fragment in self._message.fragments:
            fragment_length: int = len(fragment.text)
            if fragment.type == "mention":
                mention: str = StringUtils.ensure_str(fragment.text)
                span: Span = Span(start=current_pos, end=current_pos + fragment_length)
                if mention in seen_mentions:
                    # Duplicate mention found; blank it out in the content.
                    content = StringUtils.replace_blanks(content, span.start, span.end)
                else:
                    seen_mentions.add(mention)
                    self._mention_list.append(Mention(mention, span))
            current_pos += fragment_length

        self._message.content = content
        logger.debug("Message content after dedup: %s", self._message.content)
        logger.debug("Extracted mentions: %s", self._mention_list)

    def get_mentions_strings(self, *, is_speak: bool = False) -> str:
        """Get all mentions as a concatenated string.

        When is_speak is True, the '@' prefix is removed for speech synthesis.
        For reply messages, the first mention (indicating the reply target) is excluded.

        Args:
            is_speak (bool): If True, remove '@' prefix from mentions for speech output.

        Returns:
            str: Space-separated string of mention names.
        """
        result: str = ""
        for idx, mention in enumerate(self._mention_list):
            # Skip the first mention in reply messages as it indicates the reply target.
            if self._message.is_replying and idx == 0:
                continue
            # Remove '@' prefix when generating text for speech synthesis.
            name: str = mention.name.replace("@", "") if is_speak else mention.name
            result += name + " "
        return result.strip()

    def _remove_mention_from_message(self, message: str, mention: Mention, *, atsign_only: bool = False) -> str:
        """Remove a mention from the message string.

        Args:
            message (str): The message string to process.
            mention (Mention): The mention to remove.
            atsign_only (bool): If True, remove only the '@' symbol; otherwise, remove the entire mention.

        Returns:
            str: The message string with the mention removed.
        """
        start: int = mention.span.start
        end: int = mention.span.end
        if atsign_only:
            # Remove only the '@' symbol.
            message = StringUtils.replace_blanks(message, start, start + 1)
        else:
            message = StringUtils.replace_blanks(message, start, end)
        return message

    def strip_mentions(self, message: str, *, atsign_only: bool = False) -> str:
        """Remove all mentions from the given message string.

        Args:
            message (str): The message string to process.
            atsign_only (bool): If True, remove only the '@' symbol; otherwise, remove the entire mention.

        Returns:
            str: The message string with mentions removed.
        """
        for mention in self._mention_list:
            message = self._remove_mention_from_message(message, mention, atsign_only=atsign_only)
        logger.debug("Message after mention removal: '%s'", message)
        return message

    def strip_mention_at(self, message: str, index: int, *, atsign_only: bool = False) -> str:
        """Remove a specific mention at the given index from the message string.

        Args:
            message (str): The message string to process.
            index (int): The zero-based index of the mention to remove.
            atsign_only (bool): If True, remove only the '@' symbol; otherwise, remove the entire mention.

        Returns:
            str: The message string with the specified mention removed.
        """
        if index < 0 or index >= len(self._mention_list):
            logger.warning("Invalid mention index: %d (list size: %d)", index, len(self._mention_list))
            return message

        mention: Mention = self._mention_list[index]
        message = self._remove_mention_from_message(message, mention, atsign_only=atsign_only)
        logger.debug("Message after removing mention at index %d: '%s'", index, message)
        return message

    def shift_mention(self) -> Mention | None:
        """Remove and return the first mention from the mention list.

        Returns:
            Mention | None: The first mention if available; otherwise, None.
        """
        if self._mention_list:
            return self._mention_list.pop(0)
        return None

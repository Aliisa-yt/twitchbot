"""Data models for chat messages.

Defines ChatMessage dataclass for content, author information, translation details, and TTS parameters.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING

from models.re_models import REPLY_PATTERN
from models.translation_models import TranslationInfo
from models.voice_models import TTSParam
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from datetime import datetime
    from re import Match

    from twitchio import ChatMessage as TwitchMessage
    from twitchio import ChatMessageFragment, ChatMessageReply, Chatter

    from handlers.fragment_handler import EmoteHandler, MentionHandler
    from models.config_models import Config, TTSFormat


__all__: list[str] = [
    "ChatMessage",
    "ChatMessageAuthorDTO",
    "ChatMessageDTO",
    "ChatMessageFragmentDTO",
    "ChatMessageReplyDTO",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


@dataclass
class ChatMessageFragmentDTO:
    """Lightweight fragment data for DTO transport."""

    type: str = ""
    text: str = ""


@dataclass
class ChatMessageAuthorDTO:
    """Lightweight author data for DTO transport."""

    id: str = ""
    name: str = ""
    display_name: str = ""
    broadcaster: bool = False
    moderator: bool = False
    vip: bool = False
    subscriber: bool = False


@dataclass
class ChatMessageReplyDTO:
    """Lightweight reply data for DTO transport."""

    parent_message_body: str = ""
    parent_user_display_name: str = ""
    parent_user_name: str = ""


@dataclass
class ChatMessageDTO:
    """Lightweight chat message DTO for queue transport."""

    message_id: str = ""
    content: str = ""
    text: str = ""
    fragments: list[ChatMessageFragmentDTO] = field(default_factory=list)
    author: ChatMessageAuthorDTO = field(default_factory=ChatMessageAuthorDTO)
    timestamp: datetime | None = None
    reply: ChatMessageReplyDTO | None = None

    @classmethod
    def from_twitch_message(cls, twitch_message: TwitchMessage) -> ChatMessageDTO:
        """Create a DTO from a TwitchIO ChatMessage.

        Args:
            twitch_message (TwitchMessage): Incoming Twitch chat message.

        Returns:
            ChatMessageDTO: DTO snapshot of the message.
        """
        from utils.string_utils import StringUtils  # noqa: PLC0415

        content: str = StringUtils.ensure_str(twitch_message.text)
        text_parts: list[str] = []
        fragments: list[ChatMessageFragmentDTO] = []
        for fragment in twitch_message.fragments:
            fragment_text: str = StringUtils.ensure_str(fragment.text)
            fragments.append(ChatMessageFragmentDTO(type=fragment.type, text=fragment_text))
            if fragment.type == "text":
                text_parts.append(fragment_text)

        author: ChatMessageAuthorDTO = ChatMessageAuthorDTO(
            id=StringUtils.ensure_str(twitch_message.chatter.id),
            name=StringUtils.ensure_str(twitch_message.chatter.name),
            display_name=StringUtils.ensure_str(twitch_message.chatter.display_name),
            broadcaster=bool(twitch_message.chatter.broadcaster),
            moderator=bool(twitch_message.chatter.moderator),
            vip=bool(twitch_message.chatter.vip),
            subscriber=bool(twitch_message.chatter.subscriber),
        )

        reply: ChatMessageReplyDTO | None = None
        if twitch_message.reply is not None:
            reply = ChatMessageReplyDTO(
                parent_message_body=StringUtils.ensure_str(twitch_message.reply.parent_message_body),
                parent_user_display_name=StringUtils.ensure_str(twitch_message.reply.parent_user.display_name),
                parent_user_name=StringUtils.ensure_str(twitch_message.reply.parent_user.name),
            )

        return cls(
            message_id=StringUtils.ensure_str(twitch_message.id),
            content=content,
            text="".join(text_parts),
            fragments=fragments,
            author=author,
            timestamp=twitch_message.timestamp,
            reply=reply,
        )


@dataclass
class _ReplyMessage:
    name: str = ""
    src_lang: str = ""
    tgt_lang: str = ""
    is_replying: bool = False


@dataclass
class ChatMessage:
    twitch_message: InitVar[TwitchMessage | ChatMessageDTO]
    config: InitVar[Config]
    content: str = ""
    text: str = ""
    author: Chatter | ChatMessageAuthorDTO = field(init=False)
    id: str = ""
    timestamps: datetime | None = None
    display_name: str = ""
    _reply: _ReplyMessage = field(default_factory=_ReplyMessage)
    trans_info: TranslationInfo = field(default_factory=TranslationInfo)
    tts_param: TTSParam = field(default_factory=TTSParam)
    emote: EmoteHandler = field(init=False)
    mention: MentionHandler = field(init=False)
    tts_format: TTSFormat = field(init=False)
    fragments: list[ChatMessageFragment | ChatMessageFragmentDTO] = field(default_factory=list)

    def __post_init__(self, twitch_message: TwitchMessage | ChatMessageDTO, config: Config) -> None:
        # Lazy import to avoid circular import when models/__init__.py exports ChatMessage
        from handlers.fragment_handler import EmoteHandler, MentionHandler  # noqa: PLC0415
        from utils.string_utils import StringUtils  # noqa: PLC0415

        if isinstance(twitch_message, ChatMessageDTO):
            self.content = StringUtils.ensure_str(twitch_message.content)
            self.text = StringUtils.ensure_str(twitch_message.text)
            self.author = twitch_message.author
            self.id = StringUtils.ensure_str(twitch_message.message_id)
            self.timestamps = twitch_message.timestamp
            self.fragments = list(twitch_message.fragments)

            self.display_name = StringUtils.ensure_str(twitch_message.author.display_name)
            self.is_replying = twitch_message.reply is not None

            if twitch_message.reply is not None:
                self._process_reply_info_dto(twitch_message.reply)
        else:
            self.content = StringUtils.ensure_str(twitch_message.text)

            self.text = ""
            for fragment in twitch_message.fragments:
                if fragment.type == "text":
                    self.text += StringUtils.ensure_str(fragment.text)

            self.author = twitch_message.chatter
            self.id = str(twitch_message.id)
            self.timestamps = twitch_message.timestamp
            self.fragments = list(twitch_message.fragments)

            self.display_name = StringUtils.ensure_str(twitch_message.chatter.display_name)
            self.is_replying = twitch_message.reply is not None

            # Process reply information if the message is a reply
            if twitch_message.reply is not None:
                self._process_reply_info(twitch_message)

        self.tts_format: TTSFormat = config.TTS_FORMAT
        self.emote: EmoteHandler = EmoteHandler(self)
        self.mention: MentionHandler = MentionHandler(self)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({', '.join(f"{key[1:]}='{value}'" for key, value in self.__dict__.items())})"

    def _process_reply_info(self, twitch_message: TwitchMessage) -> None:
        """Extract and process reply information from a chat message.

        If the message has a reply, extracts the parent user's display name and language codes.
        Attempts to extract language codes from the parent message body using REPLY_PATTERN.
        Falls back to the parent user's display name if the pattern does not match.
        Returns early if no reply is present.

        Args:
            twitch_message (TwitchMessage): The Twitch chat message to process.

        Raises:
            ValueError: If reply display name cannot be extracted when REPLY_PATTERN is matched.
        """
        from utils.string_utils import StringUtils  # noqa: PLC0415

        reply: ChatMessageReply | None = twitch_message.reply
        if reply is None:
            logger.debug("Reply payload is missing; skipping reply info processing")
            return

        decoded_message: str = reply.parent_message_body
        match: Match[str] | None = REPLY_PATTERN.search(decoded_message)

        if match:
            self.reply_name = StringUtils.ensure_str(match.group("display_name"))
            if not self.reply_name:
                msg = "Reply display name cannot be empty when matched by REPLY_PATTERN."
                raise ValueError(msg)

            # When replying, set the source language code of the reply to the target language code so that
            # the reply content is translated into the target language, and set the target language code
            # of the reply to the source language code.
            self.reply_tgt_lang = StringUtils.ensure_str(match.group("src_lang"))
            self.reply_src_lang = StringUtils.ensure_str(match.group("tgt_lang"))
            logger.debug(
                "Reply pattern matched: name='%s', src_lang='%s', tgt_lang='%s'",
                self.reply_name,
                self.reply_src_lang,
                self.reply_tgt_lang,
            )
        else:
            self.reply_name = StringUtils.ensure_str(reply.parent_user.display_name)
            # Fallback to the username if display name is not available.
            if not self.reply_name:
                self.reply_name = StringUtils.ensure_str(reply.parent_user.name)

            self.reply_src_lang = ""
            self.reply_tgt_lang = ""
            logger.debug("Reply pattern not matched, using fallback display name: '%s'", self.reply_name)

    def _process_reply_info_dto(self, reply: ChatMessageReplyDTO) -> None:
        """Extract and process reply information from DTO data.

        Args:
            reply (ChatMessageReplyDTO): Reply payload stored in the DTO.
        """
        from utils.string_utils import StringUtils  # noqa: PLC0415

        decoded_message: str = reply.parent_message_body
        match: Match[str] | None = REPLY_PATTERN.search(decoded_message)

        if match:
            self.reply_name = StringUtils.ensure_str(match.group("display_name"))
            if not self.reply_name:
                msg = "Reply display name cannot be empty when matched by REPLY_PATTERN."
                raise ValueError(msg)

            self.reply_tgt_lang = StringUtils.ensure_str(match.group("src_lang"))
            self.reply_src_lang = StringUtils.ensure_str(match.group("tgt_lang"))
            logger.debug(
                "Reply pattern matched: name='%s', src_lang='%s', tgt_lang='%s'",
                self.reply_name,
                self.reply_src_lang,
                self.reply_tgt_lang,
            )
        else:
            self.reply_name = StringUtils.ensure_str(reply.parent_user_display_name)
            if not self.reply_name:
                self.reply_name = StringUtils.ensure_str(reply.parent_user_name)

            self.reply_src_lang = ""
            self.reply_tgt_lang = ""
            logger.debug("Reply pattern not matched, using fallback display name: '%s'", self.reply_name)

    @property
    def reply_name(self) -> str:
        return self._reply.name

    @reply_name.setter
    def reply_name(self, value: str) -> None:
        self._reply.name = value

    @property
    def reply_src_lang(self) -> str:
        return self._reply.src_lang

    @reply_src_lang.setter
    def reply_src_lang(self, value: str) -> None:
        self._reply.src_lang = value

    @property
    def reply_tgt_lang(self) -> str:
        return self._reply.tgt_lang

    @reply_tgt_lang.setter
    def reply_tgt_lang(self, value: str) -> None:
        self._reply.tgt_lang = value

    @property
    def is_replying(self) -> bool:
        return self._reply.is_replying

    @is_replying.setter
    def is_replying(self, value: bool) -> None:
        self._reply.is_replying = value

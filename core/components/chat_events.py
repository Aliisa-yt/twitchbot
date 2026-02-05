from __future__ import annotations

import time
from typing import TYPE_CHECKING

from twitchio.ext.commands import Component

from core.components.base import Base
from core.trans.manager import TransManager
from handlers.chat_message import ChatMessageHandler
from models.translation_models import TranslationInfo
from utils.chat_utils import ChatUtils
from utils.logger_utils import LoggerUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    import logging

    from twitchio import ChannelChatClear, ChannelChatClearUserMessages, ChatMessageDelete
    from twitchio import ChatMessage as TwitchMessage

    from models.voice_models import TTSParam


__all__: list[str] = ["ChatEventsCog"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class ChatEventsCog(Base):
    """Handler for Twitch chat events (message, clear, delete).

    This cog listens for incoming Twitch chat messages and processes them for translation and TTS.
    It filters messages, detects language, translates content, and queues audio for playback.
    """

    @Component.listener()
    async def event_message_delete(self, payload: ChatMessageDelete) -> None:
        """
        Receive a message delete event from the IRC server.
        This event is sent when a message is deleted.
        """
        logger.debug("event_message_delete payload '%s'", payload)

    @Component.listener()
    async def event_chat_clear(self, payload: ChannelChatClear) -> None:
        """
        Receive a chat clear event from the IRC server.
        This event is sent when the chat box is cleared.
        """
        _ = payload
        logger.debug("Chat has been cleared")
        # The queue must be cleared before stopping playback.
        # Otherwise, the next playback may start immediately after the playback is stopped.
        await self.tts_manager.playback_queue.clear(callback=self.tts_manager.file_remove)
        # Playback will stop unconditionally when the chat box is cleared.
        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")

    @Component.listener()
    async def event_chat_clear_user(self, payload: ChannelChatClearUserMessages) -> None:
        """
        Receive a chat clear user messages event from the IRC server.
        This event is sent when all messages from a specific user are deleted.
        """
        logger.debug("event_chat_clear_user payload '%s'", payload)

    # When a new message arrives, the processing of the new message is initiated.
    # However, this does not trigger immediate execution.
    # If control is transferred to the TwitchIO event handler via await during processing,
    # a new event message is generated.
    # Consequently, multiple messages are processed while switching via await.
    @Component.listener()
    async def event_message(self, payload: TwitchMessage) -> None:
        """Process incoming Twitch chat messages for translation and TTS.

        This method handles message preprocessing, language detection, translation,
        and TTS queue preparation. It respects configuration settings for original and
        translated text processing.

        Args:
            payload (TwitchMessage): The Twitch message event payload.
        """
        logger.debug("event_message payload '%s'", payload)

        if self._should_ignore_message(payload):
            return

        # Note: The method for retrieving CLEARMSG has changed in Twitchio v3, necessitating a complete rebuild.
        # if self.config.BOT.AWAITING_CLEARMSG:
        #     wait_time: float = self.config.BOT.AWAITING_CLEARMSG
        #     logger.debug("CLEARMSG notification waiting time: %.1fsec", wait_time)
        #     await asyncio.sleep(wait_time)

        start_time: float = time.perf_counter()

        message: ChatMessageHandler = self._preprocess_message(payload)

        temp_trans_info: TranslationInfo = TranslationInfo(content=message.content)
        TransManager.parse_language_prefix(temp_trans_info)
        message.content = temp_trans_info.content

        # Remove emotes and mentions from content
        trans_info: TranslationInfo = self.prepare_translate_parameters(message)
        # Apply forced language code settings to trans_info
        if temp_trans_info.src_lang is not None:
            trans_info.src_lang = temp_trans_info.src_lang
        if temp_trans_info.tgt_lang is not None:
            trans_info.tgt_lang = temp_trans_info.tgt_lang

        self.trans_manager.refresh_active_engine_list()

        # Language detection (if the source language is not set)
        if trans_info.src_lang is None and not await self.trans_manager.detect_language(trans_info):
            # detect_language returns False when content is empty.
            # If the content is empty but contains emotes, set default languages and continue.
            # Otherwise, skip processing for this message.
            if not message.emote.has_valid_emotes:
                return
            trans_info.src_lang = self.config.TRANSLATION.NATIVE_LANGUAGE
            trans_info.tgt_lang = self.config.TRANSLATION.SECOND_LANGUAGE
            logger.debug(
                "Content is empty but contains emotes. Setting default languages: src_lang=%s, tgt_lang=%s",
                trans_info.src_lang,
                trans_info.tgt_lang,
            )

        await self._process_original_tts(message, trans_info)

        if not self.trans_manager.determine_target_language(trans_info):
            # The target language could not be identified.
            return

        if not await self.trans_manager.perform_translation(trans_info):
            # The translation process has failed.
            return

        await self._process_translated_tts(message, trans_info)

        await self._output_and_send_translation(message, trans_info)

        logger.debug("'process time': '%.3fsec'", time.perf_counter() - start_time)

    def _should_ignore_message(self, payload: TwitchMessage) -> bool:
        """Check if the message should be ignored.

        Args:
            payload (TwitchMessage): The Twitch message payload.
        Returns:
            bool: True if the message should be ignored, False otherwise.
        """
        return (
            payload.chatter.id == self.bot.bot_id
            or payload.source_broadcaster is not None
            or payload.text is None
            or payload.text.strip() == ""
            or payload.text.startswith("!")
            or ChatUtils.is_ignore_users(self.config, payload.chatter.name)
        )

    def _preprocess_message(self, payload: TwitchMessage) -> ChatMessageHandler:
        """Preprocess the message (emote/emoji handling, TTS parameters).

        Args:
            payload (TwitchMessage): The Twitch message payload.
        Returns:
            ChatMessageHandler: The preprocessed chat message handler instance.
        """
        message = ChatMessageHandler(payload, config=self.config)

        message.emote.set_same_emote_limit(self.config.TTS.LIMIT_SAME_EMOTE)
        message.emote.set_total_emotes_limit(self.config.TTS.LIMIT_TOTAL_EMOTES)
        message.emote.parse()
        message.mention.parse()

        self.prepare_tts_voice_parameters(message)
        return message

    async def _process_original_tts(self, message: ChatMessageHandler, trans_info: TranslationInfo) -> None:
        """Process original text output and TTS.

        Output original text to console and prepare TTS if enabled.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            trans_info (TranslationInfo): The translation information instance.
        """
        self.print_console_message(
            message.formatting_messages(content=trans_info.content, language=trans_info.src_lang),
            header="<- ",
        )

        if self.config.TTS.ORIGINAL_TEXT:
            tts_param: TTSParam = TTSUtils.create_tts_parameters(self.config, message)
            tts_param.content_lang = trans_info.src_lang
            queue_data: TTSParam | None = self.prepare_original_text(message=message, tts_param=tts_param)
            if queue_data is not None:
                await self.store_tts_queue(queue_data)

    async def _process_translated_tts(self, message: ChatMessageHandler, trans_info: TranslationInfo) -> None:
        """Process translated text TTS.

        Prepare TTS for translated text if enabled.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            trans_info (TranslationInfo): The translation information instance.
        """
        if self.config.TTS.TRANSLATED_TEXT:
            queue_data: TTSParam | None = self.prepare_translated_text(message=message, trans_info=trans_info)
            if queue_data is not None:
                await self.store_tts_queue(queue_data)

    async def _output_and_send_translation(self, message: ChatMessageHandler, trans_info: TranslationInfo) -> None:
        """Output translated text to console and send to chat.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            trans_info (TranslationInfo): The translation information instance.
        """
        footer: str = ChatUtils.generate_footer(self.config, message, trans_info)
        trans_info.translated_text = message.formatting_messages(
            content=trans_info.translated_text, language=trans_info.tgt_lang, is_translated=True
        )
        self.print_console_message(trans_info.translated_text, header="-> ", footer=footer)
        await self.send_chat_message(trans_info.translated_text, header="/me ", footer=footer)

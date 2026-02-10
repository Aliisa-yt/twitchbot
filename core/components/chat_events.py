from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from twitchio.ext.commands import Component

from core.components.base import ComponentBase
from core.trans.manager import TransManager
from handlers.chat_message import ChatMessageHandler
from models.message_models import ChatMessageDTO
from models.translation_models import TranslationInfo
from utils.chat_utils import ChatUtils
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from twitchio import ChannelChatClear, ChannelChatClearUserMessages, ChatMessageDelete
    from twitchio import ChatMessage as TwitchMessage

    from core.bot import Bot
    from models.voice_models import TTSParam


__all__: list[str] = ["ChatEventsManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

MESSAGE_QUEUE_MAX_SIZE: int = 50
MESSAGE_QUEUE_USAGE_DEBUG_THRESHOLD: float = 0.9

COMPONENT_KWARGS: dict[str, int] = {"priority": 0}


class ChatEventsManager(ComponentBase, **COMPONENT_KWARGS):
    """Handler for Twitch chat events (message, clear, delete).

    This cog listens for incoming Twitch chat messages and processes them for translation and TTS.
    It filters messages, detects language, translates content, and queues audio for playback.
    """

    def __init__(self, bot: Bot) -> None:
        super().__init__(bot)
        self._message_queue: ExcludableQueue[ChatMessageDTO] = ExcludableQueue(maxsize=MESSAGE_QUEUE_MAX_SIZE)
        self._message_worker_task: asyncio.Task[None] | None = None

    async def component_load(self) -> None:
        """Load the component. No setup required for this component."""
        if self._message_worker_task is None:
            self._message_worker_task = asyncio.create_task(self._message_worker_loop())
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component. No teardown required for this component."""
        await self._message_queue.clear()
        if self._message_worker_task is not None:
            self._message_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._message_worker_task
            self._message_worker_task = None
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    @Component.listener()
    async def event_message_delete(self, payload: ChatMessageDelete) -> None:
        """
        Receive the 'event_message_delete' event from TwitchIO.
        This event is triggered when a message is deleted.

        Args:
            payload (ChatMessageDelete): The chat message delete event payload.

        Note: This event handler is not implemented.
        """
        logger.debug("event_message_delete payload '%s'", payload)

    @Component.listener()
    async def event_chat_clear(self, payload: ChannelChatClear) -> None:
        """
        Receive the 'event_chat_clear' event from TwitchIO.
        This event is triggered when the chat box is cleared.

        Args:
            payload (ChannelChatClear): The chat clear event payload.
        """
        _ = payload
        logger.debug("Chat has been cleared")

        await self._message_queue.clear()

        # The queue must be cleared before stopping playback.
        # Otherwise, the next playback may start immediately after the playback is stopped.
        async def _enqueue_delete(tts_param: TTSParam) -> None:
            _file_path: Path | None = tts_param.filepath
            if _file_path is not None:
                self.tts_manager.file_manager.enqueue_file_deletion(_file_path)

        await self.tts_manager.playback_queue.clear(callback=_enqueue_delete)

        # Playback will stop unconditionally when the chat box is cleared.
        if self.tts_manager.playback_manager.is_playing:
            await self.tts_manager.playback_manager.cancel_playback()
            logger.debug("Current playback cancelled.")

    @Component.listener()
    async def event_chat_clear_user(self, payload: ChannelChatClearUserMessages) -> None:
        """
        Receive the 'event_chat_clear_user' event from TwitchIO.
        This event is triggered when all messages from a specific user are deleted.

        Args:
            payload (ChannelChatClearUserMessages): The chat clear user messages event payload.

        Note: This event handler is not implemented.
        """
        logger.debug("event_chat_clear_user payload '%s'", payload)

    # Message handling is queued to avoid re-entrancy when awaits yield back to TwitchIO.
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

        dto: ChatMessageDTO = ChatMessageDTO.from_twitch_message(payload)
        await self._enqueue_message(dto)

    async def _enqueue_message(self, dto: ChatMessageDTO) -> None:
        """Enqueue a chat message DTO for processing.

        Args:
            dto (ChatMessageDTO): The chat message data transfer object.
        """
        if self._message_queue.full():
            logger.warning("Message queue full. Dropping message id '%s'.", dto.message_id)
            return
        maxsize: int = self._message_queue.maxsize
        if maxsize > 0:
            projected_size: int = self._message_queue.qsize() + 1
            usage: float = projected_size / maxsize
            if usage >= MESSAGE_QUEUE_USAGE_DEBUG_THRESHOLD:
                logger.debug("Message queue usage %.0f%% (%d/%d)", usage * 100, projected_size, maxsize)
        await self._message_queue.put(dto)

    async def _message_worker_loop(self) -> None:
        """Worker loop to process messages from the queue.

        This loop continuously retrieves messages from the queue and processes them.
        """
        while True:
            dto: ChatMessageDTO = await self._message_queue.get()
            try:
                await self._handle_message(dto)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - isolate worker failures
                logger.error("Message worker error: %s", err)
            finally:
                self._message_queue.task_done()

    async def _handle_message(self, dto: ChatMessageDTO) -> None:
        """Handle a chat message DTO for translation and TTS processing.

        Args:
            dto (ChatMessageDTO): The chat message data transfer object.
        """
        start_time: float = time.perf_counter()

        message: ChatMessageHandler = self._preprocess_message(dto)

        temp_trans_info: TranslationInfo = TranslationInfo(content=message.content)
        TransManager.parse_language_prefix(temp_trans_info)
        message.content = temp_trans_info.content

        # Strip emotes/mentions before translation.
        trans_info: TranslationInfo = self.prepare_translate_parameters(message)
        # Apply forced language settings from prefixes.
        if temp_trans_info.src_lang is not None:
            trans_info.src_lang = temp_trans_info.src_lang
        if temp_trans_info.tgt_lang is not None:
            trans_info.tgt_lang = temp_trans_info.tgt_lang

        self.trans_manager.refresh_active_engine_list()

        # Detect language when not explicitly provided.
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
            return

        if not await self.trans_manager.perform_translation(trans_info):
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

    def _preprocess_message(self, payload: TwitchMessage | ChatMessageDTO) -> ChatMessageHandler:
        """Preprocess the message (emote/emoji handling, TTS parameters).

        Args:
            payload (TwitchMessage | ChatMessageDTO): The chat message payload.

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
            header="<- " + ChatUtils.get_current_time() + " ",
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
        self.print_console_message(
            trans_info.translated_text, header="-> " + ChatUtils.get_current_time() + " ", footer=footer
        )
        await self.send_chat_message(trans_info.translated_text, header="/me ", footer=footer)

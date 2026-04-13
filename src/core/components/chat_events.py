import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, ClassVar, Final, override

from twitchio.ext.commands import Component

from core.components.base import ComponentBase
from core.trans.trans_manager import TransManager
from handlers.chat_message import ChatMessageHandler
from models.message_models import ChatMessageDTO
from models.translation_models import TranslationInfo
from utils.chat_utils import ChatUtils
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils
from utils.time_utils import TimeUtils
from utils.tts_utils import TTSUtils

if TYPE_CHECKING:
    import logging

    from twitchio import ChannelChatClear, ChannelChatClearUserMessages, ChatMessageDelete
    from twitchio import ChatMessage as TwitchMessage

    from core.bot import Bot
    from models.voice_models import TTSParam


__all__: list[str] = ["ChatEventsManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

MESSAGE_QUEUE_MAX_SIZE: Final[int] = 50
MESSAGE_QUEUE_USAGE_DEBUG_THRESHOLD: Final[float] = 0.9
MESSAGE_CONCURRENCY_DEFAULT: Final[int] = 3


class ChatEventsManager(ComponentBase):
    """Handler for Twitch chat events (message, clear, delete).

    This cog listens for incoming Twitch chat messages and processes them for translation and TTS.
    It filters messages, detects language, translates content, and queues audio for playback.

    Attributes:
        depends (ClassVar[list[str]]): List of component dependencies.

    Event Listeners:
        event_message: Triggered when a new chat message is received.
        event_message_delete: Triggered when a chat message is deleted.
        event_chat_clear: Triggered when the chat box is cleared.
        event_chat_clear_user: Triggered when all messages from a specific user are deleted.
        event_safe_enqueue_message: Triggered when a message is enqueued via safe_dispatch.
    """

    depends: ClassVar[list[str]] = []

    def __init__(self, bot: Bot) -> None:
        super().__init__(bot)
        self._message_queue: ExcludableQueue[ChatMessageDTO] = ExcludableQueue(maxsize=MESSAGE_QUEUE_MAX_SIZE)
        self._message_worker_task: asyncio.Task[None] | None = None
        # tasks spawned per-message when using create_task approach
        self._spawned_tasks: set[asyncio.Task[None]] = set()
        # concurrency limiter (Semaphore) will be initialized in component_load
        self._concurrency_sem: asyncio.Semaphore | None = None
        self._is_available: bool = False

    @override
    async def component_load(self) -> None:
        """Initialize the component, including the message queue and concurrency semaphore."""
        max_concurrent: int = getattr(self.config.TTS, "MAX_CONCURRENT_MESSAGES", MESSAGE_CONCURRENCY_DEFAULT)
        try:
            max_concurrent = int(max_concurrent)
        except ValueError, TypeError:
            logger.warning(
                "Invalid MAX_CONCURRENT_MESSAGES value '%s'. Falling back to default: %d",
                max_concurrent,
                MESSAGE_CONCURRENCY_DEFAULT,
            )
            max_concurrent = MESSAGE_CONCURRENCY_DEFAULT
        if max_concurrent < 1:
            logger.warning(
                "MAX_CONCURRENT_MESSAGES must be >= 1. Falling back to default: %d",
                MESSAGE_CONCURRENCY_DEFAULT,
            )
            max_concurrent = MESSAGE_CONCURRENCY_DEFAULT
        self._concurrency_sem = asyncio.Semaphore(max_concurrent)
        self._is_available = True
        logger.debug("'%s' component loaded", self.__class__.__name__)

    @override
    async def component_teardown(self) -> None:
        """Teardown the component, including cancelling tasks and releasing resources."""
        self._is_available = False
        await self._message_queue.clear()
        if self._message_worker_task is not None:
            self._message_worker_task.cancel()
            try:
                await self._message_worker_task
            except BaseException as exc:  # noqa: BLE001
                if not isinstance(exc, asyncio.CancelledError):
                    logger.warning("Message worker exited with exception during teardown: %s", exc)
            self._message_worker_task = None
        # cancel and await any per-message tasks we spawned
        if self._spawned_tasks:
            for _t in list(self._spawned_tasks):
                _t.cancel()
            # Suppress CancelledError in case the calling coroutine itself is
            # cancelled while waiting; exceptions from spawned tasks are already
            # collected via return_exceptions=True.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._spawned_tasks, return_exceptions=True)
            self._spawned_tasks.clear()
        self._concurrency_sem = None
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

        # Cancel in-flight message tasks before clearing playback_queue.
        # Without this, a concurrent _handle_message_task may call store_tts_queue
        # after playback_queue.clear() completes, leaving orphaned items for playback.
        if self._spawned_tasks:
            for _t in list(self._spawned_tasks):
                _t.cancel()
            # Suppress CancelledError in case the calling coroutine itself is
            # cancelled while waiting; exceptions from spawned tasks are already
            # collected via return_exceptions=True.
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._spawned_tasks, return_exceptions=True)
            self._spawned_tasks.clear()
        logger.debug("Dispatching `tts_clear` event to clear TTS playback queue")
        self.bot.safe_dispatch("tts_clear")

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

    @Component.listener()
    async def event_safe_stt_message(self, payload: ChatMessageDTO) -> None:
        """Receive the 'event_safe_stt_message' event and forward to the internal queue.

        Args:
            payload (ChatMessageDTO): The chat message data transfer object dispatched via safe_dispatch.
        """
        await self._enqueue_message(payload)

    async def _enqueue_message(self, payload: ChatMessageDTO) -> None:
        """Enqueue a chat message DTO for processing.

        Args:
            payload (ChatMessageDTO): The chat message data transfer object.
        """
        if not self._is_available:
            # TwitchIO events may arrive before component_load completes or after teardown starts.
            # Events in this transient state are non-critical, so log at debug and drop them.
            logger.debug("ChatEventsManager is not available. Cannot enqueue message id '%s'.", payload.message_id)
            return
        if self._message_queue.full():
            logger.warning("Message queue full. Dropping message id '%s'.", payload.message_id)
            return
        maxsize: int = self._message_queue.maxsize
        if maxsize > 0:
            projected_size: int = self._message_queue.qsize() + 1
            usage: float = projected_size / maxsize
            if usage >= MESSAGE_QUEUE_USAGE_DEBUG_THRESHOLD:
                logger.debug("Message queue usage %.0f%% (%d/%d)", usage * 100, projected_size, maxsize)
        if not self._ensure_message_worker_running():
            return
        await self._message_queue.put(payload)

    def _ensure_message_worker_running(self) -> bool:
        """Ensure the message worker task is running to process messages from the queue.

        Returns:
            bool: True if the worker is running or was successfully started, False if the component is unavailable.
        """

        if not self._is_available:
            logger.warning("ChatEventsManager is not available. Cannot enqueue message.")
            return False
        task: asyncio.Task[None] | None = self._message_worker_task
        if task is None or task.done():
            if task is not None and not task.cancelled():
                try:
                    exc: BaseException | None = task.exception()
                    if exc is not None:
                        logger.error("Message worker exited with exception: %s", exc, exc_info=exc)
                except asyncio.CancelledError:
                    pass
                except Exception as err:  # noqa: BLE001
                    logger.warning("Message worker task ended unexpectedly: %s", err)

            try:
                self._message_worker_task = asyncio.create_task(
                    self._message_worker_loop(),
                    name="ChatEventsManagerMessageWorker",
                )
            except RuntimeError:  # noqa: BLE001
                logger.exception("Failed to start message worker task")
                self._message_worker_task = None
                return False
        return True

    async def _message_worker_loop(self) -> None:
        """Worker loop to process messages from the queue.

        This loop continuously retrieves messages from the queue and processes them.
        """
        while True:
            dto: ChatMessageDTO = await self._message_queue.get()
            semaphore: asyncio.Semaphore | None = self._concurrency_sem
            if semaphore is None:
                logger.error("Concurrency semaphore is not initialized. Dropping message id '%s'.", dto.message_id)
                with contextlib.suppress(ValueError, RuntimeError):
                    self._message_queue.task_done()
                continue

            await semaphore.acquire()
            # spawn a background task per message; concurrency is limited by semaphore
            try:
                task: asyncio.Task[None] = asyncio.create_task(
                    self._handle_message_task(dto, semaphore),
                    name=f"ChatEventsManagerMessageTask-{dto.message_id}",
                )
            except Exception:  # noqa: BLE001
                # In case of failure to create a task,
                # release the semaphore and mark the message as done to prevent deadlock.
                semaphore.release()
                with contextlib.suppress(ValueError, RuntimeError):
                    self._message_queue.task_done()
                raise
            self._spawned_tasks.add(task)
            task.add_done_callback(self._task_done_callback)

    async def _handle_message_task(self, dto: ChatMessageDTO, semaphore: asyncio.Semaphore) -> None:
        """Wrapper that enforces concurrency via semaphore and ensures task_done() is called."""
        try:
            await self._handle_message(dto)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate handler failures
            logger.exception("Message handler task error")
        finally:
            semaphore.release()
            # mark queue item as processed when the background task finishes
            # suppress ValueError (double task_done) and RuntimeError (queue edge cases)
            with contextlib.suppress(ValueError, RuntimeError):
                self._message_queue.task_done()

    def _task_done_callback(self, task: asyncio.Task[None]) -> None:
        """Callback for spawned tasks to remove them from tracking and log exceptions."""
        self._spawned_tasks.discard(task)
        try:
            exc: BaseException | None = task.exception()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return
        if exc is not None:
            logger.error("Spawned message task finished with exception: %s", exc, exc_info=exc)

    async def _handle_message(self, dto: ChatMessageDTO) -> None:
        """Handle a chat message DTO for translation and TTS processing.

        Args:
            dto (ChatMessageDTO): The chat message data transfer object.
        """
        start_time: float = time.perf_counter()
        logger.debug("Handling message id '%s' from user '%s'", dto.message_id, dto.author)

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
            logger.debug(
                "No valid target language determined for message id '%s'. Skipping translation.", dto.message_id
            )
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
        # Avoid lint errors caused by Twitchio not defining types correctly.
        if not isinstance(payload.id, str):
            return True
        # echo messages sent by the bot itself should be ignored to prevent loops
        if payload.id in self.bot.send_message_cache:
            self.bot.send_message_cache.remove(payload.id)
            return True

        return (
            payload.chatter.id == self.bot.bot_id
            or payload.source_broadcaster is not None
            or payload.text is None
            or payload.text.strip() == ""
            or payload.text.startswith("!")
            or ChatUtils.is_ignore_users(self.config, payload.chatter.name)
        )

    def _preprocess_message(self, payload: ChatMessageDTO) -> ChatMessageHandler:
        """Preprocess the message (emote/emoji handling, TTS parameters).

        Args:
            payload (ChatMessageDTO): The chat message payload.

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
            header="<- " + TimeUtils.get_time_in_hours_minutes() + " ",
        )

        if self.config.TTS.ORIGINAL_TEXT:
            tts_param: TTSParam = TTSUtils.create_tts_parameters(self.config, message)
            tts_param.content_lang = trans_info.src_lang
            queue_data: TTSParam = self.prepare_original_text(message=message, tts_param=tts_param)
            logger.debug("Dispatching `tts_message` event for original text")
            self.bot.safe_dispatch("tts_message", payload=queue_data)

    async def _process_translated_tts(self, message: ChatMessageHandler, trans_info: TranslationInfo) -> None:
        """Process translated text TTS.

        Prepare TTS for translated text if enabled.

        Args:
            message (ChatMessageHandler): The chat message handler instance.
            trans_info (TranslationInfo): The translation information instance.
        """
        if self.config.TTS.TRANSLATED_TEXT:
            queue_data: TTSParam = self.prepare_translated_text(message=message, trans_info=trans_info)
            logger.debug("Dispatching `tts_message` event for translated text")
            self.bot.safe_dispatch("tts_message", payload=queue_data)

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
            trans_info.translated_text, header="-> " + TimeUtils.get_time_in_hours_minutes() + " ", footer=footer
        )
        await self.send_chat_message(trans_info.translated_text, header="/me ", footer=footer)

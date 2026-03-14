from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast
from uuid import uuid4

from core.components.base import ComponentBase
from models.message_models import ChatMessageAuthorDTO, ChatMessageDTO, ChatMessageFragmentDTO
from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from core.components.chat_events import ChatEventsManager
    from core.stt.interface import STTResult


__all__: list[str] = ["STTServiceComponent"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

STT_CONSOLE_PREFIX: str = "[STT] "
STT_RESULT_IGNORE_WORDS_DIC_FILENAME: str = "stt_result_ignore_words.dic"


class STTServiceComponent(ComponentBase):
    """STT service component for Twitch bot.

    This component manages the initialization and teardown of the STT service, processes STT results,
    and forwards valid transcriptions to the chat events manager for further handling (e.g., TTS processing).
    """

    depends: ClassVar[list[str]] = ["ChatEventsManager", "TTSServiceComponent", "TranslationServiceComponent"]

    async def component_load(self) -> None:
        """Load the component and initialize STT services."""
        self._stt_result_ignore_words: list[str] = self._load_stt_result_ignore_words()

        try:
            self._confidence_threshold: float | None = None
            confidence_threshold: float | None = getattr(self.config.STT, "CONFIDENCE_THRESHOLD", None)
            if confidence_threshold is not None:
                try:
                    self._confidence_threshold = float(confidence_threshold)
                except (ValueError, TypeError) as err:
                    logger.warning("Invalid STT confidence threshold in configuration: %s", err)
                    self._confidence_threshold = None

            self._debug_mode: bool = getattr(self.config.STT, "DEBUG", False)
            stt_enabled: bool = self.config.STT.ENABLED
            if isinstance(stt_enabled, bool) and stt_enabled:
                await self.stt_manager.async_init(on_result=self._on_stt_result)
                logger.debug("'%s' component loaded", self.__class__.__name__)
                return
            logger.info(
                "STT service is disabled by configuration; '%s' component loaded without initializing STT",
                self.__class__.__name__,
            )
        except AttributeError as err:
            logger.warning("STT service initialization skipped due to missing configuration: %s", err)

    async def component_teardown(self) -> None:
        """Teardown the component and close STT services."""
        with suppress(AttributeError):
            await self.stt_manager.close()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    async def _on_stt_result(self, result: STTResult) -> None:
        """Handle STT result forwarding.

        self._debug_mode is intended for development and testing purposes,
        allowing STT results to be printed in the console instead of being forwarded to chat events.
        This can help with verifying the STT integration and tuning confidence thresholds.

        Args:
            result (STTResult): The result from the STT service, containing the transcribed text and confidence score.
        """
        # Although `result.text` is guaranteed to be of type `str`, we will check it just to be on the safe side.
        if not isinstance(result.text, str):
            logger.warning("Received STT result with non-string text: %s", result.text)
            return

        text: str = result.text.strip()
        if not text:
            return

        logger.debug("STT result: %s, confidence: %s", result.text[:20], result.confidence)

        if self._should_discard_by_confidence(result.confidence):
            return

        if self._contains_ignored_phrase(text):
            return

        if self._debug_mode:
            # For debugging
            self.print_console_message(text, header=STT_CONSOLE_PREFIX)
            self.print_console_message(str(result.confidence), header=STT_CONSOLE_PREFIX)
        else:
            await self.send_chat_message(text, sender=self.bot.owner_id)
            await self._forward_stt_result_to_chat_events(text=text)

    def _load_stt_result_ignore_words(self) -> list[str]:
        """Load STT misrecognition phrases from dictionary file."""
        dictionary_path: Path = self._resolve_stt_ignore_words_path()
        try:
            with dictionary_path.open(mode="r", encoding="utf-8") as handle:
                words: list[str] = [
                    line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")
                ]
        except OSError as err:
            logger.warning("Failed to load STT ignore dictionary: %s", err)
            return []

        logger.info("Loaded %d STT ignore phrase(s) from: %s", len(words), dictionary_path)
        return words

    def _resolve_stt_ignore_words_path(self) -> Path:
        """Resolve dictionary path used for filtering STT misrecognition phrases."""
        dic_base_path: str = "dic"
        with suppress(AttributeError):
            raw_path: str | Path = self.config.DICTIONARY.PATH
            if raw_path:
                dic_base_path = str(raw_path)

        return FileUtils.resolve_path(Path(dic_base_path) / STT_RESULT_IGNORE_WORDS_DIC_FILENAME)

    def _should_discard_by_confidence(self, confidence: float | None) -> bool:
        """Check whether STT result should be discarded by confidence score."""
        if confidence is None or self._confidence_threshold is None:
            return False

        if confidence < self._confidence_threshold:
            logger.warning(
                "STT result discarded by confidence threshold: confidence=%s threshold=%s",
                confidence,
                self._confidence_threshold,
            )
            return True
        return False

    def _contains_ignored_phrase(self, text: str) -> bool:
        """Check whether text contains any configured ignored phrases."""
        ignore_words: list[str] = getattr(self, "_stt_result_ignore_words", [])
        for ignore_word in ignore_words:
            if ignore_word in text:
                logger.warning(
                    "The STT result is incomprehensible and will be disregarded as a misrecognition: %s",
                    text,
                )
                return True
        return False

    async def _forward_stt_result_to_chat_events(self, *, text: str) -> None:
        forward_raw: bool | None = self.config.STT.FORWARD_TO_TTS
        if not isinstance(forward_raw, bool) or not forward_raw:
            return

        component: ComponentBase | None = self.get_attached_component("ChatEventsManager")
        if component is None:
            logger.warning("STT forwarding skipped because ChatEventsManager is unavailable")
            return

        dto: ChatMessageDTO = self._create_stt_chat_message_dto(text=text)
        await cast("ChatEventsManager", component).enqueue_external_message(dto)

    def _create_stt_chat_message_dto(self, *, text: str) -> ChatMessageDTO:
        owner_name: str = self.config.TWITCH.OWNER_NAME or self.config.BOT.BOT_NAME or "streamer"
        author = ChatMessageAuthorDTO(
            id=str(self.bot.owner_id),
            name=owner_name,
            display_name=owner_name,
            broadcaster=True,
        )
        return ChatMessageDTO(
            message_id=f"stt-{uuid4().hex}",
            content=text,
            text=text,
            fragments=[ChatMessageFragmentDTO(type="text", text=text)],
            author=author,
            timestamp=datetime.now(tz=UTC),
        )

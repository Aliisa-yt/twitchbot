import asyncio
from typing import TYPE_CHECKING

from core.tts.audio_playback_manager import AudioPlaybackManager
from core.tts.file_manager import TTSFileManager
from core.tts.parameter_manager import ParameterManager
from core.tts.synthesis_manager import SynthesisManager
from core.tts.text_preprocessor import TextPreprocessor
from core.tts.tts_interface import Interface
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from handlers.chat_message import ChatMessageHandler
    from models.config_models import Config
    from models.voice_models import TTSInfo, TTSParam, UserTypeInfo


__all__: list[str] = ["TTSManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TTSManager:
    """TTSManager is responsible for managing the Text-to-Speech (TTS) system.

    It handles the initialization, synthesis, playback, and management of TTS parameters.

    Attributes:
        config (Config): The configuration object containing TTS settings.
        parameter_manager (ParameterManager): Manager for TTS parameters and voice selection.
        text_preprocessor (TextPreprocessor): Preprocessor for TTS text content.
        synthesis_queue (ExcludableQueue[TTSParam]): Queue for TTS synthesis tasks.
        playback_queue (ExcludableQueue[TTSParam]): Queue for TTS playback tasks.
        deletion_queue (asyncio.Queue[Path]): Queue for audio file deletion tasks.
        task_terminate_event (asyncio.Event): Event to signal termination of background tasks.
        file_manager (TTSFileManager): Manager for TTS audio files.
        synthesis_manager (SynthesisManager): Manager for TTS synthesis tasks.
        playback_manager (AudioPlaybackManager): Manager for TTS audio playback.
        background_tasks (set[asyncio.Task[None]]): Set of active background tasks.

    Properties:
        voice_parameters (UserTypeInfo): Property to access the current voice parameters.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the TTSManager with the given configuration.

        Args:
            config (Config): The configuration object containing TTS settings.
        """
        logger.debug("Initializing TTSManager with config")
        self.config: Config = config
        self.parameter_manager: ParameterManager = ParameterManager(config)
        self.text_preprocessor: TextPreprocessor = TextPreprocessor(config)
        self._reset_runtime_managers()

        # Set to keep track of background tasks
        # This set is used to manage and monitor the background tasks that are running.
        self.background_tasks: set[asyncio.Task[None]] = set()

        logger.debug("Registered TTS engines: %s", list(Interface.get_registered().keys()))

    def _reset_runtime_managers(self) -> None:
        """Recreate runtime primitives and managers used by background tasks."""
        # `ExcludableQueue` is used to allow for safe concurrent access
        # and to prevent deadlocks when multiple tasks are trying to access the queue.
        self.synthesis_queue: ExcludableQueue[TTSParam] = ExcludableQueue()
        self.playback_queue: ExcludableQueue[TTSParam] = ExcludableQueue()
        self.deletion_queue: asyncio.Queue[Path] = asyncio.Queue()

        # This event is used to gracefully shut down the TTS processing tasks.
        # When set, it will allow the tasks to exit their loops and clean up resources.
        self.task_terminate_event: asyncio.Event = asyncio.Event()

        self.file_manager: TTSFileManager = TTSFileManager(self.deletion_queue)
        self.synthesis_manager: SynthesisManager = SynthesisManager(
            self.config, self.synthesis_queue, self.playback_queue
        )
        self.playback_manager: AudioPlaybackManager = AudioPlaybackManager(
            self.config, self.file_manager, self.playback_queue, self.task_terminate_event
        )

    async def initialize(self) -> None:
        """Initialize the TTSManager and start background tasks."""
        logger.info("TTSManager initialization started")

        # Check if the TTSManager is already initialized
        if self.background_tasks:
            logger.warning("TTSManager is already initialized")
            return

        # Recreate runtime primitives when reopening after close().
        if self.task_terminate_event.is_set():
            logger.debug("Recreating TTS runtime managers after previous shutdown")
            self._reset_runtime_managers()

        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(
                self.synthesis_manager.tts_processing_task(),
                name="TTS_processing_task",
            ),
            asyncio.create_task(self.playback_manager.playback_queue_processor(), name="play_voicefile_task"),
            asyncio.create_task(self.file_manager.audio_file_cleanup_task(), name="audio_file_cleanup_task"),
        ]
        for task in tasks:
            logger.debug("Creating task: '%s'", task.get_name())
            self.background_tasks.add(task)

    async def close(self) -> None:
        """Close the TTSManager and terminate background tasks."""
        logger.info("Terminating background tasks")

        # Set the task termination event to signal tasks to stop
        # This will allow the tasks to exit their loops and clean up resources.
        self.task_terminate_event.set()

        # The shutdown() method is executed to throw a QueueShutDown exception and terminate the endless loop task.
        self.playback_queue.shutdown()
        self.synthesis_queue.shutdown()
        self.deletion_queue.shutdown()

        logger.debug("Waiting for background tasks to finish")
        # Wait for all background tasks to finish or timeout after 2 seconds.
        finished_tasks: set[asyncio.Task[None]]
        remaining_tasks: set[asyncio.Task[None]]
        finished_tasks, remaining_tasks = await asyncio.wait(self.background_tasks, timeout=2.0)

        # Log the status of finished tasks
        # This will log whether each task was cancelled or completed successfully.
        for task in finished_tasks:
            if task.cancelled():
                logger.debug("Task '%s' was cancelled", task.get_name())
            else:
                logger.debug("Task '%s' completed successfully", task.get_name())
        if remaining_tasks:
            logger.warning("Some tasks are still pending: %s", [task.get_name() for task in remaining_tasks])
            for task in remaining_tasks:
                task.cancel()
            await asyncio.gather(*remaining_tasks, return_exceptions=True)

        # Clean up the background tasks
        # This will remove completed tasks from the set and cancel any pending tasks.
        logger.debug("Cleaning up background tasks")
        self.background_tasks.clear()

        logger.info("TTSManager closed successfully")

    def select_voice_usertype(self, message: ChatMessageHandler) -> None:
        self.parameter_manager.select_voice_usertype(message)

    def command_voiceparameters(self, message: ChatMessageHandler) -> None:
        self.parameter_manager.command_voiceparameters(message)

    def get_voice_param(self, lang: str | None = None, *, is_system: bool = False) -> TTSInfo:
        return self.parameter_manager.get_voice_param(lang, is_system=is_system)

    def prepare_tts_content(self, ttsparam: TTSParam) -> TTSParam | None:
        return self.text_preprocessor.process(ttsparam)

    async def enqueue_tts_synthesis(self, ttsparam: TTSParam) -> None:
        await self.synthesis_manager.enqueue_tts_synthesis(ttsparam)

    @property
    def voice_parameters(self) -> UserTypeInfo:
        return self.parameter_manager.voice_parameters

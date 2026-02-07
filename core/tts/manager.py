from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.tts.audio_playback_manager import AudioPlaybackManager
from core.tts.file_manager import TTSFileManager
from core.tts.interface import Interface
from core.tts.parameter_manager import ParameterManager
from core.tts.synthesis_manager import SynthesisManager
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from config.loader import Config
    from handlers.chat_message import ChatMessageHandler
    from models.voice_models import TTSInfo, TTSParam, UserTypeInfo


__all__: list[str] = ["TTSManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TTSManager:
    """TTSManager is responsible for managing the Text-to-Speech (TTS) system.

    It handles the initialization, synthesis, playback, and management of TTS parameters.
    """

    def __init__(self, config: Config) -> None:
        """Initialize the TTSManager with the given configuration.

        Args:
            config (Config): The configuration object containing TTS settings.
        """
        logger.debug("Initializing TTSManager with config")
        self.config: Config = config

        # Initialize queues for TTS synthesis and playback
        # `ExcludableQueue` is used to allow for safe concurrent access
        # and to prevent deadlocks when multiple tasks are trying to access the queue.
        self.synthesis_queue: ExcludableQueue[TTSParam] = ExcludableQueue()
        self.playback_queue: ExcludableQueue[TTSParam] = ExcludableQueue()
        self.deletion_queue: asyncio.Queue[Path] = asyncio.Queue()

        # Event to signal task termination
        # This event is used to gracefully shut down the TTS processing tasks.
        # When set, it will allow the tasks to exit their loops and clean up resources.
        self.task_terminate_event: asyncio.Event = asyncio.Event()

        # Initialize managers for TTS parameters, synthesis, and playback
        # These managers handle the respective functionalities of the TTS system.
        # `ParameterManager` manages voice parameters and user types.
        # `SynthesisManager` handles the TTS synthesis process.
        # `AudioPlaybackManager` manages the playback of synthesized audio.
        self.file_manager = TTSFileManager(self.deletion_queue)
        self.parameter_manager = ParameterManager(config)
        self.synthesis_manager = SynthesisManager(config, self.synthesis_queue, self.playback_queue)
        self.playback_manager = AudioPlaybackManager(
            config, self.file_manager, self.playback_queue, self.task_terminate_event
        )

        # Set to keep track of background tasks
        # This set is used to manage and monitor the background tasks that are running.
        self.background_tasks: set[asyncio.Task[None]] = set()

        # Register TTS classes and set up the interface
        Interface.play_callback = self.synthesis_manager.add_to_playback_queue
        # Interface.configure_audio_save_path(config.GENERAL.TMP_DIR)
        Interface.audio_save_directory = config.GENERAL.TMP_DIR
        logger.debug("Registered TTS classes: %s", Interface.get_registered())

    async def initialize(self) -> None:
        """Initialize the TTSManager and start background tasks."""
        logger.info("TTSManager initialization started")

        # Check if the TTSManager is already initialized
        if self.background_tasks:
            logger.warning("TTSManager is already initialized")
            return

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

        # Clean up the background tasks
        # This will remove completed tasks from the set and cancel any pending tasks.
        logger.debug("Cleaning up background tasks")
        self.background_tasks.clear()

        logger.info("TTSManager closed successfully")

    def select_voice_usertype(self, message: ChatMessageHandler) -> None:
        self.parameter_manager.select_voice_usertype(message)

    def command_voiceparameters(self, message: ChatMessageHandler) -> None:
        self.parameter_manager.command_voiceparameters(message)

    def get_voice_param(self, lang: str | None = None) -> TTSInfo:
        return self.parameter_manager.get_voice_param(lang)

    def prepare_tts_content(self, ttsparam: TTSParam) -> TTSParam | None:
        return self.synthesis_manager.prepare_tts_content(ttsparam)

    async def enqueue_tts_synthesis(self, ttsparam: TTSParam) -> None:
        await self.synthesis_manager.enqueue_tts_synthesis(ttsparam)

    @property
    def voice_parameters(self) -> UserTypeInfo:
        return self.parameter_manager.voice_parameters

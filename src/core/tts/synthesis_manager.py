"""Synthesis Manager for TTS (Text-to-Speech) engines.

This module manages the TTS synthesis process, including initializing TTS engines,
processing synthesis requests, and queuing audio files for playback.
"""

import asyncio
import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any

# The TTS engine is invoked in such a way that it is recognised as an unused import.
# To prevent this, the warning must be disabled.
from core.tts.engines import (  # noqa: F401
    BouyomiChanSocket,
    CevioAI,
    CevioCS7,
    CoeiroInk,
    CoeiroInk2,
    GoogleText2Speech,
    VoiceVox,
)
from core.tts.tts_interface import EngineContext, EngineHandler, Interface
from models.config_models import TTSEngine
from models.voice_models import TTSParam, UserTypeInfo
from utils.excludable_queue import ExcludableQueue
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

    from models.config_models import Config
    from utils.excludable_queue import ExcludableQueue


__all__: list[str] = ["SynthesisManager", "TTSEngineHandlerMap"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

# alias declaration
# TTSEngineHandlerMap is a dictionary type that stores TTSEngineHandler with engine name as a key
TTSEngineHandlerMap = dict[str, EngineHandler]


class SynthesisManager:
    """Manages the TTS synthesis task.

    It initialises the TTS engine and processes synthesis requests, registering
    them with the speech playback queue.
    The class is also responsible for converting text to speech using the various
    TTS engines and queuing the resulting speech files for playback.

    Attributes:
        config (Config): The configuration object containing TTS settings.
        voice_parameters (UserTypeInfo): User-specific voice parameters.
        synthesis_queue (ExcludableQueue[TTSParam]): Queue for TTS synthesis requests.
        playback_queue (ExcludableQueue[TTSParam]): Queue for audio playback requests.
    """

    def __init__(
        self,
        config: Config,
        synthesis_queue: ExcludableQueue[TTSParam],
        playback_queue: ExcludableQueue[TTSParam],
    ) -> None:
        """Initialize the SynthesisManager with configuration and queues.

        Args:
            config (Config):
                Configuration object containing TTS settings.
            synthesis_queue (ExcludableQueue[TTSParam]):
                Queue for TTS synthesis requests.
            playback_queue (ExcludableQueue[TTSParam]):
                Queue for audio playback requests.
        """
        self.config: Config = config
        self.voice_parameters: UserTypeInfo = config.VOICE_PARAMETERS
        self.synthesis_queue: ExcludableQueue[TTSParam] = synthesis_queue
        self.playback_queue: ExcludableQueue[TTSParam] = playback_queue

    async def _create_handler_map(self) -> TTSEngineHandlerMap:
        """Create a map of TTS engine handlers.

        This method initializes the TTS engines based on the configuration,
        registers them, and returns a dictionary mapping engine names to their handlers.

        Returns:
            TTSEngineHandlerMap: A dictionary mapping TTS engine names to their respective handlers.
        """
        logger.debug("Creating TTS engine handler map")
        tts_engine_handler_map: TTSEngineHandlerMap = {}

        for engine_name in sorted(self.voice_parameters.get_tts_engine_list()):
            try:
                engine_instance: Interface = Interface.get_engine(engine_name)()
            except KeyError:
                logger.error("TTS engine '%s' is not registered", engine_name)
                continue

            # Get the TTS engine configuration from the config object.
            # If the configuration is not found, use a default TTSEngine instance.
            # This allows for flexibility in engine configuration.
            tts_engine: TTSEngine = getattr(self.config, engine_name.upper(), TTSEngine())

            tmp_dir = self.config.GENERAL.TMP_DIR
            if tmp_dir is None:
                logger.error("TMP_DIR is not configured; failed to initialize TTS engine '%s'", engine_name)
                continue

            context = EngineContext(
                audio_save_directory=tmp_dir if isinstance(tmp_dir, Path) else Path(tmp_dir),
                play_callback=self.add_to_playback_queue,
            )

            if not engine_instance.initialize_engine(tts_engine, context):
                # If the engine initialization fails, log the error and continue to the next engine.
                logger.error("Failed to initialize TTS engine '%s'", engine_name)
                continue

            # Register the engine instance in the handler map.
            logger.info("TTS engine '%s' initialized successfully", engine_name)

            tts_engine_handler_map[engine_name] = engine_instance.handler

        return tts_engine_handler_map

    async def _dispatch_tts_tasks(
        self,
        handler_map: TTSEngineHandlerMap,
        method_name: str,
        *args: UserTypeInfo | TTSParam | None,
        **kwargs: dict[str, Any],
    ) -> None:
        """Dispatch a method call to all TTS engine handlers.

        Calls ``method_name`` on every handler in ``handler_map``.
        - If a handler doesn't implement the method, it is skipped.
        - Scheduling errors are logged per-engine.
        - Execution exceptions are gathered and logged per-engine.
        This method is intentionally standalone to improve testability and readability.
        """
        logger.debug("Dispatching TTS engine method '%s' with args: %s, kwargs: %s", method_name, args, kwargs)
        tasks: list[Awaitable[None]] = []
        engine_names: list[str] = []

        for engine_name, handler in handler_map.items():
            method: Callable[[None | UserTypeInfo | TTSParam], Awaitable[None]] | None = getattr(
                handler, method_name, None
            )
            if method is None:
                logger.debug("TTS engine '%s' does not implement method '%s', skipping", engine_name, method_name)
                continue
            if not callable(method):
                logger.debug("Attribute '%s' of TTS engine '%s' is not callable, skipping", method_name, engine_name)
                continue

            try:
                coro: Awaitable[None] = method(*args, **kwargs)
            except Exception as err:  # noqa: BLE001
                logger.error("Failed to schedule method '%s' on engine '%s': %s", method_name, engine_name, err)
                continue

            if not inspect.isawaitable(coro):
                logger.error(
                    "Method '%s' of TTS engine '%s' did not return an awaitable, skipping", method_name, engine_name
                )
                continue

            tasks.append(coro)
            engine_names.append(engine_name)

        if not tasks:
            return

        results: list[None | BaseException] = await asyncio.gather(*tasks, return_exceptions=True)
        for engine_name, result in zip(engine_names, results, strict=False):
            if isinstance(result, Exception):
                logger.error("Exception in TTS engine '%s' during method '%s': %s", engine_name, method_name, result)

    async def _handle_tts_param(self, tts_param: TTSParam, handler_map: TTSEngineHandlerMap) -> None:
        """Handle a single TTSParam item.

        Validates the item and dispatches synthesis to the selected engine.
        Designed to keep the main processing loop concise and testable.
        """
        if not isinstance(tts_param, TTSParam):
            logger.debug("Received non-TTSParam item: %r", tts_param)
            return

        engine_name: str | None = tts_param.tts_info.engine
        if engine_name and engine_name in handler_map:
            logger.info("Using TTS engine: '%s'", engine_name)
            try:
                await handler_map[engine_name].synthesis(tts_param)
            except Exception as err:  # noqa: BLE001
                logger.error("Exception during synthesis in TTS engine '%s': %s", engine_name, err)
        else:
            logger.warning("TTS engine name not found or invalid: '%s'", engine_name)

    async def tts_processing_task(self) -> None:
        """Main task for processing TTS synthesis requests.

        This method initializes the TTS engines, waits for them to be ready,
        and processes synthesis requests from the queue.
        It handles the conversion of text to speech, manages the playback queue,
        and ensures that the TTS engines are properly initialized and terminated.
        """

        async def dispatch(method_name: str, *args: UserTypeInfo | TTSParam | None, **kwargs: dict[str, Any]) -> None:
            """Helper function to dispatch methods to all TTS engines."""
            await self._dispatch_tts_tasks(tts_engine_handler_map, method_name, *args, **kwargs)

        tts_engine_handler_map: TTSEngineHandlerMap = await self._create_handler_map()

        # Start TTS applications
        await dispatch("execute")
        await dispatch("ainit", self.voice_parameters)

        try:
            while True:
                try:
                    tts_param: TTSParam = await self.synthesis_queue.get()
                except asyncio.QueueShutDown:
                    logger.info("TTS processing task terminated")
                    break

                try:
                    await self._handle_tts_param(tts_param, tts_engine_handler_map)
                finally:
                    try:
                        # Ensure task_done() is called after processing (or on error).
                        self.synthesis_queue.task_done()
                    except ValueError as err:
                        # This can happen if task_done() is called more times than there were items.
                        logger.debug("synthesis_queue.task_done() raised ValueError: %s", err)
                    except Exception as err:  # noqa: BLE001
                        # task_done() should only raise a ValueError, but we catch all exceptions just in case.
                        logger.debug("synthesis_queue.task_done() raised an exception: %s", err)
        except asyncio.QueueShutDown:
            logger.info("TTS processing task terminated (outer handler)")

        # Terminate TTS engines
        await dispatch("close")
        await dispatch("termination")

    async def enqueue_tts_synthesis(self, tts_param: TTSParam) -> None:
        """Enqueue the TTS parameters for synthesis.

        Args:
            tts_param (TTSParam): The TTS parameters to be processed and queued for synthesis.
        """
        logger.debug("Enqueuing TTS parameters for synthesis: '%s'", tts_param)
        await self.synthesis_queue.put(tts_param)

    async def add_to_playback_queue(self, tts_param: TTSParam) -> None:
        """Add the TTS parameters to the playback queue.

        Args:
            tts_param (TTSParam): The TTS parameters to be queued for playback.
        """
        logger.debug("Adding TTS parameters to playback queue: '%s'", tts_param)
        await self.playback_queue.put(tts_param)

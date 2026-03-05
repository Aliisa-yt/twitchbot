"""Audio playback manager using sounddevice and soundfile.

This module provides the AudioPlaybackManager class, which handles
the playback of audio files in a non-blocking manner using asyncio.
It uses sounddevice for audio output and soundfile for reading audio files.
"""

from __future__ import annotations

import asyncio
import contextlib
from enum import IntEnum
from typing import TYPE_CHECKING, Final

import sounddevice
import soundfile

from models.voice_models import TTSParam
from utils.file_utils import FileUtils, FileUtilsError
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path
    from typing import Any

    from numpy.typing import NDArray

    from config.loader import Config
    from core.tts.file_manager import TTSFileManager
    from utils.excludable_queue import ExcludableQueue

# soundfile -> sounddevice conversion tables
# PCM_S8, PCM_U8, PCM_24 are commented out because they have not been confirmed to play
FORMAT_CONV: Final[dict[str, str]] = {
    # "PCM_S8": "int16",
    "PCM_16": "int16",
    # "PCM_24": "int32",
    "PCM_32": "int32",
    # "PCM_U8": "int16",
    "FLOAT": "float32",
}


class _CallbackAction(IntEnum):
    """Represents stream callback actions."""

    CONTINUE = 0
    STOP = 1
    ABORT = 2


__all__: list[str] = ["AudioPlaybackManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


def _stream_callback_logic(
    outdata: NDArray[Any],
    frames: int,
    /,
    sf: soundfile.SoundFile,
    dtype: str,
    loop: asyncio.AbstractEventLoop,
    terminate_event: asyncio.Event,
    cancel_playback_event: asyncio.Event,
) -> _CallbackAction:
    """Callback function for the sounddevice stream.

    This function is called by sounddevice to fill the audio buffer with data.

    Args:
        outdata: Output buffer provided by sounddevice.
        frames: Number of frames to read.
        sf (soundfile.SoundFile): SoundFile object for reading audio data.
        dtype (str): Data type of the audio data.
        loop (asyncio.AbstractEventLoop): Event loop for asyncio.
        terminate_event (asyncio.Event): Event to signal when playback is finished.
        cancel_playback_event (asyncio.Event): Event to signal when playback is cancelled.

    Returns:
        _CallbackAction: Callback action for the stream.
    """
    try:
        if terminate_event.is_set():
            outdata.fill(0)
            loop.call_soon_threadsafe(cancel_playback_event.set)
            return _CallbackAction.ABORT

        data = sf.read(frames=frames, dtype=dtype, always_2d=True)
        # Considered complete when there is no more data to playback
        frames_read = data.shape[0]
        outdata.fill(0)
        if frames_read > 0:
            outdata[:frames_read] = data

        if frames_read < frames:
            loop.call_soon_threadsafe(cancel_playback_event.set)
            return _CallbackAction.STOP

    except soundfile.SoundFileRuntimeError:
        outdata.fill(0)
        loop.call_soon_threadsafe(cancel_playback_event.set)
        return _CallbackAction.ABORT

    except RuntimeError as err:
        # Event loop already closed when cancel_playback_event is set
        outdata.fill(0)
        logger.critical("Runtime error in audio callback: %s", err)
        return _CallbackAction.ABORT

    return _CallbackAction.CONTINUE


class AudioPlaybackManager:
    """Audio playback manager using sounddevice and soundfile.

    This class handles the playback of audio files in a non-blocking manner using asyncio.
    It uses sounddevice for audio output and soundfile for reading audio files.

    Supported WAV formats: PCM_16, PCM_32, FLOAT
    """

    def __init__(
        self,
        config: Config,
        file_manager: TTSFileManager,
        playback_queue: ExcludableQueue[TTSParam],
        task_terminate_event: asyncio.Event,
    ) -> None:
        """Initializes the AudioPlaybackManager.

        Args:
            config (Config): Configuration object.
            file_manager (TTSFileManager): File manager for handling audio files.
            playback_queue (ExcludableQueue[TTSParam]): Queue for TTS parameters.
            task_terminate_event (asyncio.Event): Event to terminate the playback task.
        """
        self.config: Config = config
        self.file_manager: TTSFileManager = file_manager
        self.playback_queue: ExcludableQueue[TTSParam] = playback_queue
        # An event that terminates a task. Must never be cleared.
        self.task_terminate_event: asyncio.Event = task_terminate_event
        # An event that interrupts playback. Must be cleared before playback.
        self.cancel_playback_event: asyncio.Event = asyncio.Event()
        self.play_task: asyncio.Task[None] | None = None
        self.stream: sounddevice.OutputStream | None = None

    async def playback_queue_processor(self) -> None:
        """Asynchronous task to process and play queued audio files.

        Continuously fetches audio files from the queue and plays them unless a termination
        event is set. Supports optional timeout based on configuration.
        """
        try:
            while True:
                tts_param: TTSParam = await self.playback_queue.get()
                try:
                    if not isinstance(tts_param, TTSParam):
                        logger.warning("Invalid TTSParam in playback queue: %s", tts_param)
                        continue

                    file_path: Path | None = tts_param.filepath
                    if file_path is None:
                        continue
                    try:
                        FileUtils.validate_file_path(file_path, suffix=".wav")
                    except FileUtilsError as err:
                        logger.warning("Invalid file path: %s", err)
                        continue

                    logger.debug("Audio file: '%s'", file_path)
                    self.play_task = asyncio.create_task(
                        self._play_sounddevice(file_path, self.task_terminate_event),
                        name=f"AudioPlayback-{file_path.stem}",
                    )

                    _timelimit: float | None = self._get_timelimit()

                    async with asyncio.timeout(_timelimit):
                        logger.debug("Playback start")
                        await self.play_task
                except TimeoutError as err:
                    logger.info("Playback timeout reached: %s", err)
                    await self.cancel_playback()
                except asyncio.CancelledError as err:
                    logger.info("Playback task was cancelled: %s", err)
                else:
                    logger.info("Playback completed")
                finally:
                    self.play_task = None
                    self.playback_queue.task_done()
                    logger.debug("Waiting for playback task to finish")
                    # Pause playback as sound can be connected if the next playback starts
                    # immediately after the end of playback.
                    await asyncio.sleep(0.5)
        except asyncio.QueueShutDown:
            logger.debug("Playback queue closed")
            self.release_audio_resources()

        logger.info("Audio playback task finished")

    def _get_timelimit(self) -> float | None:
        """Gets the playback time limit from configuration.

        Returns:
            float | None: Time limit in seconds if configured and valid, None otherwise.
        """
        try:
            if float(self.config.TTS.LIMIT_TIME) > 0.0:
                return float(self.config.TTS.LIMIT_TIME)
        except (ValueError, TypeError) as err:
            logger.warning(
                "Invalid TTS_READOUT_LIMIT_TIME value: '%s'",
                self.config.TTS.LIMIT_TIME,
            )
            logger.debug(err)
        return None

    async def cancel_playback(self) -> None:
        """Cancels the currently playing WAV file.

        Called when a TimeoutError occurs during playback or manually from external logic.
        """
        if not self.cancel_playback_event.is_set():
            try:
                self.cancel_playback_event.set()
            except RuntimeError as err:
                logger.error("Error setting cancel_playback_event: %s", err)
        if self.play_task and not self.play_task.done():
            self.play_task.cancel()
            try:
                await self.play_task
            except asyncio.CancelledError as err:
                logger.info("Cancelled during playback: %s", err)
            except RuntimeError as err:
                logger.error("Error during playback cancellation: %s", err)

    def _create_stream_callback(
        self,
        sf: soundfile.SoundFile,
        dtype: str,
        loop: asyncio.AbstractEventLoop,
        task_terminate_event: asyncio.Event,
    ):
        """Creates a stream callback function for sounddevice output stream."""

        def callback_fn(outdata: NDArray[Any], frames: int, time_info, status) -> None:
            _ = time_info, status
            action = _stream_callback_logic(
                outdata,
                frames,
                sf=sf,
                dtype=dtype,
                loop=loop,
                terminate_event=task_terminate_event,
                cancel_playback_event=self.cancel_playback_event,
            )
            if action == _CallbackAction.ABORT:
                raise sounddevice.CallbackAbort
            if action == _CallbackAction.STOP:
                raise sounddevice.CallbackStop

        return callback_fn

    def _open_output_stream(
        self,
        sf: soundfile.SoundFile,
        dtype: str,
        frame_buffer_size: int,
        callback_fn,
    ) -> bool:
        """Opens and validates the sounddevice output stream."""
        try:
            self.stream = sounddevice.OutputStream(
                samplerate=sf.samplerate,
                channels=sf.channels,
                dtype=dtype,
                blocksize=frame_buffer_size,
                callback=callback_fn,
            )
        except Exception as err:  # noqa: BLE001
            logger.error("Error opening sounddevice stream: %s", err)
            return False

        if self.stream is None:
            logger.error("Failed to create sounddevice stream")
            return False

        return True

    async def _play_sounddevice(self, file_path: Path, task_terminate_event: asyncio.Event) -> None:
        """Plays a WAV file using sounddevice.

        Args:
            file_path (Path): Path to the audio file.
            task_terminate_event (asyncio.Event): Event to signal task termination from external sources.
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        # If the event is not initialised, playback will not start after the cancellation process.
        self.cancel_playback_event.clear()

        try:
            with soundfile.SoundFile(file_path) as sf:
                try:
                    _dtype: str = FORMAT_CONV[sf.subtype]
                except KeyError:
                    logger.error("Unsupported wav file format: '%s'", sf.subtype)
                    return

                callback_fn = self._create_stream_callback(sf, _dtype, loop, task_terminate_event)

                # The buffer size is set to 0.2 seconds of audio data.
                # The value set here is the number of words,
                # so the number of bytes actually read is the value taking into account the channel and bit width.
                frame_buffer_size: int = max(2048, int(sf.samplerate * 0.2))
                logger.debug(
                    "Audio properties - Channels: %s, Sampling rate: %s, Buffer size: %s",
                    sf.channels,
                    sf.samplerate,
                    frame_buffer_size,
                )
                if not self._open_output_stream(sf, _dtype, frame_buffer_size, callback_fn):
                    return
                stream: sounddevice.OutputStream | None = self.stream
                if stream is None:
                    return

                stream.start()
                await self.cancel_playback_event.wait()
                stream.stop()
                stream.close()
                self.stream = None
        except (soundfile.LibsndfileError, soundfile.SoundFileRuntimeError) as err:
            logger.error("Soundfile error: %s", err)
        except sounddevice.PortAudioError as err:
            logger.error("Sounddevice error: %s", err)
        except (OSError, AttributeError, TypeError, ValueError) as err:
            logger.error("System error: %s", err)
        except asyncio.CancelledError as err:
            logger.info("Playback task was cancelled: %s", err)
        finally:
            # file for asynchronous deletion (non-blocking)
            self.file_manager.enqueue_file_deletion(file_path)
            # Ensure stream is closed if an error occured earlier
            if self.stream is not None:
                with contextlib.suppress(Exception):
                    self.stream.stop()
                with contextlib.suppress(Exception):
                    self.stream.close()
                self.stream = None

    @property
    def is_playing(self) -> bool:
        """Checks if audio is currently playing.

        Returns:
            bool: True if audio is playing, False otherwise.
        """
        if self.stream is None:
            return False
        return bool(self.stream.active)

    def release_audio_resources(self) -> None:
        """Releases the audio stream resources."""
        if self.stream is not None:
            with contextlib.suppress(Exception):
                self.stream.stop()
            with contextlib.suppress(Exception):
                self.stream.close()
            self.stream = None
            logger.info("Audio stream resources released")

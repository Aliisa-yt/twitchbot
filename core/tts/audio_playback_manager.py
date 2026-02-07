"""Audio playback manager using PyAudio and soundfile.

This module provides the AudioPlaybackManager class, which handles
the playback of audio files in a non-blocking manner using asyncio.
It uses PyAudio for audio output and soundfile for reading audio files.
"""

from __future__ import annotations

import asyncio
import contextlib
from functools import partial
from typing import TYPE_CHECKING, Final

import pyaudio
import soundfile

from models.voice_models import TTSParam
from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path

    from config.loader import Config
    from core.tts.file_manager import TTSFileManager
    from utils.excludable_queue import ExcludableQueue

# soundfile -> pyaudio conversion tables
# PCM_S8, PCM_U8, PCM_24 are commented out because they have not been confirmed to play
FORMAT_CONV: Final[dict[str, tuple[int, str]]] = {
    # "PCM_S8": (pyaudio.paInt8, "int16"),
    "PCM_16": (pyaudio.paInt16, "int16"),
    # "PCM_24": (pyaudio.paInt24, "int32"),
    "PCM_32": (pyaudio.paInt32, "int32"),
    # "PCM_U8": (pyaudio.paUInt8, "int16"),
    "FLOAT": (pyaudio.paFloat32, "float32"),
}

__all__: list[str] = ["AudioPlaybackManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


def _stream_callback_logic(
    in_data,
    frame_count,
    time_info,
    status,
    /,
    sf: soundfile.SoundFile,
    dtype: str,
    loop: asyncio.AbstractEventLoop,
    terminate_event: asyncio.Event,
    cancel_playback_event: asyncio.Event,
) -> tuple[bytes | None, int]:
    """Callback function for the PyAudio stream.

    This function is called by PyAudio to fill the audio buffer with data.

    Args:
        _in_data: Input data (not used).
        frame_count: Number of frames to read.
        _time_info: Time information (not used).
        _status: Status information (not used).
        sf (soundfile.SoundFile): SoundFile object for reading audio data.
        dtype (str): Data type of the audio data.
        loop (asyncio.AbstractEventLoop): Event loop for asyncio.
        terminate_event (asyncio.Event): Event to signal when playback is finished.
        cancel_playback_event (asyncio.Event): Event to signal when playback is cancelled.

    Returns:
        tuple[bytes | None, int]: Audio data and playback status.
    """
    # The first four are position-only arguments.
    # The order of definitions cannot be changed.
    _ = in_data
    _ = time_info
    _ = status
    try:
        if terminate_event.is_set():
            loop.call_soon_threadsafe(cancel_playback_event.set)
            return (None, pyaudio.paAbort)

        data = sf.read(frames=frame_count, dtype=dtype)
        # Considered complete when there is no more data to playback
        frames_read = data.shape[0]
        if frames_read < frame_count:
            loop.call_soon_threadsafe(cancel_playback_event.set)
            return (data.tobytes(), pyaudio.paComplete)

    except soundfile.SoundFileRuntimeError:
        loop.call_soon_threadsafe(cancel_playback_event.set)
        return (None, pyaudio.paAbort)

    except RuntimeError as err:
        # Event loop already closed when cancel_playback_event is set
        logger.critical("Runtime error in audio callback: %s", err)
        return (None, pyaudio.paAbort)

    return (data.tobytes(), pyaudio.paContinue)


class AudioPlaybackManager:
    """Audio playback manager using PyAudio and soundfile.

    This class handles the playback of audio files in a non-blocking manner using asyncio.
    It uses PyAudio for audio output and soundfile for reading audio files.

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
        self._pyaudio: pyaudio.PyAudio | None = pyaudio.PyAudio()
        self.stream: pyaudio.Stream | None = None

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
                    if file_path is None or not FileUtils.is_valid_file_path(file_path, suffix=".wav"):
                        continue

                    logger.debug("Audio file: '%s'", file_path)
                    self.play_task = asyncio.create_task(self._play_pyaudio(file_path, self.task_terminate_event))

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
            self.release_pyaudio()

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

    async def _play_pyaudio(self, file_path: Path, task_terminate_event: asyncio.Event) -> None:
        """Plays a WAV file using PyAudio.

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
                    (_format, _dtype) = FORMAT_CONV[sf.subtype]
                except KeyError:
                    logger.error("Unsupported wav file format: '%s'", sf.subtype)
                    return

                callback_fn: partial[tuple[bytes | None, int]] = partial(
                    _stream_callback_logic,
                    sf=sf,
                    dtype=_dtype,
                    loop=loop,
                    terminate_event=task_terminate_event,
                    cancel_playback_event=self.cancel_playback_event,
                )

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
                try:
                    self.stream = self.pyaudio.open(
                        format=_format,
                        channels=sf.channels,
                        rate=sf.samplerate,
                        output=True,
                        frames_per_buffer=frame_buffer_size,
                        stream_callback=callback_fn,
                    )
                except Exception as err:  # noqa: BLE001
                    logger.error("Error opening PyAudio stream: %s", err)
                    return
                # It is unclear whether the stream can become 'None' without an exception occurring.
                if self.stream is None:
                    logger.error("Failed to create PyAudio stream")
                    return

                self.stream.start_stream()
                await self.cancel_playback_event.wait()
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
        except (soundfile.LibsndfileError, soundfile.SoundFileRuntimeError) as err:
            logger.error("Soundfile error: %s", err)
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
                    self.stream.stop_stream()
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
        return self.stream.is_active()

    @property
    def pyaudio(self) -> pyaudio.PyAudio:
        """Gets the PyAudio instance, recreating it if necessary.

        Returns:
            pyaudio.PyAudio: The PyAudio instance.
        """
        if self._pyaudio is None:
            self._pyaudio = pyaudio.PyAudio()
            logger.info("PyAudio instance recreated")
        return self._pyaudio

    def release_pyaudio(self) -> None:
        """Releases the PyAudio resources."""
        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None
            logger.info("PyAudio resources released")

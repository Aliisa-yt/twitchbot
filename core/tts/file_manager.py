"""TTS File Manager Module

Handles asynchronous deletion of audio files to prevent blocking TTS operations.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from utils.file_utils import FileUtils
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path


__all__: list[str] = ["TTSFileManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TTSFileManager:
    """TTSFileManager handles asynchronous deletion of audio files.

    It uses a background worker task to delete files from a queue,
    ensuring that file deletion does not block other TTS operations.
    """

    def __init__(self, deletion_queue: asyncio.Queue[Path]) -> None:
        """Initialize the TTSFileManager with a deletion queue.

        Args:
            deletion_queue (asyncio.Queue[Path]): Queue for file paths to be deleted.
        """
        logger.debug("Initializing TTSFileManager")
        self.deletion_queue: asyncio.Queue[Path] = deletion_queue

    def enqueue_file_deletion(self, file_path: Path) -> None:
        """Enqueue a file for deletion.

        Args:
            file_path (Path): Path to the file to be deleted.
        """
        logger.debug("Enqueuing file for deletion: '%s'", file_path)
        try:
            self.deletion_queue.put_nowait(file_path)
        except asyncio.QueueFull:
            logger.warning("Deletion queue is full. Failed to enqueue file: '%s'", file_path)
        except asyncio.QueueShutDown:
            logger.info("Deletion queue is shut down. Cannot enqueue file: '%s'", file_path)

    async def audio_file_cleanup_task(self) -> None:
        """Background worker task to delete audio files asynchronously.

        This task runs independently from playback and processes files from the deletion queue.
        It retries deletion on PermissionError to handle Windows file locking issues.
        """
        logger.debug("Starting audio file cleanup task")
        try:
            while True:
                file_path: Path = await self.deletion_queue.get()
                await self._delete_file_with_retry(file_path)
                self.deletion_queue.task_done()
        except asyncio.QueueShutDown:
            logger.info("Audio file cleanup task received shutdown signal")
            while not self.deletion_queue.empty():
                try:
                    file_path = self.deletion_queue.get_nowait()
                    await self._delete_file_with_retry(file_path)
                    self.deletion_queue.task_done()
                except asyncio.QueueEmpty:
                    break
        logger.info("Audio file cleanup task finished")

    async def _delete_file_with_retry(
        self,
        file_path: Path,
        max_retries: int = 3,
        delay: float = 0.5,
    ) -> None:
        """Delete a file with retry logic for handling PermissionError.

        Args:
            file_path (Path): Path to the file to delete.
            max_retries (int): Maximum number of retry attempts.
            delay (float): Delay in seconds between retries.
        """
        for attempt in range(max_retries):
            try:
                if not FileUtils.check_file_availability(file_path):
                    break
                file_path.unlink(missing_ok=True)  # noqa: ASYNC240

            except PermissionError as err:
                if attempt < max_retries - 1:
                    logger.debug(
                        "PermissionError deleting '%s', retrying... (%d/%d)",
                        file_path,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Failed to delete '%s' after %d attempts: %s",
                        file_path,
                        max_retries,
                        err,
                    )
            except Exception as err:  # noqa: BLE001
                logger.error("Unexpected error deleting '%s': %s", file_path, err)
                return
            else:
                logger.debug("Deleted audio file: '%s'", file_path)
                return

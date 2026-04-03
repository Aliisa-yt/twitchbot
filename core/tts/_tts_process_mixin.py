"""Process lifecycle management mixin for TTS engines.

Provides _execute, _kill, _wait_for_exit, and _cleanup for managing an external subprocess.
Intended to be used only in combination with Interface.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from abc import abstractmethod
from typing import TYPE_CHECKING, Final

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from pathlib import Path


__all__: list[str] = ["ProcessMixin"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

WINDOWS: Final[bool] = os.name == "nt"
KILL_TIMEOUT: Final[float] = 3.0  # Timeout in seconds for process termination


class ProcessMixin:
    """Mixin that manages the lifecycle of an external TTS engine process.

    Must not be used standalone; combine with Interface.
    Assumes the concrete class (Interface) provides the following:

    Attributes:
        process (asyncio.subprocess.Process | None): The subprocess object for the TTS engine process,
            or None if not running.

    Properties:
        linkedstartup (bool): Whether linked startup is enabled. Must be implemented by Interface.
        exec_path (Path | None): The path to the executable to launch. Must be implemented by Interface.
    """

    # Type annotation only; the actual value is provided by the concrete class (Interface)
    process: asyncio.subprocess.Process | None

    @property
    @abstractmethod
    def linkedstartup(self) -> bool:
        """Return whether linked startup is enabled. Implemented by Interface."""
        raise NotImplementedError

    @property
    @abstractmethod
    def exec_path(self) -> Path | None:
        """Return the path to the executable to launch. Implemented by Interface."""
        raise NotImplementedError

    async def _execute(self) -> None:
        """Launch the external process asynchronously if linked startup is enabled.

        When linkedstartup is True and exec_path is set, starts the specified executable
        and assigns the resulting subprocess object to self.process.
        """
        if self.linkedstartup and self.exec_path is not None:
            try:
                self.process = await asyncio.create_subprocess_exec(
                    str(self.exec_path), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                logger.debug("Execution '%s' started successfully.", self.exec_path)
            except FileNotFoundError:
                logger.error("Executable file not found: '%s'", self.exec_path)
            except OSError as err:
                logger.error("Failed to execute file '%s': %s", self.exec_path, err)

    async def _kill(self) -> None:
        """Asynchronously terminate the process started by linked startup.

        Attempts a graceful termination first; falls back to a forceful kill if the
        process does not exit within the timeout. Does nothing if no process is running.
        """
        if not (self.linkedstartup and self.process):
            return

        # Attempt a graceful termination
        with contextlib.suppress(ProcessLookupError):
            try:
                logger.info("Terminating process %s", self.process.pid)
                self.process.terminate()
            except PermissionError as exc:
                logger.error("Failed to terminate process %s: %s", self.process.pid, exc)
                return

        if await self._wait_for_exit(KILL_TIMEOUT):
            self._cleanup()
            return

        if WINDOWS:
            # On Windows, terminate() and kill() behave identically, so a two-stage shutdown is unnecessary.
            logger.error("Timeout while terminating process %s on Windows", self.process.pid)
            self._cleanup()
            return

        # Fall back to force kill after timeout
        with contextlib.suppress(ProcessLookupError):
            try:
                logger.warning("Termination timed out; force killing process %s", self.process.pid)
                self.process.kill()
            except PermissionError as exc:
                logger.error("Failed to force kill process %s: %s", self.process.pid, exc)
                self._cleanup()
                return

        if not await self._wait_for_exit(KILL_TIMEOUT):
            logger.error("Force kill also timed out for process %s", self.process.pid)

        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up after the process has exited."""
        self.process = None

    async def _wait_for_exit(self, wait_timeout: float) -> bool:
        """Wait for the process to exit.

        Args:
            wait_timeout (float): Maximum time to wait in seconds.

        Returns:
            bool: True if the process exited within the timeout, False otherwise.
        """
        if not self.process:
            logger.debug("No process to wait for exit")
            return True

        try:
            await asyncio.wait_for(self.process.wait(), timeout=wait_timeout)
        except TimeoutError:
            return False
        else:
            return True

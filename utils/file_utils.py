from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

__all__: list[str] = ["FileUtils"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class FileUtils:
    """File system utility functions for safe file operations.

    Provides methods for file deletion with safety checks and path resolution.
    """

    @staticmethod
    def remove(file_path: Path) -> None:
        """Remove a file from the filesystem with safety checks.

        Checks for various conditions before attempting file removal:
        - Existence of the file
        - Whether it's a directory
        - Whether it's a symbolic link
        - Whether it's in use (hard link count > 1)

        Logs appropriate messages for each condition.

        Args:
            file_path (Path): The path to the file to remove.
        """
        if not file_path.exists():
            logger.debug("File does not exist: %s", file_path)
            return
        if file_path.is_dir():
            logger.warning("File is a directory: %s", file_path)
            return
        if file_path.is_symlink():
            logger.warning("File is a symlink: %s", file_path)
            return
        if file_path.stat().st_nlink > 1:
            logger.warning("File is in use: %s", file_path)
            return
        # Attempt to remove the file
        try:
            file_path.unlink(missing_ok=True)
            logger.debug("File deleted: %s", file_path)
        except PermissionError as err:
            logger.warning("Error deleting file '%s': %s", file_path, err)

    @staticmethod
    def resolve_path(path: str | Path, *, strict: bool = False) -> Path:
        """Convert a user-input path to an absolute path safely.

        Expands environment variables (e.g., $HOME, %APPDATA%), expands ~ to the home directory,
        and resolves relative paths based on the current working directory.
        Optionally resolves symbolic links with `.resolve()`.

        Args:
            path (str | Path): The input path (e.g., "~/logs/$APP_ENV/app.log").
            strict (bool): Whether to raise an exception if the path does not exist. Defaults to False.

        Returns:
            Path: The converted absolute `Path` object.
        """
        path_str = str(path)
        expanded: str = os.path.expandvars(path_str)
        user_expanded: Path = Path(expanded).expanduser()

        resolved_path: Path
        if user_expanded.is_absolute():
            resolved_path = user_expanded.resolve(strict=strict)
        else:
            resolved_path = (Path.cwd() / user_expanded).resolve(strict=strict)
        logger.debug("Original path: %s, Resolved absolute path: %s", path_str, resolved_path)
        return resolved_path

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__: list[str] = [
    "FileInUseError",
    "FileMissingError",
    "FilePermissionError",
    "FileUtils",
    "FileUtilsError",
    "InvalidFileTypeError",
    "UnsupportedFileFormatError",
]


class FileUtils:
    """Utility class for file operations with safety checks.

    Provides methods to safely remove files, resolve paths, and validate file types.

    Methods:
    - check_file_status: Check the status of a file before performing operations.
    - remove: Remove a file with safety checks.
    - resource_path: Get the absolute path to a resource file, compatible with PyInstaller.
    - resolve_path: Convert a user-input path to an absolute path safely.
    - validate_file_path: Validate that a file exists and has an allowed suffix.

    Attributes:
        RESOURCE_BASE (Path):
            Base path for resource files, set to _MEIPASS for PyInstaller or current working directory
            for normal execution.
    """

    RESOURCE_BASE = Path(getattr(sys, "_MEIPASS", Path.cwd()))

    @staticmethod
    def check_file_status(file_path: Path) -> None:
        """Check the status of a file before performing operations.

        Checks for various conditions:
        - Existence of the file
        - Whether it's a directory
        - Whether it's a symbolic link
        - Whether it's in use (hard link count > 1)

        Args:
            file_path (Path): The path to the file to check.

        Raises:
            FileMissingError: If the file does not exist.
            InvalidFileTypeError: If the file is a directory or a symbolic link.
            FileInUseError: If the file is in use (hard link count > 1).
        """

        if not file_path.exists():
            msg = f"File does not exist: {file_path}"
            raise FileMissingError(msg)
        if file_path.is_dir() or file_path.is_symlink():
            msg = f"Invalid file type (directory or symbolic link): {file_path}"
            raise InvalidFileTypeError(msg)
        if file_path.stat().st_nlink > 1:
            msg = f"File is in use (hard link count > 1): {file_path}"
            raise FileInUseError(msg)

    @staticmethod
    def remove(file_path: Path) -> None:
        """Remove a file from the filesystem with safety checks.

        Checks for various conditions before attempting file removal:
        - Existence of the file
        - Whether it's a directory
        - Whether it's a symbolic link
        - Whether it's in use (hard link count > 1)

        Args:
            file_path (Path): The path to the file to remove.

        Raises:
            FileMissingError: If the file does not exist.
            InvalidFileTypeError: If the file is a directory or a symbolic link.
            FileInUseError: If the file is in use (hard link count > 1).
            FilePermissionError: If there are insufficient permissions to delete the file.
        """

        FileUtils.check_file_status(file_path)
        try:
            file_path.unlink(missing_ok=True)
        except PermissionError as err:
            msg = f"Insufficient permissions to delete the file: {file_path}"
            raise FilePermissionError(msg) from err

    @staticmethod
    def resource_path(path: str | Path, *, strict: bool = False) -> Path:
        """Get the absolute path to a resource file, resolving it based on the execution context.

        This method is designed to work correctly whether the application is run as a script or as a PyInstaller bundle.

        Args:
            path (str | Path): The relative path to the resource file (e.g., "data/config.yaml").
            strict (bool): Whether to raise an exception if the resolved path does not exist. Defaults to False.

        Returns:
            Path: The resolved absolute path to the resource file.
        """
        return FileUtils.resolve_path(path, strict=strict, is_resource=True)

    @staticmethod
    def resolve_path(path: str | Path, *, strict: bool = False, is_resource: bool = False) -> Path:
        """Convert a user-input path to an absolute path safely.

        Expands environment variables (e.g., $HOME, %APPDATA%), expands ~ to the home directory,
        and resolves relative paths based on the current working directory.
        Optionally resolves symbolic links with `.resolve()`.

        Args:
            path (str | Path): The input path (e.g., "~/logs/$APP_ENV/app.log").
            strict (bool): Whether to raise an exception if the path does not exist. Defaults to False.
            is_resource (bool): Whether the path is a resource path. Defaults to False.
                PyInstaller's _MEIPASS is used as the base for resource paths when is_resource=True.

        Returns:
            Path: The converted absolute `Path` object.
        """
        expanded: str = os.path.expandvars(str(path))
        user_expanded: Path = Path(expanded).expanduser()

        if user_expanded.is_absolute():
            return user_expanded.resolve(strict=strict)

        base: Path = FileUtils.RESOURCE_BASE if is_resource else Path.cwd()

        return (base / user_expanded).resolve(strict=strict)

    @staticmethod
    def validate_file_path(file_path: Path, suffix: list[str] | str) -> None:
        """Validate that a file exists and has an allowed suffix.

        Args:
            file_path (Path): The path to the file to validate.
            suffix (list[str] | str): Allowed file suffix(es) (e.g., [".txt", ".md"] or ".txt").

        Raises:
            FileMissingError: If the file does not exist.
            UnsupportedFileFormatError: If the file's suffix is not in the allowed list.
        """

        if isinstance(suffix, str):
            suffix = [suffix]

        if not file_path.exists():
            msg = f"File does not exist: {file_path}"
            raise FileMissingError(msg)
        if file_path.suffix.lower() not in [s.lower() for s in suffix]:
            msg = f"Unsupported file format: '{file_path.suffix}'. Supported formats are: {', '.join(suffix)}"
            raise UnsupportedFileFormatError(msg)


class FileUtilsError(Exception):
    """Custom exception for FileUtils-related errors."""


class FileMissingError(FileUtilsError):
    """Custom exception for file missing errors."""


class InvalidFileTypeError(FileUtilsError):
    """Custom exception for invalid file type errors."""


class FileInUseError(FileUtilsError):
    """Custom exception for file-in-use errors."""


class FilePermissionError(FileUtilsError):
    """Custom exception for file permission errors."""


class UnsupportedFileFormatError(FileUtilsError):
    """Custom exception for unsupported file format errors."""

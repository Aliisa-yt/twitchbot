from __future__ import annotations

import os
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
    """

    @staticmethod
    def check_file_status(file_path: Path) -> None:
        """Challenges the status of a file before performing operations.

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
        return resolved_path

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

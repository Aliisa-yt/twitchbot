from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from models.re_models import URL_PATTERN
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

__all__: list[str] = ["StringUtils"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)
# logger.addHandler(logging.NullHandler())


class StringUtils:
    """String manipulation utilities for text processing.

    Provides various utility methods for string handling including type conversion,
    whitespace manipulation, URL removal, and IRC escape character decoding.
    """

    @staticmethod
    def ensure_str(value: str | None) -> str:
        """Ensure that the value is a string, returning an empty string if None.

        Note: Does not use strip() to preserve command delimiters and significant whitespace.

        Args:
            value (str | None): The value to ensure as a string.

        Returns:
            str: The value as a string, or empty string if None.
        """
        if not isinstance(value, str):
            logger.debug("Converting value to string: %s", value)
            value = str(value) if value is not None else ""
        # Do not use value.strip().
        # This has the unintended consequence of deleting whitespace characters that should not be deleted,
        # such as command delimiters.
        return value

    @staticmethod
    def compress_blanks(value: str) -> str:
        """Compress multiple consecutive spaces into a single space.

        Ensures the input is a string and removes leading and trailing whitespace.

        Args:
            value (str): The string to compress.

        Returns:
            str: The string with multiple spaces compressed to single spaces.
        """
        value = StringUtils.ensure_str(value)
        return " ".join(value.split())

    @staticmethod
    def replace_blanks(value: str, start: int, end: int) -> str:
        """Replace a substring with spaces while preserving string length.

        Replaces characters between start and end indices with spaces. If start is greater
        than end, they are automatically swapped.

        Args:
            value (str): The string to modify.
            start (int): The starting index (inclusive).
            end (int): The ending index (exclusive).

        Returns:
            str: The modified string with the substring replaced by spaces.

        Raises:
            IndexError: If start or end index is out of bounds.
        """
        value = StringUtils.ensure_str(value)
        length: int = len(value)

        if not (0 <= start <= length) or not (0 <= end <= length):
            logger.debug("Invalid indices: start=%d, end=%d, length=%d", start, end, length)
            msg: str = f"Start or end index is out of bounds: start={start}, end={end}, length={length}"
            raise IndexError(msg)

        if start > end:
            logger.debug("Swapping start and end indices: start=%d, end=%d", start, end)
            start, end = end, start

        logger.debug("Replacing substring with spaces: start=%d, end=%d", start, end)
        return value[:start] + " " * (end - start) + value[end:]

    @staticmethod
    def remove_url(value: str) -> str:
        """Remove URL-like strings from the given string.

        Finds and removes URLs while preserving the string length by replacing
        URL characters with spaces.

        Args:
            value (str): The string to process.

        Returns:
            str: The string with URLs replaced by spaces.
        """
        value = StringUtils.ensure_str(value)
        if not value:
            logger.debug("Value is empty, nothing to remove.")
            return value

        urls: set[str | Any] = {match.group(1) for match in re.finditer(URL_PATTERN, value)}
        for url in sorted(urls, key=len, reverse=True):
            value = value.replace(url, " " * len(url))
            logger.debug("Removed URL: %s", url)
        return value

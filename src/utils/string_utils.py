from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from models.re_models import URL_PATTERN

__all__: list[str] = ["StringUtils"]


class StringUtils:
    """Utility class for string manipulation and processing.

    Provides static methods for common string operations such as ensuring string type,
    compressing spaces, replacing substrings with spaces, and removing URLs.
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
            msg: str = f"Start or end index is out of bounds: start={start}, end={end}, length={length}"
            raise IndexError(msg)

        if start > end:
            start, end = end, start

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
            return value

        urls: set[str | Any] = {match.group(1) for match in re.finditer(URL_PATTERN, value)}
        for url in sorted(urls, key=len, reverse=True):
            value = value.replace(url, " " * len(url))
        return value

    @staticmethod
    def unicode_normalize(text: str, form: Literal["NFC", "NFD", "NFKC", "NFKD"] = "NFC") -> str:
        """Normalize text using Unicode normalization.

        Args:
            text (str): Text to normalize.
            form (Literal["NFC", "NFD", "NFKC", "NFKD"]): Unicode normalization form (NFC, NFD, NFKC, NFKD).

        Returns:
            str: Normalized text.
        """
        return unicodedata.normalize(form, text)

    @staticmethod
    def truncate_string(content: str, limit_length: int, *, ellipsis: str = " ...") -> str:
        """Truncate a string to fit within a specified character length.

        Truncates the input string to the specified character limit. If truncation occurs,
        appends the specified ellipsis to the end. If no truncation is needed, returns the original string.

        Args:
            content (str): The string content to potentially truncate.
            limit_length (int): The maximum allowed character length.
            ellipsis (str): The string to append if truncation occurs. Defaults to " ...".

        Returns:
            str: The truncated string with the specified ellipsis appended if truncated, otherwise the original.

        Raises:
            ValueError: If limit_length is negative.
        """
        if limit_length < 0:
            msg = "limit_length must be non-negative"
            raise ValueError(msg)

        if len(content) <= limit_length:
            return content

        limit_length -= len(ellipsis)
        if limit_length < 0:
            msg = "limit_length must be greater than or equal to the length of ellipsis"
            raise ValueError(msg)

        return f"{content[:limit_length]}{ellipsis}"

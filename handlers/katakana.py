"""Romanji to Katakana and English word to Katakana conversion utilities.

This module provides utilities for converting romanized Japanese text and English words
to Japanese Katakana characters. It includes the Romaji class for converting romanized
input to Katakana based on dictionary mappings, and the Katakanaise class for converting
English words to Katakana with support for both dictionary-based and algorithm-based conversion.

Key features:
    - Romaji to Katakana conversion using JSON dictionary files
    - English word to Katakana conversion with CamelCase word boundary detection
    - Dictionary loading and management
    - Fallback to romanization when dictionary entries are not found
"""

import json
import logging
import re
from json import JSONDecodeError
from pathlib import Path
from typing import ClassVar

from utils.logger_utils import LoggerUtils

__all__: list[str] = ["E2KConverter", "Romaji"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class _JSONLoader:
    """Helper class for loading JSON dictionary files.

    Provides utilities for reading JSON-formatted dictionary files containing
    character conversion mappings.
    """

    @staticmethod
    def load(dic_name: Path) -> dict[str, str]:
        """Load a JSON dictionary file.

        Args:
            dic_name (Path): Path to the JSON dictionary file.

        Returns:
            dict[str, str]: Dictionary with conversion mappings.
        """
        with dic_name.open(mode="r", encoding="utf-8") as fhdl:
            return json.load(fhdl)


class Romaji:
    """Convert romanized text to Japanese Katakana.

    This class manages the conversion of romanized Japanese text (romaji) to Katakana
    characters using dictionary-based lookups. It loads a JSON dictionary file where keys
    are romanized strings and values are their Katakana equivalents.

    Attributes:
        tree (dict[str, str]): Dictionary mapping romanized strings to Katakana.
        max_unit_len (int): Maximum length of romanized units in the dictionary.
    """

    tree: ClassVar[dict[str, str]] = {}
    max_unit_len: ClassVar[int] = 0

    @classmethod
    def load(cls, dic_name: Path) -> None:
        """Load a romanization dictionary from a JSON file.

        Loads the dictionary and calculates the maximum unit length for efficient
        matching. The loaded dictionary is stored in the class variable 'tree'.

        Args:
            dic_name (Path): Path to the JSON dictionary file.

        Raises:
            OSError: If the dictionary file cannot be read.
            RuntimeError: If the dictionary file is not valid JSON format.
        """
        logger.info("file open '%s' as read-only", dic_name)
        msg: str
        try:
            cls.tree = _JSONLoader.load(dic_name)
            cls.max_unit_len = max((len(k) for k in cls.tree), default=0)
            logger.info("loaded dictionary '%s'", dic_name)
        except OSError as err:
            logger.debug(err)
            msg = f"failed to load '{dic_name}'"
            raise OSError(msg) from err
        except JSONDecodeError as err:
            logger.debug(err)
            msg = f"'{dic_name}' is an invalid JSON format"
            raise RuntimeError(msg) from err

    @classmethod
    def is_unit(cls, tokens: str, s: int = 0) -> bool:
        """Check if a position in the string starts a convertible romanized unit.

        Checks whether the substring starting at position 's' in 'tokens' can be
        converted to a single Katakana mora (syllable unit).

        Args:
            tokens (str): The romanized string to check.
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            bool: True if the position starts a convertible unit, False otherwise.
        """
        return any(tokens[s : s + i] in cls.tree for i in range(cls.max_unit_len, 0, -1))

    @classmethod
    def get_unit(cls, tokens: str, s: int = 0) -> tuple[str, int]:
        """Convert a romanized unit to Katakana at the given position.

        Converts the substring starting at position 's' to a single Katakana mora
        and returns the converted character along with the position of the next unit.

        Args:
            tokens (str): The romanized string to convert.
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            tuple[str, int]: A tuple of (converted_katakana, next_index). Returns
                empty string if no conversion is found.
        """
        for i in range(cls.max_unit_len, 0, -1):
            if tokens[s : s + i] in cls.tree:
                return cls.tree[tokens[s : s + i]], s + i
        return "", s

    @classmethod
    def is_hatsuon(cls, tokens: str, s: int = 0) -> bool:
        """Check if the position should be converted to 'ン' (final n sound).

        Determines whether the character at position 's' should be converted to 'ン'.
        Converts 'n' if it's at end of string or followed by a non-vowel.
        Converts 'm' if it's followed by 'b', 'm', or 'p'.

        Args:
            tokens (str): The romanized string to check.
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            bool: True if the position should convert to 'ン', False otherwise.
        """
        if s >= len(tokens):
            return False
        ch: str = tokens[s]
        if ch == "n":
            return s + 1 == len(tokens) or tokens[s + 1] not in "aeiouy" or tokens[s + 1] == "'"
        if ch == "m":
            return s + 1 < len(tokens) and tokens[s + 1] in "bmp"
        return False

    @classmethod
    def get_hatsuon(cls, tokens: str, s: int = 0) -> tuple[str, int]:
        """Convert a character to 'ン' (final n sound).

        Converts the character at position 's' to 'ン' and returns the converted
        character with the position of the next character.

        Args:
            tokens (str): The romanized string (unused in this method).
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            tuple[str, int]: A tuple of ('ン', next_index).
        """
        _ = tokens
        return "ン", s + 1

    @classmethod
    def is_sokuon(cls, tokens: str, s: int = 0) -> bool:
        """Check if the position should be converted to 'ッ' (geminate marker).

        Determines whether the character at position 's' should be converted to 'ッ',
        which marks a doubled consonant in the following syllable. This occurs when
        the same consonant is repeated, excluding 'n' and 'm'.

        Args:
            tokens (str): The romanized string to check.
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            bool: True if the position should convert to 'ッ', False otherwise.
        """
        # Exclude 'n' and 'm' from gemination
        return s + 1 < len(tokens) and tokens[s].isalpha() and tokens[s] not in "nm" and tokens[s] == tokens[s + 1]

    @classmethod
    def get_sokuon(cls, tokens: str, s: int = 0) -> tuple[str, int]:
        """Convert a character to 'ッ' (geminate marker).

        Converts the character at position 's' to 'ッ' and returns the converted
        character with the position of the next character.

        Args:
            tokens (str): The romanized string (unused in this method).
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            tuple[str, int]: A tuple of ('ッ', next_index).
        """
        _ = tokens
        return "ッ", s + 1

    @classmethod
    def get_kana(cls, tokens: str, s: int = 0) -> str:
        """Convert romanized text to Katakana starting from the given position.

        Converts the substring from position 's' onwards to Katakana by processing
        each character as a unit, detecting gemination markers, and final n sounds.

        Args:
            tokens (str): The romanized string to convert.
            s (int): Starting index in the string. Defaults to 0.

        Returns:
            str: The converted Katakana string, or empty string if index is invalid.
        """
        # Return empty string if index is out of bounds
        if s >= len(tokens) or s < 0:
            return ""

        kana: str = ""
        res: list[str] = []
        idx: int = s
        while idx < len(tokens):
            if cls.is_unit(tokens, idx):
                # If a convertible romanized unit is found, convert it
                kana, idx = cls.get_unit(tokens, idx)
            elif cls.is_hatsuon(tokens, idx):
                # If a final n sound is found, convert it to 'ン'
                kana, idx = cls.get_hatsuon(tokens, idx)
            elif cls.is_sokuon(tokens, idx):
                # If a geminate marker is found, convert it to 'ッ'
                kana, idx = cls.get_sokuon(tokens, idx)
            else:
                # If no conversion is possible, keep the character as is
                kana, idx = tokens[idx], idx + 1
            res.append(kana)
        return "".join(res)

    @classmethod
    def romanize(cls, text: str) -> str:
        """Convert a romanized string to Katakana.

        Converts the entire romanized input string to Katakana. The input is converted
        to lowercase before processing since uppercase/lowercase distinction is not
        meaningful in romanization.

        Args:
            text (str): The romanized string to convert (case-insensitive).

        Returns:
            str: The converted Katakana string.
        """
        text = text.lower()
        return cls.get_kana(text, 0)


class E2KConverter:
    """Convert English words and text to Japanese Katakana.

    This class converts English words and mixed text containing English to Katakana characters.
    It uses a dictionary file for direct word mappings and falls back to romanization for
    unknown words. CamelCase word boundaries are detected and used to segment concatenated
    words, while unconvertible words are romanized using the Romaji converter.

    Attributes:
        e2kata_dict (dict[str, str]): Dictionary mapping English words (uppercase) to Katakana.

    Examples:
        "HELLO WORLD" -> "ハロー ワールド" (dictionary lookup)
        "ThisIsAnExample" -> "ディスイズアンエグザンプル" (CamelCase segmentation)
        "HELLO123" -> "ハロー123" (numbers preserved)
        "HELLO_WORLD!" -> "ハロー_ワールド!" (punctuation preserved)
    """

    e2kata_dict: ClassVar[dict[str, str]] = {}

    @classmethod
    def clear(cls) -> None:
        """Clear the English to Katakana dictionary."""
        cls.e2kata_dict.clear()

    @classmethod
    def load(cls, dic_name: Path) -> None:
        """Load English to Katakana dictionary from a file.

        Reads a text file where each line contains an English word and its Katakana
        equivalent separated by whitespace. Lines starting with non-alphabetic characters
        are treated as comments and ignored.

        Args:
            dic_name (Path): Path to the dictionary file.

        Raises:
            OSError: If the dictionary file cannot be read.

        Examples:
            File format:
                hello ハロー
                world ワールド
        """
        logger.info("file open '%s' as read-only", dic_name)
        try:
            with dic_name.open(mode="r", encoding="utf-8") as fhdl:
                for line in fhdl:
                    # Remove trailing newlines and split by whitespace
                    line_list: list[str] = line.strip().split()
                    if len(line_list) < 2:
                        continue
                    # Only process if the first element starts with an alphabetic character
                    # Otherwise, treat it as a comment line
                    if re.match(r"^[A-Za-z]+", line_list[0]):
                        cls.e2kata_dict[line_list[0].upper()] = line_list[1]
            logger.info("loaded dictionary '%s'", dic_name)
        except OSError as err:
            logger.debug(err)
            msg: str = f"failed to load '{dic_name}'"
            raise OSError(msg) from err

    @classmethod
    def katakanaize(cls, msg: str) -> str:
        """Convert English words in text to Katakana.

        Converts English words to Katakana by dictionary lookup or romanization.
        Handles CamelCase word segmentation for concatenated English words.
        Preserves numbers, symbols, and non-alphabetic characters.

        When consecutive alphabetic characters without spaces are encountered:
        - If CamelCase format is detected, segments are separated at uppercase boundaries
        - Otherwise, the entire sequence is treated as a single word

        Word conversion priority:
        1. Check the dictionary for exact match (uppercase)
        2. Fall back to romanization using Romaji converter
        3. Apply special character replacements for non-dictionary entries

        Args:
            msg (str): The text to convert (typically identified as Japanese by language detection).

        Returns:
            str: The converted text with English words replaced by Katakana.

        Examples:
            "ThisIsAnExample" -> "ディスイズアンエグザンプル"
            "HELLO WORLD" -> "ハロー ワールド"
            "HELLO123" -> "ハロー123"
            "HELLO_WORLD!" -> "ハロー_ワールド!"
        """
        logger.debug("Original message: %s", msg)

        # Find all sequences of alphabetic characters, including trailing spaces
        matched_alphabets: list[str] = re.findall(r"['A-Za-z]+ ?", msg)
        logger.debug("Matching alphabet strings: %s", matched_alphabets)

        # Process from longest to shortest to avoid partial replacements
        for found in sorted(matched_alphabets, key=len, reverse=True):
            # Check if trailing space is present
            has_trailing_space: bool = found.endswith(" ")
            # Remove trailing space for processing
            trimmed: str = found.rstrip(" ")

            # Segment CamelCase words at uppercase boundaries
            matched_words: list[str] = re.findall(r"['A-Za-z]+?(?:(?=[A-Z]|$))", trimmed)
            logger.debug("Matched words: %s", matched_words)

            converted: str = trimmed
            for word in sorted(matched_words, key=len, reverse=True):
                # Skip single-character words
                if len(word) == 1:
                    continue
                # Look up word in dictionary, or convert via romanization
                kata: str = cls.e2kata_dict.get(
                    word.upper(), cls._replace_nonconversion_characters(Romaji.romanize(word))
                )
                converted = converted.replace(word, kata)

            logger.debug("Converted string: %s", converted)
            # Handle remaining all-uppercase sequences that may not have been replaced
            kata = cls.e2kata_dict.get(
                converted.upper(), cls._replace_nonconversion_characters(Romaji.romanize(converted))
            )
            # Restore trailing space if it was present in the original
            if has_trailing_space:
                kata += " "
            # Replace the original substring with converted version
            msg = msg.replace(found, kata)
        logger.debug("Final converted message: %s", msg)
        return msg

    @classmethod
    def _replace_nonconversion_characters(cls, romaji: str) -> str:
        """Replace unconvertible characters with fallback Katakana mappings.

        This method handles individual characters that don't have dictionary entries
        and converts them based on standard phonetic approximations to Katakana.

        Args:
            romaji (str): The romanized string with potentially unconvertible characters.

        Returns:
            str: The string with unconvertible characters replaced by Katakana approximations.
        """
        # Phonetic fallback mappings for individual characters
        special_conversion: dict[str, str] = {
            "b": "ブ",
            "c": "ク",
            "d": "ド",
            "f": "フ",
            "g": "グ",
            "h": "ハ",
            "j": "ジ",
            "k": "ク",
            "l": "ル",
            "p": "プ",
            "q": "ク",
            "r": "ア",
            "s": "ス",
            "t": "ト",
            "v": "ブ",
            "w": "ウ",
            "x": "クス",
            "y": "イー",
            "z": "ズ",
        }
        for _alpha, _kana in special_conversion.items():
            romaji = romaji.replace(_alpha, _kana)
        return romaji

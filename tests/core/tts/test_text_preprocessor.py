"""Unit tests for TextPreprocessor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from core.tts.text_preprocessor import TextPreprocessor
from models.voice_models import TTSParam


def _make_config(
    *,
    native_language: str = "ja",
    second_language: str = "en",
    enabled_languages: list[str] | None = None,
    katakanaise: bool = False,
    limit_characters: int | None = None,
) -> Any:
    return SimpleNamespace(
        TRANSLATION=SimpleNamespace(
            NATIVE_LANGUAGE=native_language,
            SECOND_LANGUAGE=second_language,
        ),
        TTS=SimpleNamespace(
            ENABLED_LANGUAGES=enabled_languages,
            KATAKANAISE=katakanaise,
            LIMIT_CHARACTERS=limit_characters,
        ),
    )


def _make_tts_param(content: str, content_lang: str | None = "ja") -> TTSParam:
    param = MagicMock(spec=TTSParam)
    param.content = content
    param.content_lang = content_lang
    return param


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_returns_none_when_content_lang_is_none(mock_emoji_cls: MagicMock) -> None:
    """Returns None when content_lang is None."""
    _ = mock_emoji_cls
    config = _make_config()
    preprocessor = TextPreprocessor(config)

    param = _make_tts_param("hello", content_lang=None)
    result = preprocessor.process(param)

    assert result is None


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_returns_none_when_language_not_enabled(mock_emoji_cls: MagicMock) -> None:
    """Returns None when the content language is not in ENABLED_LANGUAGES."""
    _ = mock_emoji_cls
    config = _make_config(enabled_languages=["ja", "en"])
    preprocessor = TextPreprocessor(config)

    param = _make_tts_param("hola", content_lang="es")
    result = preprocessor.process(param)

    assert result is None


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_passes_when_enabled_languages_is_none(mock_emoji_cls: MagicMock) -> None:
    """Returns the TTSParam when ENABLED_LANGUAGES is None (no restriction)."""
    config = _make_config(enabled_languages=None)
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.side_effect = lambda content, _lang: content

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("hello", content_lang="en")
    result = preprocessor.process(param)

    assert result is param


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_passes_when_language_is_enabled(mock_emoji_cls: MagicMock) -> None:
    """Returns the TTSParam when the content language is in ENABLED_LANGUAGES."""
    config = _make_config(enabled_languages=["ja", "en"])
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.side_effect = lambda content, _lang: content

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("hello", content_lang="en")
    result = preprocessor.process(param)

    assert result is param


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_trims_content_to_limit(mock_emoji_cls: MagicMock) -> None:
    """Trims content to LIMIT_CHARACTERS when a limit is configured."""
    config = _make_config(limit_characters=5)
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.side_effect = lambda content, _lang: content

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("0123456789", content_lang="en")
    result = preprocessor.process(param)

    assert result is not None
    assert result.content == "01234"


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_returns_none_when_content_empty_after_conversion(mock_emoji_cls: MagicMock) -> None:
    """Returns None when content becomes empty after emoji conversion."""
    config = _make_config()
    mock_emoji_inst = mock_emoji_cls.return_value
    # Simulate the case where emoji-only text becomes an empty string after conversion
    mock_emoji_inst.emojize_to_text.return_value = ""

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("😀", content_lang="ja")
    result = preprocessor.process(param)

    assert result is None


@patch("core.tts.text_preprocessor.E2KConverter")
@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_katakanaizes_japanese(mock_emoji_cls: MagicMock, mock_e2k_cls: MagicMock) -> None:
    """Calls E2KConverter.katakanaize when KATAKANAISE=True and content_lang="ja"."""
    config = _make_config(katakanaise=True)
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.side_effect = lambda content, _lang: content
    mock_e2k_cls.katakanaize.return_value = "カタカナ"

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("hello", content_lang="ja")
    result = preprocessor.process(param)

    mock_e2k_cls.katakanaize.assert_called_once_with("hello")
    assert result is not None
    assert result.content == "カタカナ"


@patch("core.tts.text_preprocessor.E2KConverter")
@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_skips_katakanaize_for_non_japanese(mock_emoji_cls: MagicMock, mock_e2k_cls: MagicMock) -> None:
    """Does not call katakanaize even when KATAKANAISE=True if content_lang is not "ja"."""
    config = _make_config(katakanaise=True)
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.side_effect = lambda content, _lang: content

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("hello", content_lang="en")
    preprocessor.process(param)

    mock_e2k_cls.katakanaize.assert_not_called()


@patch("core.tts.text_preprocessor.EmojiHandler")
def test_process_calls_emojize_to_text(mock_emoji_cls: MagicMock) -> None:
    """Verifies that process() calls EmojiHandler.emojize_to_text."""
    config = _make_config()
    mock_emoji_inst = mock_emoji_cls.return_value
    mock_emoji_inst.emojize_to_text.return_value = "converted"

    preprocessor = TextPreprocessor(config)
    param = _make_tts_param("😀", content_lang="ja")
    result = preprocessor.process(param)

    mock_emoji_inst.emojize_to_text.assert_called_once_with("😀", "ja")
    assert result is not None
    assert result.content == "converted"

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from config.loader import ConfigFileNotFoundError, ConfigFormatError, ConfigLoader, ConfigValueError

if TYPE_CHECKING:
    from pathlib import Path

    from models.voice_models import Voice


def _write_ini(tmp_path: Path, content: str) -> Path:
    ini_path: Path = tmp_path / "twitchbot.ini"
    ini_path.write_text(dedent(content), encoding="utf-8")
    return ini_path


def test_config_loader_raises_for_missing_file(tmp_path: Path) -> None:
    ini_path: Path = tmp_path / "missing.ini"
    with pytest.raises(ConfigFileNotFoundError):
        ConfigLoader(config_filename=str(ini_path), script_name="test")


def test_config_loader_overrides_and_color_mapping(tmp_path: Path) -> None:
    ini_path: Path = _write_ini(
        tmp_path,
        """
        [GENERAL]
        DEBUG = False

        [TWITCH]
        OWNER_NAME = "owner1"

        [BOT]
        BOT_NAME = "bot1"
        COLOR = "Blue"

        [TRANSLATION]
        ENGINE = ["google"]
        """,
    )

    loader = ConfigLoader(
        config_filename=str(ini_path),
        script_name="test",
        owner="override_owner",
        bot="override_bot",
        debug=True,
    )

    assert loader.config.TWITCH.OWNER_NAME == "override_owner"
    assert loader.config.BOT.BOT_NAME == "override_bot"
    assert loader.config.GENERAL.DEBUG is True
    assert loader.config.BOT.COLOR == "blue"


def test_voice_parameters_parse_cast_and_params(tmp_path: Path) -> None:
    ini_path: Path = _write_ini(
        tmp_path,
        """
        [TWITCH]
        OWNER_NAME = "owner1"

        [BOT]
        BOT_NAME = "bot1"
        COLOR = "blue"

        [TRANSLATION]
        ENGINE = ["google"]

        [CAST]
        DEFAULT = [{"lang": "ja", "engine": "voicevox", "cast": "test", "param": "v1.0,s2,t3,a4,i5"}]
        """,
    )

    loader = ConfigLoader(config_filename=str(ini_path), script_name="test")
    voice: Voice = loader.config.VOICE_PARAMETERS.streamer["ja"].voice

    assert voice.cast == "test"
    assert voice.volume == 100
    assert voice.speed == 2
    assert voice.tone == 3
    assert voice.alpha == 4
    assert voice.intonation == 5


def test_invalid_translation_engine_type_raises_format_error(tmp_path: Path) -> None:
    ini_path: Path = _write_ini(
        tmp_path,
        """
        [TWITCH]
        OWNER_NAME = "owner1"

        [BOT]
        BOT_NAME = "bot1"
        COLOR = "blue"

        [TRANSLATION]
        ENGINE = 1
        """,
    )

    with pytest.raises(ConfigFormatError):
        ConfigLoader(config_filename=str(ini_path), script_name="test")


def test_invalid_boolean_value_raises_config_value_error(tmp_path: Path) -> None:
    ini_path: Path = _write_ini(
        tmp_path,
        """
        [TWITCH]
        OWNER_NAME = "owner1"

        [BOT]
        BOT_NAME = "bot1"
        COLOR = "blue"
        DONT_LOGIN_MESSAGE = maybe

        [TRANSLATION]
        ENGINE = ["google"]
        """,
    )

    with pytest.raises(ConfigValueError):
        ConfigLoader(config_filename=str(ini_path), script_name="test")


def test_invalid_cast_param_raises_config_value_error(tmp_path: Path) -> None:
    ini_path: Path = _write_ini(
        tmp_path,
        """
        [TWITCH]
        OWNER_NAME = "owner1"

        [BOT]
        BOT_NAME = "bot1"
        COLOR = "blue"

        [TRANSLATION]
        ENGINE = ["google"]

        [CAST]
        DEFAULT = [{"lang": "ja", "engine": "voicevox", "cast": "test", "param": "x1"}]
        """,
    )

    with pytest.raises(ConfigValueError):
        ConfigLoader(config_filename=str(ini_path), script_name="test")

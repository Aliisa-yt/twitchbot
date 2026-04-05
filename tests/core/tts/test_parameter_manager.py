"""Unit tests for core.tts.parameter_manager module."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.tts.parameter_manager import ParameterManager
from models.voice_models import TTSInfo, TTSInfoPerLanguage, UserTypeInfo, Voice

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tts_info(lang: str = "ja", engine: str = "voicevox", **voice_kwargs: Any) -> TTSInfo:
    return TTSInfo(supported_lang=lang, engine=engine, voice=Voice(**voice_kwargs))


def _make_config(
    native_language: str = "ja",
    voice_parameters: UserTypeInfo | None = None,
) -> Any:
    if voice_parameters is None:
        voice_parameters = UserTypeInfo(
            streamer={"ja": _make_tts_info("ja", volume=100, speed=100)},
            moderator={"ja": _make_tts_info("ja", volume=90, speed=90)},
            vip={"ja": _make_tts_info("ja", volume=80, speed=80)},
            subscriber={"ja": _make_tts_info("ja", volume=70, speed=70)},
            others={"ja": _make_tts_info("ja", volume=60, speed=60)},
            system={"ja": _make_tts_info("ja", volume=50, speed=50)},
        )
    return SimpleNamespace(
        TRANSLATION=SimpleNamespace(NATIVE_LANGUAGE=native_language),
        VOICE_PARAMETERS=voice_parameters,
    )


def _make_message(content: str, **chatter_flags: Any) -> MagicMock:
    """Create a ChatMessageHandler-like mock with a writable content attribute."""
    flags: dict[str, Any] = {
        "broadcaster": False,
        "moderator": False,
        "vip": False,
        "subscriber": False,
    }
    flags.update(chatter_flags)
    author = SimpleNamespace(**flags)
    msg = MagicMock()
    msg.content = content
    msg.author = author
    return msg


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_config(self) -> None:
        config = _make_config()
        pm = ParameterManager(config)
        assert pm.config is config

    def test_stores_voice_parameters(self) -> None:
        config = _make_config()
        pm = ParameterManager(config)
        assert pm.voice_parameters is config.VOICE_PARAMETERS

    def test_initial_onetime_params_are_empty_voice(self) -> None:
        pm = ParameterManager(_make_config())
        assert pm._onetime_voiceparameters == Voice()

    def test_initial_usertype_params_are_empty(self) -> None:
        pm = ParameterManager(_make_config())
        assert pm._usertype_voiceparameters == {}


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_resets_onetime_voiceparameters(self) -> None:
        pm = ParameterManager(_make_config())
        pm._onetime_voiceparameters = Voice(volume=99, speed=50)
        pm.clear()
        assert pm._onetime_voiceparameters == Voice()

    def test_resets_usertype_voiceparameters(self) -> None:
        pm = ParameterManager(_make_config())
        pm._usertype_voiceparameters = {"ja": _make_tts_info()}
        pm.clear()
        assert pm._usertype_voiceparameters == {}


# ---------------------------------------------------------------------------
# get_voice_param – system voice
# ---------------------------------------------------------------------------


class TestGetVoiceParamSystem:
    def test_returns_system_voice_for_matching_lang(self) -> None:
        system_info = _make_tts_info("ja", volume=50)
        vp = UserTypeInfo(system={"ja": system_info})
        pm = ParameterManager(_make_config(voice_parameters=vp))

        result = pm.get_voice_param("ja", is_system=True)

        assert result is system_info

    def test_falls_back_to_all_when_lang_missing(self) -> None:
        all_info = _make_tts_info(engine="gtts", volume=30)
        vp = UserTypeInfo(system={"all": all_info})
        pm = ParameterManager(_make_config(voice_parameters=vp))

        result = pm.get_voice_param("en", is_system=True)

        assert result is all_info

    def test_raises_key_error_when_no_system_voice(self) -> None:
        vp = UserTypeInfo(system={})
        pm = ParameterManager(_make_config(voice_parameters=vp))

        with pytest.raises(KeyError, match="System voice parameters for 'en' and 'all' are missing"):
            pm.get_voice_param("en", is_system=True)

    def test_uses_native_language_when_lang_not_supplied(self) -> None:
        system_info = _make_tts_info("ja")
        vp = UserTypeInfo(system={"ja": system_info})
        pm = ParameterManager(_make_config(native_language="ja", voice_parameters=vp))

        result = pm.get_voice_param(is_system=True)

        assert result is system_info


# ---------------------------------------------------------------------------
# get_voice_param – user voice
# ---------------------------------------------------------------------------


class TestGetVoiceParamUser:
    def _pm_with_usertype(self, lang_map: TTSInfoPerLanguage, native: str = "ja") -> ParameterManager:
        vp = UserTypeInfo()
        pm = ParameterManager(_make_config(native_language=native, voice_parameters=vp))
        pm._usertype_voiceparameters = lang_map
        return pm

    def test_returns_voice_for_matching_lang(self) -> None:
        info = _make_tts_info("ja", volume=60)
        pm = self._pm_with_usertype({"ja": info})

        result = pm.get_voice_param("ja")

        assert result is info

    def test_falls_back_to_all_when_lang_missing(self) -> None:
        all_info = _make_tts_info(engine="cevio", volume=40)
        pm = self._pm_with_usertype({"all": all_info})

        result = pm.get_voice_param("fr")

        assert result is all_info

    def test_uses_native_language_when_lang_not_supplied(self) -> None:
        info = _make_tts_info("ja")
        pm = self._pm_with_usertype({"ja": info}, native="ja")

        result = pm.get_voice_param()

        assert result is info

    def test_raises_key_error_when_no_voice_for_lang(self) -> None:
        pm = self._pm_with_usertype({})

        with pytest.raises(KeyError, match="Voice parameters for 'en' and 'all' are missing"):
            pm.get_voice_param("en")

    def test_applies_onetime_volume_to_result(self) -> None:
        info = _make_tts_info("ja", volume=60, speed=100)
        pm = self._pm_with_usertype({"ja": info})
        pm._onetime_voiceparameters = Voice(volume=99)

        result = pm.get_voice_param("ja")

        assert result.voice.volume == 99

    def test_applies_onetime_speed_to_result(self) -> None:
        info = _make_tts_info("ja", volume=60, speed=100)
        pm = self._pm_with_usertype({"ja": info})
        pm._onetime_voiceparameters = Voice(speed=50)

        result = pm.get_voice_param("ja")

        assert result.voice.speed == 50

    def test_does_not_apply_onetime_param_when_none(self) -> None:
        """None in _onetime_voiceparameters should leave the original value intact."""
        info = _make_tts_info("ja", volume=60, speed=100)
        pm = self._pm_with_usertype({"ja": info})
        # _onetime_voiceparameters.volume is None by default → should keep original 60
        pm._onetime_voiceparameters = Voice(speed=50)

        result = pm.get_voice_param("ja")

        assert result.voice.volume == 60
        assert result.voice.speed == 50


# ---------------------------------------------------------------------------
# select_voice_usertype
# ---------------------------------------------------------------------------


class TestSelectVoiceUsertype:
    @pytest.fixture
    def pm(self) -> ParameterManager:
        vp = UserTypeInfo(
            streamer={"ja": _make_tts_info(volume=100)},
            moderator={"ja": _make_tts_info(volume=90)},
            vip={"ja": _make_tts_info(volume=80)},
            subscriber={"ja": _make_tts_info(volume=70)},
            others={"ja": _make_tts_info(volume=60)},
        )
        return ParameterManager(_make_config(voice_parameters=vp))

    def test_selects_streamer_for_broadcaster(self, pm: ParameterManager) -> None:
        msg = _make_message("hi", broadcaster=True)
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.streamer

    def test_selects_moderator(self, pm: ParameterManager) -> None:
        msg = _make_message("hi", moderator=True)
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.moderator

    def test_selects_vip(self, pm: ParameterManager) -> None:
        msg = _make_message("hi", vip=True)
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.vip

    def test_selects_subscriber(self, pm: ParameterManager) -> None:
        msg = _make_message("hi", subscriber=True)
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.subscriber

    def test_selects_others_when_no_special_role(self, pm: ParameterManager) -> None:
        msg = _make_message("hi")
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.others

    def test_calls_clear_before_selecting(self, pm: ParameterManager) -> None:
        """select_voice_usertype must reset state before applying new user type."""
        pm._onetime_voiceparameters = Voice(volume=42)
        pm._usertype_voiceparameters = {"stale": _make_tts_info()}

        msg = _make_message("hi")
        pm.select_voice_usertype(msg)

        assert pm._onetime_voiceparameters == Voice()
        assert "stale" not in pm._usertype_voiceparameters

    def test_broadcaster_takes_priority_over_moderator(self, pm: ParameterManager) -> None:
        """When broadcaster=True, streamer params should win regardless of other flags."""
        msg = _make_message("hi", broadcaster=True, moderator=True)
        pm.select_voice_usertype(msg)
        assert pm._usertype_voiceparameters == pm.voice_parameters.streamer


# ---------------------------------------------------------------------------
# command_voiceparameters
# ---------------------------------------------------------------------------


class TestCommandVoiceparameters:
    @pytest.fixture
    def pm(self) -> ParameterManager:
        return ParameterManager(_make_config())

    def test_no_command_block_leaves_content_unchanged(self, pm: ParameterManager) -> None:
        msg = _make_message("hello world")
        pm.command_voiceparameters(msg)
        assert msg.content == "hello world"
        assert pm._onetime_voiceparameters == Voice()

    def test_parses_comma_separated_params(self, pm: ParameterManager) -> None:
        msg = _make_message("{v1, s-2, t0, a3, i-4} hello")
        pm.command_voiceparameters(msg)
        assert pm._onetime_voiceparameters.volume == 1
        assert pm._onetime_voiceparameters.speed == -2
        assert pm._onetime_voiceparameters.tone == 0
        assert pm._onetime_voiceparameters.alpha == 3
        assert pm._onetime_voiceparameters.intonation == -4

    def test_parses_space_separated_params(self, pm: ParameterManager) -> None:
        msg = _make_message("{v10 s-5 t3} hi")
        pm.command_voiceparameters(msg)
        assert pm._onetime_voiceparameters.volume == 10
        assert pm._onetime_voiceparameters.speed == -5
        assert pm._onetime_voiceparameters.tone == 3

    def test_removes_command_block_from_content(self, pm: ParameterManager) -> None:
        msg = _make_message("{v1} hello")
        original_len = len(msg.content)
        pm.command_voiceparameters(msg)
        # Block is replaced with spaces, so length is preserved
        assert len(msg.content) == original_len
        assert "hello" in msg.content
        assert "{v1}" not in msg.content

    def test_multiple_command_blocks_all_parsed(self, pm: ParameterManager) -> None:
        msg = _make_message("{v5} some text {s-3}")
        pm.command_voiceparameters(msg)
        assert pm._onetime_voiceparameters.volume == 5
        assert pm._onetime_voiceparameters.speed == -3

    def test_case_insensitive_command_keys(self, pm: ParameterManager) -> None:
        msg = _make_message("{V100 S50}")
        pm.command_voiceparameters(msg)
        assert pm._onetime_voiceparameters.volume == 100
        assert pm._onetime_voiceparameters.speed == 50

    def test_non_matching_block_is_ignored(self, pm: ParameterManager) -> None:
        # Mixed-content blocks like "{v1, zABC, s2}" do not match COMMAND_PATTERN,
        # so content should be unchanged and no params should be set.
        msg = _make_message("{v1, zABC, s2}")
        original_content = msg.content
        pm.command_voiceparameters(msg)
        assert msg.content == original_content
        assert pm._onetime_voiceparameters == Voice()

    def test_last_block_wins_on_duplicate_key(self, pm: ParameterManager) -> None:
        """When the same param appears in two separate blocks, the last value wins."""
        msg = _make_message("{v10} text {v99}")
        pm.command_voiceparameters(msg)
        assert pm._onetime_voiceparameters.volume == 99

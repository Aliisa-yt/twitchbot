"""Configuration file loader and validator.

Handles reading, formatting, and validating settings from the INI configuration file.
Raises exceptions for any issues encountered during loading.
"""

from __future__ import annotations

import ast
import configparser
import re
from configparser import ConfigParser
from dataclasses import fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from models.config_models import Config
from models.voice_models import TTSInfo, TTSInfoPerLanguage, UserTypeInfo, Voice
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable
    from dataclasses import Field as DataclassField
else:
    from dataclasses import Field as DataclassField

__all__: list[str] = [
    "ConfigFileNotFoundError",
    "ConfigFormatError",
    "ConfigLoader",
    "ConfigTypeError",
    "ConfigValueError",
    "InternalError",
]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

ALLOWED_TRANSLATION_ENGINES: list[str] = ["google", "deepl", "google_cloud"]

API_COLORS: list[str] = [
    "blue",
    "blue_violet",
    "cadet_blue",
    "chocolate",
    "coral",
    "dodger_blue",
    "firebrick",
    "golden_rod",
    "green",
    "hot_pink",
    "orange_red",
    "red",
    "sea_green",
    "spring_green",
    "yellow_green",
]

CHAT_COMMAND_COLORS: list[str] = [
    "Blue",
    "BlueViolet",
    "CadetBlue",
    "Chocolate",
    "Coral",
    "DodgerBlue",
    "Firebrick",
    "GoldenRod",
    "Green",
    "HotPink",
    "OrangeRed",
    "Red",
    "SeaGreen",
    "SpringGreen",
    "YellowGreen",
]


class InternalError(Exception):
    """An anomaly occurred in the internal process."""


class ConfigLoaderError(Exception):
    """An error occurred while processing the configuration file."""


class ConfigFileNotFoundError(ConfigLoaderError):
    """The specified configuration file does not exist."""


class ConfigFormatError(ConfigLoaderError):
    """The configuration file is not formatted correctly."""


class ConfigValueError(ConfigFormatError):
    """The configuration file contains an invalid value."""


class ConfigTypeError(ConfigFormatError):
    """The configuration file contains an invalid type."""


class ConfigLoader:
    """Handles loading and validation of configuration settings.

    This class reads the configuration file, applies formatting rules, and validates settings.
    It raises exceptions for any issues encountered during the loading process.

    Args:
        config_filename (str): INI file name to load.
        script_name (str): Executing script name, used in error messaging.
        owner_name (str | None): Optional override for the Twitch owner name.
        bot_name (str | None): Optional override for the bot user name.

    Raises:
        ConfigFileNotFoundError: If the configuration file does not exist.
        ConfigFormatError: If the file cannot be parsed or contains invalid values/types.
    """

    def __init__(
        self,
        *,
        config_filename: str,
        script_name: str,
        **args,
    ) -> None:
        config_path = Path(config_filename)
        msg: str
        if not config_path.exists():
            msg = (
                f"Configuration file '{config_filename}' not found. "
                f"Please create '{config_filename}' in the same directory as '{script_name}'."
            )
            raise ConfigFileNotFoundError(msg)

        parser: ConfigParser = ConfigParser()

        try:
            parser.read(config_filename, encoding="utf-8")
        except configparser.Error as err:
            msg = f"Failed to parse configuration file '{config_filename}': {err}"
            raise ConfigFormatError(msg) from None

        self.config = Config()
        self._convert_settings(parser)
        self.config.VOICE_PARAMETERS = self._get_voice_parameters()
        # Apply command-line argument overrides
        if args.get("owner") is not None:
            self.config.TWITCH.OWNER_NAME = args["owner"]
        if args.get("bot") is not None:
            self.config.BOT.BOT_NAME = args["bot"]
        if args.get("debug", False):
            self.config.GENERAL.DEBUG = True
        self._validate_settings()

    def _convert_settings(self, parser: ConfigParser) -> None:
        """Convert configuration settings from the parser to the Config object.

        This method iterates through each section and field in the Config object,
        applying the appropriate formatting based on the field type.

        Args:
            parser (ConfigParser): Parsed INI data.

        Raises:
            ConfigFormatError: If a value cannot be parsed or coerced to the expected type.
        """
        formatter = _ConfigFormatter(self.config, parser)
        for section in fields(self.config):
            # VOICE_PARAMETERS is a parameter that will be automatically generated later.
            # Skip it now as it has no content.
            if section.name == "VOICE_PARAMETERS":
                continue
            self._convert_section_field(parser, formatter, section)

    def _convert_section_field(
        self, parser: ConfigParser, formatter: _ConfigFormatter, section: DataclassField[Any]
    ) -> None:
        """Convert all fields in a configuration section.

        Iterates through each field in the section, formats its value from the INI parser,
        and assigns it to the corresponding Config attribute.

        Args:
            parser (ConfigParser): Parsed INI data.
            formatter (_ConfigFormatter): Formatter used to coerce string values to typed values.
            section (Field[Any]): Target configuration section dataclass field.

        Raises:
            ConfigFormatError: If a value fails to format correctly.
        """
        for key in fields(getattr(self.config, section.name)):
            try:
                parser[section.name][key.name]
            except KeyError:
                logger.debug("Skipping undefined setting: '%s.%s'", section.name, key.name)
                continue

            formatted_value = formatter.apply_format(section, key)
            setattr(getattr(self.config, section.name), key.name, formatted_value)

    def _get_voice_parameters(self) -> UserTypeInfo:
        """Build UserTypeInfo by merging default voice parameters with user-type-specific settings.

        Returns:
            UserTypeInfo: Voice parameters organized by user type and language.
        """
        default_voice_params: TTSInfoPerLanguage = self._check_voice_parameters(self.config.CAST.DEFAULT)

        voice_params_dict = UserTypeInfo()
        for user_type in [
            "STREAMER",
            "MODERATOR",
            "VIP",
            "SUBSCRIBER",
            "OTHERS",
            "SYSTEM",
        ]:
            lang_dict: TTSInfoPerLanguage = {}
            for lang, default_voice in default_voice_params.items():
                lang_dict[lang] = default_voice.copy()

            user_voice_list = getattr(self.config.CAST, user_type)
            user_voice_params: TTSInfoPerLanguage = self._check_voice_parameters(user_voice_list)
            for lang, user_voice in user_voice_params.items():
                lang_dict[lang] = user_voice.copy()

            setattr(voice_params_dict, user_type.lower(), lang_dict)
        return voice_params_dict

    def _check_voice_parameters(self, params: list[dict[str, str]]) -> TTSInfoPerLanguage:
        """Parse and validate voice parameters for each language.

        Args:
            params: List of dictionaries containing lang, engine, cast, and param keys.

        Returns:
            TTSInfoPerLanguage: Dictionary mapping language codes to TTSInfo objects.

        Raises:
            ConfigValueError: If any parameter value is invalid.
        """
        voice_parameter: TTSInfoPerLanguage = {}

        parameter_type_map: dict[str, Callable[[TTSInfo, Voice, str], None]] = {
            "lang": self._set_lang,
            "engine": self._set_engine,
            "cast": self._set_cast,
            "param": self._set_param,
        }

        for language_parameters in params:
            tmp_ttsinfo: TTSInfo = TTSInfo()
            tmp_voice: Voice = Voice()
            for _key, _value in language_parameters.items():
                parameter_type: Callable[[TTSInfo, Voice, str], None] | None = parameter_type_map.get(_key)
                if parameter_type:
                    parameter_type(tmp_ttsinfo, tmp_voice, _value)

            tmp_ttsinfo.voice = tmp_voice
            if tmp_ttsinfo.supported_lang and not tmp_ttsinfo.engine:
                logger.warning(
                    "Engine is not set for CAST entry (lang='%s'); this entry may be ignored downstream.",
                    tmp_ttsinfo.supported_lang,
                )
            if tmp_ttsinfo.supported_lang:
                voice_parameter[tmp_ttsinfo.supported_lang] = tmp_ttsinfo

        return voice_parameter

    def _set_lang(self, tts_info: TTSInfo, voice: Voice, value: str) -> None:
        """Set the language code in TTSInfo."""
        _: Voice = voice  # Unused parameter
        if not value:
            msg = "Language code is empty"
            raise ConfigValueError(msg)
        tts_info.supported_lang = value.lower()

    def _set_engine(self, tts_info: TTSInfo, voice: Voice, value: str) -> None:
        """Set the TTS engine name in TTSInfo."""
        _: Voice = voice  # Unused parameter
        if not value:
            msg = "Engine name is empty"
            raise ConfigValueError(msg)
        tts_info.engine = value

    def _set_cast(self, tts_info: TTSInfo, voice: Voice, value: str) -> None:
        """Set the voice cast name in Voice."""
        _: TTSInfo = tts_info  # Unused parameter
        if not value:
            msg = "Cast name is empty"
            raise ConfigValueError(msg)
        voice.cast = value

    def _set_param(self, tts_info: TTSInfo, voice: Voice, value: str) -> None:
        """Parse and set voice parameters (volume, speed, tone, alpha, intonation) in Voice."""
        _: TTSInfo = tts_info  # Unused parameter

        def check_param_sub(param: str) -> tuple[str, int]:
            param = param.strip().lower()
            if len(param) < 2:
                msg: str = f"Invalid parameter format: '{param}'"
                raise ConfigValueError(msg)

            _typ, _val = param[0], param[1:]
            if _typ not in ("a", "i", "s", "t", "v"):
                msg: str = f"Unknown parameter type: '{_typ}' in '{param}'"
                raise ConfigValueError(msg)

            try:
                num_val: int = int(_val) if _val.isdigit() else int(float(_val) * 100)
            except ValueError as err:
                logger.error("Failed to parse parameter value: %s.", err)
                msg: str = f"Invalid parameter value: {err}"
                raise ConfigValueError(msg) from None
            else:
                return _typ, num_val

        for item in value.split(","):
            if not item.strip():
                continue
            _typ, _val = check_param_sub(item)
            setattr(
                voice,
                {"a": "alpha", "i": "intonation", "s": "speed", "t": "tone", "v": "volume"}.get(_typ, ""),
                _val,
            )

    def _validate_settings(self) -> None:
        """Validate configuration settings for usernames, translation engines, and colors.

        Raises:
            ConfigFormatError: If validation fails for any setting.
        """
        try:
            self._validate_username("TWITCH", "OWNER_NAME")
            self._validate_username("BOT", "BOT_NAME")
            self._inspect_defined_item("TRANSLATION", "ENGINE", ALLOWED_TRANSLATION_ENGINES)
            self._validate_color_setting("BOT", "COLOR")
        except (NameError, SyntaxError, AttributeError, TypeError, ValueError) as err:
            msg: str = f"Invalid configuration value: {err}"
            raise ConfigFormatError(msg) from None

    def _validate_username(self, section_name: str, key_name: str) -> None:
        """Validate username against Twitch requirements (4-25 chars, alphanumeric + underscore).

        Logs a warning if the username is not lowercase.
        """
        value: str = getattr(getattr(self.config, section_name), key_name)
        field_name: str = f"{section_name}.{key_name}"

        if not re.match(r"^[a-zA-Z0-9_]{4,25}$", value):
            msg: str = f"'{field_name}' contains invalid characters. Only alphanumeric and underscores are allowed."
            raise ConfigFormatError(msg)
        if not value.islower():
            logger.warning("The value for '%s' should be all lowercase.", field_name)

    def _inspect_defined_item(self, section_name: str, key_name: str, defined_list: list[str]) -> None:
        """Verify that configuration values match allowed options.

        Logs warnings for unrecognized values but does not raise exceptions.

        Args:
            section_name (str): Section name in the config model.
            key_name (str): Field name to inspect.
            defined_list (list[str]): Allowed values.

        Raises:
            ConfigTypeError: If the configured value is neither list nor str.
        """
        value: str | list[str] = getattr(getattr(self.config, section_name), key_name)
        field_name: str = f"{section_name}.{key_name}"

        if isinstance(value, (list, str)):
            values: list[str] = value if isinstance(value, list) else [value]
            if any(val not in defined_list for val in values):
                for val in values:
                    if val not in defined_list:
                        logger.warning("Unknown value '%s' is set for '%s'", val, field_name)
        else:
            msg: str = f"Unsupported type used for '{field_name}': {type(value)}"
            raise ConfigTypeError(msg)

    def _validate_color_setting(self, section_name: str, key_name: str) -> None:
        """Validate color setting and convert chat command colors to API format.

        Raises:
            ConfigValueError: If the color is not recognized.
        """
        value: str = getattr(getattr(self.config, section_name), key_name)
        field_name: str = f"{section_name}.{key_name}"

        chat_to_api_color_map: dict[str, str] = {
            chat.lower(): api for chat, api in zip(CHAT_COMMAND_COLORS, API_COLORS, strict=False)
        }

        if value.lower() in (api.lower() for api in CHAT_COMMAND_COLORS):
            new_value: str = chat_to_api_color_map[value.lower()]
            logger.info(
                "'%s' is set to '%s', which is a chat command color. "
                "It has been changed to '%s' for API compatibility.",
                field_name,
                value,
                new_value,
            )
            setattr(getattr(self.config, section_name), key_name, new_value)
        elif value.lower() in (api.lower() for api in API_COLORS):
            pass
        else:
            msg: str = f"Unsupported color code used for '{field_name}': {value}"
            raise ConfigValueError(msg)


class _ConfigFormatter:
    """Converts INI string values to typed Python objects (bool, int, float, list, dict)."""

    def __init__(self, config: Config, parser: ConfigParser) -> None:
        self.config: Config = config
        self.parser: ConfigParser = parser

    def apply_format(self, section: DataclassField[Any], key: DataclassField[Any]) -> Any:
        """Convert INI value to the expected Python type based on the Config field type.

        Args:
            section (DataclassField[Any]): Configuration section field containing the key.
            key (DataclassField[Any]): Target field within the section.

        Returns:
            Any: Parsed value coerced to the type declared in the config dataclass.

        Raises:
            ConfigValueError: If a value cannot be coerced to the expected type.
            ConfigFormatError: If literal evaluation fails due to invalid syntax.
            ConfigTypeError: If an unexpected type is encountered during coercion.
        """
        formatters: dict[
            type[bool | int | float], Callable[[DataclassField[Any], DataclassField[Any]], bool | int | float]
        ] = {
            bool: self.parse_as_boolean,
            int: self.parse_as_integer,
            float: self.parse_as_float,
        }

        formatter: Callable[[DataclassField[Any], DataclassField[Any]], bool | int | float] | None = formatters.get(
            type(getattr(getattr(self.config, section.name), key.name))
        )
        if formatter:
            try:
                return formatter(section, key)
            except ValueError as err:
                msg = f"Invalid value for {section.name}.{key.name}: {err}"
                raise ConfigValueError(msg) from err
            except TypeError as err:
                msg = f"Invalid value for {section.name}.{key.name}: {err}"
                raise ConfigTypeError(msg) from err

        value_str: str = self.parser[section.name][key.name]
        try:
            return ast.literal_eval(value_str)
        except ValueError as err:
            msg = f"Invalid literal for {section.name}.{key.name}: {value_str}"
            raise ConfigValueError(msg) from err
        except SyntaxError as err:
            msg = f"Invalid literal for {section.name}.{key.name}: {value_str}"
            raise ConfigFormatError(msg) from err

    def parse_as_float(self, section: DataclassField[Any], key: DataclassField[Any]) -> float:
        """Convert INI string to float."""
        value: str = self.parser.get(section.name, key.name)
        for char in ("'", '"', "%"):
            value = value.removeprefix(char).removesuffix(char)
        return float(value)

    def parse_as_integer(self, section: DataclassField[Any], key: DataclassField[Any]) -> int:
        """Convert INI string to integer."""
        value: str = self.parser.get(section.name, key.name)
        for char in ("'", '"', "%"):
            value = value.removeprefix(char).removesuffix(char)
        return int(float(value))

    def parse_as_boolean(self, section: DataclassField[Any], key: DataclassField[Any]) -> bool:
        """Convert INI string to boolean."""
        return self.parser.getboolean(section.name, key.name)


if __name__ == "__main__":
    import pprint

    test = ConfigLoader(config_filename="twitchbot.ini", script_name="TEST")
    pp = pprint.PrettyPrinter(indent=1, width=100)
    pp.pprint(test.config)

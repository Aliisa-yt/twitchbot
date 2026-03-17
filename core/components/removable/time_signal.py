"""Time Signal Processing

Generate scheduled events using the routines class of TwitchIO.
The event is executed at regular intervals, and the next execution time is set after each execution.
The time signal can be configured to output text to the console or to output speech using TTS.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, ClassVar, Final

from twitchio.ext import routines

from core.components.base import ComponentBase
from models.voice_models import TTSParam
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging

    from models.config_models import TimeSignal

__all__: list[str] = ["TimeSignalManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)

DEBUG: Final[bool] = False  # Set to True to enable time announcements every 10 minutes for testing purposes.


class TimeSignalManager(ComponentBase):
    """Time Announcement Processing Class

    This class handles time announcement events, such as announcing the current time.
    Use the routine class to schedule events at regular intervals.

    Attributes:
        depends (ClassVar[list[str]]): A list of component names that this component depends on.

    Internal Attributes:
        _time_signal (TimeSignal | None): The time signal configuration object.
        _language (str): The language for time announcements.
        _clock12 (bool): Whether to use 12-hour format.
        _morning (str): The announcement for morning time.
        _afternoon (str): The announcement for afternoon time.
        _evening (str): The announcement for evening time.
        _night (str): The announcement for night time.
        _time_announcement (str): The announcement format for non-12-hour mode.
        _is_text (bool): Whether to output text to the console.
        _is_voice (bool): Whether to output speech.
    """

    depends: ClassVar[list[str]] = ["TTSServiceComponent"]

    async def component_load(self) -> None:
        """Load the component and initialize resources."""
        if not self._configure_time_signal():
            return
        self.event_time_signal.start()
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        """Teardown the component and release resources."""
        self.event_time_signal.cancel()
        logger.debug("'%s' component unloaded", self.__class__.__name__)

    def _configure_time_signal(self) -> bool:
        """Configure the time signal settings from the configuration.

        Retrieves the necessary settings from the configuration and validates them.

        Returns:
            bool: True if the configuration is valid and the time signal is enabled, False otherwise.
        """
        self._time_signal: TimeSignal | None = getattr(self.config, "TIME_SIGNAL", None)
        if self._time_signal is None:
            logger.warning("TIME_SIGNAL configuration is missing.")
            return False

        enabled: bool = getattr(self._time_signal, "ENABLED", False)
        if not isinstance(enabled, bool) or not enabled:
            logger.info("TIME_SIGNAL is disabled in the configuration.")
            return False

        self._language: str = getattr(self._time_signal, "LANGUAGE", self.config.TRANSLATION.NATIVE_LANGUAGE)
        if self._language == "" or not isinstance(self._language, str):
            logger.warning("Invalid LANGUAGE value in TIME_SIGNAL config; defaulting to TRANSLATION.NATIVE_LANGUAGE")
            self._language = self.config.TRANSLATION.NATIVE_LANGUAGE

        self._clock12: bool = getattr(self.config.TIME_SIGNAL, "CLOCK12", True)
        if not isinstance(self._clock12, bool):
            logger.warning("Invalid CLOCK12 value in TIME_SIGNAL config; defaulting to True")
            self._clock12 = True

        # Although defining 24 slots per time period would allow for greater flexibility, we have determined
        # that the current eight-slot system is sufficient.
        self._early_morning: str = ""
        self._morning: str = ""
        self._late_morning: str = ""
        self._afternoon: str = ""
        self._late_afternoon: str = ""
        self._evening: str = ""
        self._night: str = ""
        self._late_night: str = ""

        self._time_announcement: str = ""
        self._time_slots: list[tuple[int, int, str, int]] = []

        if self._clock12:
            self._early_morning = self._get_attribute("EARLY_MORNING")
            self._morning = self._get_attribute("MORNING")
            self._late_morning = self._get_attribute("LATE_MORNING")
            self._afternoon = self._get_attribute("AFTERNOON")
            self._late_afternoon = self._get_attribute("LATE_AFTERNOON")
            self._evening = self._get_attribute("EVENING")
            self._night = self._get_attribute("NIGHT")
            self._late_night = self._get_attribute("LATE_NIGHT")
            if "" in (
                self._early_morning,
                self._morning,
                self._late_morning,
                self._afternoon,
                self._late_afternoon,
                self._evening,
                self._night,
                self._late_night,
            ):
                return False

            # Although defining 24 slots per time period would allow for greater flexibility, we have determined
            # that the current eight-slot system is sufficient.
            self._time_slots = [
                (0, 4, self._late_night, 0),
                (4, 6, self._early_morning, 0),
                (6, 10, self._morning, 0),
                (10, 12, self._late_morning, 0),
                (12, 15, self._afternoon, -12),
                (15, 18, self._late_afternoon, -12),
                (18, 20, self._evening, -12),
                (20, 24, self._night, -12),
            ]
        else:
            self._time_announcement = self._get_attribute("TIME_ANNOUNCEMENT")
            if self._time_announcement == "":
                return False

        self._is_text: bool = getattr(self.config.TIME_SIGNAL, "TEXT", False)
        if not isinstance(self._is_text, bool):
            self._is_text = False
            logger.warning("Invalid TEXT value in TIME_SIGNAL config; defaulting to False")

        self._is_voice: bool = getattr(self.config.TIME_SIGNAL, "VOICE", False)
        if not isinstance(self._is_voice, bool):
            self._is_voice = False
            logger.warning("Invalid VOICE value in TIME_SIGNAL config; defaulting to False")

        return True

    def _get_attribute(self, name: str) -> str:
        """Helper method to retrieve attributes from the TIME_SIGNAL configuration."""
        value = getattr(self.config.TIME_SIGNAL, name, "")
        if value == "" or not isinstance(value, str):
            logger.warning("TIME_SIGNAL configuration is missing or invalid for '%s'.", name)
            return ""
        return value

    @routines.routine(delta=timedelta(seconds=10), iterations=1, wait_first=True)
    async def event_time_signal(self) -> None:
        """Event executed at regular intervals.

        Retrieves the current time and performs
        console output or speech output according to the settings.
        """
        _tim: datetime = datetime.now().astimezone()
        _hour: int = _tim.hour
        _minute: int = _tim.minute
        logger.debug(
            "event_timesignal: %04d-%02d-%02d %02d:%02d:%02d",
            _tim.year,
            _tim.month,
            _tim.day,
            _tim.hour,
            _tim.minute,
            _tim.second,
        )

        _time_word: str = ""
        if DEBUG or _minute == 0:
            if self._clock12:
                for start, end, msg, hour_adj in self._time_slots:
                    if start <= _hour < end:
                        _time_word = msg
                        if hour_adj != 0:
                            _hour += hour_adj
                        break
                else:
                    logger.warning("Current hour %d does not fit into any defined time slot.", _hour)
                    return
                # In Japan, the expressions `午後0時` and `午前0時` are used to refer to `noon` and `midnight`,
                # so the number 0 is not converted to 12.
                if self._language != "ja" and _hour == 0:
                    _hour = 12
            else:
                # No distinction is made when using the 24-hour clock.
                _time_word = self._time_announcement

            _time_word = _time_word.replace("{hour}", str(_hour))

            if self._is_text:
                self.print_console_message(_time_word)
            if self._is_voice:
                tts_param = TTSParam(
                    content=_time_word,
                    content_lang=self._language,
                    tts_info=self.tts_manager.get_voice_param(self._language, is_system=True),
                )
                await self.store_tts_queue(tts_param)

    @event_time_signal.after_routine
    async def event_next_time(self) -> None:
        """Set the next event occurrence time.

        Sets the next execution time calculated by the `next_time` method.
        """
        _tim: datetime = self.next_time()
        self.event_time_signal.change_interval(time=_tim)
        logger.debug(
            "next time: %04d-%02d-%02d %02d:%02d:%02d",
            _tim.year,
            _tim.month,
            _tim.day,
            _tim.hour,
            _tim.minute,
            _tim.second,
        )

    def next_time(self) -> datetime:
        """Calculate the next event occurrence time.

        Rounds the current time to the nearest 10 minutes and determines the next timing.
        For example, if it is 14:23, the next time will be 14:30.

        Returns:
            datetime: The next event occurrence time.
        """
        now: datetime = datetime.now().astimezone()
        next_minute: int = (now.minute // 10 + 1) * 10
        if next_minute >= 60:  # Example: 23:50 → 0:00
            return (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        return now.replace(minute=next_minute, second=0, microsecond=0)

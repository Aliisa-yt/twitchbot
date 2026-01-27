"""Time Signal Processing

Generate scheduled events using the routines class of TwitchIO.
Currently, there are many items that cannot be changed from the config due to provisional specifications.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from twitchio.ext import routines

from core.components.base import Base
from models.voice_models import TTSParam
from utils.logger_utils import LoggerUtils

if TYPE_CHECKING:
    import logging


__all__: list[str] = ["TimeSignalManager"]

logger: logging.Logger = LoggerUtils.get_logger(__name__)


class TimeSignalManager(Base):
    """Time Announcement Processing Class

    This class handles time announcement events, such as announcing the current time.
    Use the routine class to schedule events at regular intervals.

    Attributes:
        event_time_signal (routines.Routine): Scheduled event for time announcements.
    """

    async def async_init(self) -> None:
        """Asynchronous initialization method.
        Starts the event routine.
        """
        self.event_time_signal.start()

    async def close(self) -> None:
        """Perform cleanup and stop the event."""
        self.event_time_signal.cancel()
        logger.debug("'%s' process termination", self.__class__.__name__)

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

        _start_word: str = ""
        if self.config.TIME_SIGNAL.CLOCK12:
            if _hour < 12:
                _start_word = self.config.TIME_SIGNAL.AM_NAME
            else:
                _start_word = self.config.TIME_SIGNAL.PM_NAME
                _hour = _hour - 12

        _end_word: str = random.choice(["です", "になりました"])  # noqa: S311

        if _minute == 0:
            text: str = f"{_start_word}{_hour}時{_end_word}"

            if self.config.TIME_SIGNAL.TEXT:
                self.print_console_message(text)
            if self.config.TIME_SIGNAL.VOICE:
                tts_param = TTSParam(
                    content=text,
                    content_lang="ja",
                    tts_info=self.tts_manager.voice_parameters.system["ja"],
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

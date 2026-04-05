from __future__ import annotations

from datetime import UTC, datetime, timedelta

__all__: list[str] = ["TimeUtils"]


class TimeUtils:
    """Utility class for time-related operations."""

    @staticmethod
    def get_time_in_hours_minutes() -> str:
        """Get the current time formatted as HH:MM.

        Returns:
            str: The current time in HH:MM format.
        """
        return datetime.now(tz=UTC).astimezone().strftime("%H:%M")

    @staticmethod
    def get_current_epoch() -> int:
        """Get the current time as an epoch timestamp.

        Returns:
            int: The current time as an epoch timestamp.
        """
        return int(datetime.now().astimezone().timestamp())

    @staticmethod
    def epoch_to_datetime(value: int | str) -> datetime:
        """Convert an epoch timestamp to a timezone-aware datetime object.

        Args:
            value (int | str): The epoch timestamp to convert. Can be an integer or a string representing an integer.

        Returns:
            datetime: A timezone-aware datetime object representing the given epoch timestamp.
        """
        return datetime.fromtimestamp(int(value), tz=UTC).astimezone()

    @staticmethod
    def cutoff_epoch(days: float) -> int:
        """Calculate cutoff epoch seconds based on current time minus specified days.

        Args:
            days (float): Number of days to subtract from now.

        Returns:
            int: Cutoff as epoch seconds (UTC-based).
        """
        return TimeUtils.get_current_epoch() - int(days * 86400)

    @staticmethod
    def cutoff_datetime(days: float) -> datetime:
        """Calculate a cutoff datetime based on the current time minus a specified number of days.

        Args:
            days (float): The number of days to subtract from the current time to calculate the cutoff.

        Returns:
            datetime: A timezone-aware datetime object representing the cutoff time.
        """
        return datetime.now().astimezone() - timedelta(days=days)

    @staticmethod
    def get_iso8601_current_time(*, with_timezone: bool = True) -> str:
        """Get the current time formatted as an ISO 8601 string.

        According to TwitchIO specifications, the format must not include the timezone.

        Args:
            with_timezone (bool): Whether to include timezone information.

        Returns:
            str: The current time in ISO 8601 format.
        """
        if with_timezone:
            return datetime.now().astimezone().isoformat()
        return datetime.now().isoformat()  # noqa: DTZ005

    @staticmethod
    def convert_epoch_to_iso8601(time: float, *, with_timezone: bool = True) -> str:
        """Convert a given epoch time to an ISO 8601 formatted string.

        Args:
            time (float): The epoch time to convert.
            with_timezone (bool): Whether to include timezone information in the output.

        Returns:
            str: The given epoch time formatted as an ISO 8601 string.

        Raises:
            ValueError: If the provided time cannot be converted to a float.
        """
        try:
            time = float(time)
        except (TypeError, ValueError) as err:
            msg: str = f"Invalid epoch time: {time}"
            raise ValueError(msg) from err

        dt: datetime = datetime.fromtimestamp(time, tz=UTC).astimezone()
        if with_timezone:
            return dt.isoformat()
        return dt.replace(tzinfo=None).isoformat()  # noqa: DTZ005

    @staticmethod
    def convert_iso8601_to_epoch(time_str: str) -> float:
        """Convert an ISO 8601 formatted string to an epoch timestamp.

        Args:
            time_str (str): The ISO 8601 formatted string to convert.

        Returns:
            float: The corresponding epoch timestamp.
        """
        dt: datetime = datetime.fromisoformat(time_str)
        return dt.timestamp()

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

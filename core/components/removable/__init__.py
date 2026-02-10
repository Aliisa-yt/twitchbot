"""Removable components for temporary functionalities.

This package contains components that can be added or removed from the bot
dynamically, providing temporary functionalities such as time-based signals.

Modules:
- time_signal: Manages time-based signals and events
"""

from core.components.removable.time_signal import TimeSignalManager

__all__: list[str] = [
    "TimeSignalManager",
]

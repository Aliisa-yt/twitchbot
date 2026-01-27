"""Bot components for event handling and command processing.

This package contains the core bot components that handle chat events, commands,
time signals, and other bot behaviors.
"""

from core.components.base import Base
from core.components.chat_events import ChatEventsCog
from core.components.command import Command
from core.components.time_signal import TimeSignalManager

__all__: list[str] = ["Base", "ChatEventsCog", "Command", "TimeSignalManager"]

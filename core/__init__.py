"""Core bot components and managers for Twitchbot.

This package contains the main bot class, shared data management, token management,
components, and utilities for translation and text-to-speech functionality.
"""

from core.bot import Bot
from core.shared_data import SharedData
from core.token_manager import TokenManager, TwitchBotToken
from core.version import VERSION

__all__: list[str] = [
    "VERSION",
    "Bot",
    "SharedData",
    "TokenManager",
    "TwitchBotToken",
]

"""Bot components for event handling and command processing.

This package contains the core bot components that handle chat events, commands, and
integrate with external services like translation and text-to-speech.

Modules:
- base: Base class for all components
- cache_component: Translation cache service integration
- chat_events: Manages chat event handling
- command: Command processing and management
- trans_component: Translation service integration
- tts_component: Text-to-speech service integration
"""

from core.components.base import ComponentBase, ComponentDescriptor
from core.components.cache_component import CacheServiceComponent
from core.components.chat_events import ChatEventsManager
from core.components.command import BotCommandManager
from core.components.trans_component import TranslationServiceComponent
from core.components.tts_component import TTSServiceComponent

__all__: list[str] = [
    "BotCommandManager",
    "CacheServiceComponent",
    "ChatEventsManager",
    "ComponentBase",
    "ComponentDescriptor",
    "TTSServiceComponent",
    "TranslationServiceComponent",
]

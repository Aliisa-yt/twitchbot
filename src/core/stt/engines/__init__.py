"""STT engine implementations."""

from __future__ import annotations

from core.stt.engines.google_cloud_speech_to_text import GoogleCloudSpeechToText
from core.stt.engines.google_cloud_speech_to_text_v2 import GoogleCloudSpeechToTextV2

__all__: list[str] = ["GoogleCloudSpeechToText", "GoogleCloudSpeechToTextV2"]

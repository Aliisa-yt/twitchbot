# Twitchbot Project Structure

This document provides an English overview of the current Twitchbot Python source layout (excluding `__init__.py`). It is intended for onboarding, navigation, and quick impact assessment when editing the codebase.

**Date**: 2026-03-10  
**Version**: 1.5.0

---

## Project Tree (current)

```

├── setup_tokens.py                   # Token setup utility
├── twitchbot.py                      # Entry point
├── config/
│   └── loader.py                     # INI loader/validator
├── core/
│   ├── bot.py                        # TwitchIO bot implementation
│   ├── shared_data.py                # Shared managers wiring
│   ├── token_manager.py              # OAuth token flow
│   ├── token_storage.py              # SQLite3-based token storage
│   ├── version.py                    # Version constant
│   ├── components/
│   │   ├── base.py                   # Component base class
│   │   ├── cache_component.py        # Cache manager component wiring
│   │   ├── chat_events.py            # Chat event handling
│   │   ├── command.py                # Chat commands
│   │   ├── inflight_component.py     # In-flight deduplication component
│   │   ├── stt_component.py          # STT service component
│   │   ├── trans_component.py        # Translation service component
│   │   ├── tts_component.py          # TTS service component
│   │   └── removable/
│   │       └── time_signal.py        # Hourly time signal (optional/removable)
│   ├── cache/
│   │   ├── inflight_manager.py       # In-flight request manager
│   │   └── manager.py                # Persistent cache manager
│   ├── gui/
│   │   ├── gui_app.py                # Tkinter GUI (core side)
│   │   └── gui_logging_handler.py    # GUI log sink/handler
│   ├── stt/
│   │   ├── interface.py              # STT interface + registry
│   │   ├── manager.py                # STT manager
│   │   ├── processor.py              # STT segment processing pipeline
│   │   ├── recorder.py               # Audio capture and segmenting
│   │   ├── stt_location_model_loader.py # STT locale/model helper
│   │   └── engines/
│   │       ├── google_cloud_speech_to_text.py
│   │       └── google_cloud_speech_to_text_v2.py
│   ├── trans/
│   │   ├── interface.py              # Translation interface + registry
│   │   ├── manager.py                # Translation manager
│   │   └── engines/
│   │       ├── async_google_translate.py
│   │       ├── const_google.py
│   │       ├── trans_deepl.py
│   │       ├── trans_google.py
│   │       └── trans_google_cloud.py
│   └── tts/
│       ├── audio_playback_manager.py # Audio playback
│       ├── file_manager.py           # TTS temporary file handling
│       ├── interface.py              # TTS interface + registry
│       ├── manager.py                # TTS manager
│       ├── parameter_manager.py      # Voice parameter selection
│       ├── synthesis_manager.py      # Synthesis orchestration
│       └── engines/
│           ├── bouyomichan.py
│           ├── cevio_ai.py
│           ├── cevio_core.py
│           ├── cevio_cs7.py
│           ├── coeiroink.py
│           ├── coeiroink_v2.py
│           ├── g_tts.py
│           ├── voicevox.py
│           └── vv_core.py
├── handlers/
│   ├── async_comm.py                 # Async HTTP/socket utils
│   ├── chat_message.py               # Chat message wrapper
│   ├── emoji.py                      # Emoji processing
│   ├── fragment_handler.py           # Message fragments / emote helpers
│   ├── katakana.py                   # Romaji/English → Katakana
│   └── message_formatter.py          # Chat/TTS formatting
├── models/
│   ├── coeiroink_v2_models.py
│   ├── cache_models.py
│   ├── config_models.py
│   ├── message_models.py
│   ├── re_models.py
│   ├── translation_models.py
│   ├── voice_models.py
│   └── voicevox_models.py
└── utils/
    ├── cache_utils.py
    ├── chat_utils.py
    ├── excludable_queue.py
    ├── file_utils.py
    ├── logger_utils.py
    ├── string_utils.py
    ├── time_utils.py
    └── tts_utils.py
```

---

## Directory and File Highlights

### Root
- `setup_tokens.py`: Console-only token setup utility; performs OAuth flow and stores tokens in `tokens.db`.
- `twitchbot.py`: Main entrypoint — version check (3.13+), logging setup, config load, CLI args (`--owner`, `--bot`, `--debug`), temp dir creation, dictionary load, OAuth flow, and bot lifecycle.

### config
- `loader.py`: Parses and validates `twitchbot.ini`; coerces types; validates usernames/colors; builds voice parameters; supports CLI overrides.

### core
- `bot.py`: TwitchIO bot; EventSub subscriptions; component lifecycle; chat/console output limits; graceful shutdown; TwitchIO logger wiring.
- `shared_data.py`: Wires `TransManager`, `TTSManager`, `STTManager`, and cache managers for components.
- `token_manager.py`: Browser-based OAuth flow, token refresh, ID resolution via TokenStorage backend.
- `token_storage.py`: SQLite3-based persistent storage for tokens; handles save/load/delete/expiration checks with atomic transactions.
- `version.py`: Version constant.

#### core/components
- `base.py`: Component base class with dependency-aware registration and lifecycle hooks.
- `cache_component.py`: Injects cache manager dependencies into shared runtime.
- `chat_events.py`: Receives chat events; ignore lists; translation + TTS pipeline; message formatting.
- `command.py`: Chat commands (`!tskip`, `!tclear`, `!tversion`, `!tengine`, `!tusage`) with permission checks.
- `inflight_component.py`: In-flight deduplication manager integration for translation requests.
- `stt_component.py`: STT initialization, callback wiring, and safe teardown.
- `trans_component.py`: Translation manager initialization and lifecycle management.
- `tts_component.py`: TTS manager initialization and lifecycle management.
- `removable/time_signal.py`: Scheduled time signal (text/TTS), 12/24h, AM/PM labels, routines-based scheduling.

#### core/cache
- `manager.py`: Translation/language detection cache storage and lookup.
- `inflight_manager.py`: Prevents duplicated concurrent translation work for same input.

#### core/gui
- `gui_app.py`: Tkinter GUI app integrating asyncio with a live log console.
- `gui_logging_handler.py`: Logging handler that writes formatted records to the GUI text widget.

#### core/stt
- `interface.py`: STT interface, registration logic, and STT-specific exceptions.
- `manager.py`: STT orchestration, initialization, and close/recovery flow.
- `processor.py`: Segment-level recognition processing and result normalization.
- `recorder.py`: Audio device capture, threshold-based segmenting, and reconnect handling.
- `stt_location_model_loader.py`: Locale/model mapping helper for STT providers.
- Engines: `google_cloud_speech_to_text.py`, `google_cloud_speech_to_text_v2.py`.

#### core/trans
- `interface.py`: Translation interface, registration decorator, result/attribute models, custom exceptions.
- `manager.py`: Engine initialization/selection, forced-language parsing, detection, translation, quota queries, active-engine refresh.
- Engines: `async_google_translate.py`, `const_google.py`, `trans_google.py`, `trans_deepl.py`, `trans_google_cloud.py` (Google/DeepL/Google Cloud support).

#### core/tts
- `interface.py`: TTS interface, engine registry, audio save path, process helpers.
- `manager.py`: Orchestrates synthesis/playback queues, background tasks, graceful shutdown.
- `parameter_manager.py`: Voice parameter lookup per user type/language; tweak commands.
- `synthesis_manager.py`: Prepares TTS content, enqueues synthesis, bridges to playback.
- `audio_playback_manager.py`: Plays audio files, cleans up after playback.
- `file_manager.py`: Temporary audio file creation/removal and path safety handling.
- Engines: `bouyomichan.py`, `cevio_ai.py`, `cevio_cs7.py`, `cevio_core.py`, `coeiroink.py`, `coeiroink_v2.py`, `g_tts.py`, `voicevox.py`, `vv_core.py`.

### handlers
- `async_comm.py`: Async HTTP/socket helpers (aiohttp + sockets); JSON parsing; timeouts.
- `chat_message.py`: Wrapper/accessors for TwitchIO messages; emote/mention metadata.
- `emoji.py`: Emoji detection and naming.
- `fragment_handler.py`: Fragment-based parsing utilities and emote helpers.
- `katakana.py`: Romaji/English to katakana conversion (dictionaries + heuristics).
- `message_formatter.py`: Template-based formatting for chat/TTS output.

### models
- `coeiroink_v2_models.py`: Coeiroink v2 API models and response structures.
- `cache_models.py`: Cache entry models and key/value representations.
- `config_models.py`: Config dataclasses (General, Twitch, Bot, Translation, TTS, etc.).
- `message_models.py`: Chat message structures, TTS params, translation info.
- `re_models.py`: Regex patterns for IRC/commands/URLs/language hints.
- `translation_models.py`: Translation info and quota models.
- `voice_models.py`: Voice/TTS parameter models and user-type mappings.
- `voicevox_models.py`: VOICEVOX API models and response structures.

### utils
- `cache_utils.py`: Cache key helpers and cache-related utility functions.
- `chat_utils.py`: Chat helpers (ignore rules, truncation, footer generation).
- `excludable_queue.py`: Async queue with exclusion/shutdown controls.
- `file_utils.py`: Safe file removal and path resolution.
- `logger_utils.py`: Central logging setup and logger retrieval.
- `string_utils.py`: String sanitation, blank compression, IRC decoding.
- `time_utils.py`: Time/date helper functions used by scheduling and messaging logic.
- `tts_utils.py`: TTS parameter prep and validation.

---

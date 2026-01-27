# Twitchbot Project Structure

This document provides an English overview of the current Twitchbot Python source layout (excluding `__init__.py`). It is intended for onboarding, navigation, and quick impact assessment when editing the codebase.

**Date**: 2026-01-27  
**Version**: 20260127-01

---

## Project Tree (current)

```

├── twitchbot.py                      # Entry point
├── config/
│   └── loader.py                     # INI loader/validator
├── core/
│   ├── bot.py                        # TwitchIO bot implementation
│   ├── shared_data.py                # Shared managers wiring
│   ├── token_manager.py              # OAuth token flow/cache
│   ├── version.py                    # Version constant
│   ├── components/
│   │   ├── base.py                   # Component base class
│   │   ├── chat_events.py            # Chat event handling
│   │   ├── command.py                # Chat commands
│   │   └── time_signal.py            # Hourly time signal
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
│       ├── interface.py              # TTS interface + registry
│       ├── manager.py                # TTS manager
│       ├── parameter_manager.py      # Voice parameter selection
│       ├── synthesis_manager.py      # Synthesis orchestration
│       ├── audio_playback_manager.py # Audio playback
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
│   ├── config_models.py
│   ├── message_models.py
│   ├── re_models.py
│   ├── translation_models.py
│   └── voice_models.py
└── utils/
    ├── chat_utils.py
    ├── excludable_queue.py
    ├── file_utils.py
    ├── logger_utils.py
    ├── string_utils.py
    └── tts_utils.py
```

---

## Directory and File Highlights

### Root
- `twitchbot.py`: Main entrypoint — version check (3.13+), logging setup, config load, CLI args (`--owner`, `--bot`, `--debug`), temp dir creation, dictionary load, OAuth flow, and bot lifecycle.

### config
- `loader.py`: Parses and validates `twitchbot.ini`; coerces types; validates usernames/colors; builds voice parameters; supports CLI overrides.

### core
- `bot.py`: TwitchIO bot; EventSub subscriptions; component lifecycle; chat/console output limits; graceful shutdown; TwitchIO logger wiring.
- `shared_data.py`: Wires `TransManager` and `TTSManager` for components.
- `token_manager.py`: Browser-based OAuth, token refresh/cache, ID resolution, atomic writes.
- `version.py`: Version constant.

#### core/components
- `base.py`: Component base class with shared translation/TTS hooks and lifecycle (`async_init`, `close`).
- `chat_events.py`: Receives chat events; ignore lists; translation + TTS pipeline; message formatting.
- `command.py`: Chat commands (`!tskip`, `!tclear`, `!tversion`, `!tengine`, `!tusage`) with permission checks.
- `time_signal.py`: Scheduled time signal (text/TTS), 12/24h, AM/PM labels, routines-based scheduling.

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
- Engines: `bouyomichan.py`, `cevio_ai.py`, `cevio_cs7.py`, `cevio_core.py`, `coeiroink.py`, `coeiroink_v2.py`, `g_tts.py`, `voicevox.py`, `vv_core.py`.

### handlers
- `async_comm.py`: Async HTTP/socket helpers (aiohttp + sockets); JSON parsing; timeouts.
- `chat_message.py`: Wrapper/accessors for TwitchIO messages; emote/mention metadata.
- `emoji.py`: Emoji detection and naming.
- `fragment_handler.py`: Fragment-based parsing utilities and emote helpers.
- `katakana.py`: Romaji/English to katakana conversion (dictionaries + heuristics).
- `message_formatter.py`: Template-based formatting for chat/TTS output.

### models
- `config_models.py`: Config dataclasses (General, Twitch, Bot, Translation, TTS, etc.).
- `message_models.py`: Chat message structures, TTS params, translation info.
- `re_models.py`: Regex patterns for IRC/commands/URLs/language hints.
- `translation_models.py`: Translation info and quota models.
- `voice_models.py`: Voice/TTS parameter models and user-type mappings.

### utils
- `chat_utils.py`: Chat helpers (ignore rules, truncation, footer generation).
- `excludable_queue.py`: Async queue with exclusion/shutdown controls.
- `file_utils.py`: Safe file removal and path resolution.
- `logger_utils.py`: Central logging setup and logger retrieval.
- `string_utils.py`: String sanitation, blank compression, IRC decoding.
- `tts_utils.py`: TTS parameter prep and validation.

---

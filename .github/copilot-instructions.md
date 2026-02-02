# Copilot Instructions for `twitchbot`

## Architecture overview
**Data flow**: Twitch message → `ChatEventsCog.event_message()` → `ChatMessageHandler` → `TransManager` (detect & translate) → `TTSManager` (synthesize & queue playback) → audio output.

**Component layers**:
- Entry: [twitchbot.py](../twitchbot.py) loads config/dictionaries, OAuth via `TokenManager`, then runs `core.bot.Bot`.
- Bot runtime: [core/bot.py](../core/bot.py) registers three components (`ChatEventsCog`, `Command`, `TimeSignalManager`) via `setup_hook()` and initializes `SharedData`.
- Shared managers: [core/shared_data.py](../core/shared_data.py) provides `TransManager` and `TTSManager` to all components (initialized in `Bot.setup_hook()`).
- **Translation flow**: [core/trans/manager.py](../core/trans/manager.py) → detect language → parse forced prefixes (e.g., `"en:ja:text"`) → determine target → perform translation.
- **TTS flow**: [core/tts/manager.py](../core/tts/manager.py) orchestrates three workers: `ParameterManager` (voice config per user type), `SynthesisManager` (queues → synthesizes via engines), `AudioPlaybackManager` (plays files via queue).
- Queue pattern: `ExcludableQueue` ([utils/excludable_queue.py](../utils/excludable_queue.py)) allows safe concurrent access and graceful shutdown via `shutdown()`.
- Config: [config/loader.py](../config/loader.py) validates INI, coerces types, builds `VOICE_PARAMETERS` dataclass tree (user type → language → voice).

## Critical workflows (Windows)
- **Activate venv first**: `& .\.venv\Scripts\Activate.ps1` before any commands.
- **Run locally**: `set TWITCH_API_CLIENT_ID=<id> && set TWITCH_API_CLIENT_SECRET=<secret> && python .\twitchbot.py [--owner NAME --bot NAME --debug]` (OAuth tokens cached in [tokens.json](../tokens.json)).
- **Build EXE**: `pyinstaller twitchbot.spec --clean` (or use "Build EXE with PyInstaller" task).
- **Tests** (pytest-asyncio): `pytest tests/` (single) or `coverage run -m pytest tests/ -v && coverage report` (full).
- **Lint**: `ruff check . && ruff format . && mypy .` ([pyproject.toml](../pyproject.toml) sets rules).
- **Debug logging**: Add `--debug` flag or set `DEBUG = True` in INI; twitchio logger set to WARNING by default.

## Project conventions
- **Python 3.13 only**; always keep `from __future__ import annotations` at module top.
- **File format**: UTF-8 + LF line endings, line length 120 (ruff enforced).
- **Logging**: Use `logger = LoggerUtils.get_logger(__name__)` once per module; never re-initialize `LoggerUtils`.
- **Exceptions**: Assign error message to `msg` variable before raising (e.g., `msg = "error"; raise ValueError(msg)`).
- **Unused parameters**: Use `_ = arg1, arg2` immediately after docstring to suppress linting.
- **Docstrings**: Google style; place module docstring first, then `from __future__ import annotations`, then imports.
  - Module docstrings: Brief description of the module's purpose.
  - Class docstrings: Brief description of behavior and key attributes.
  - Method docstrings: Brief description of behavior, arguments, return values, and raised exceptions.
  - **Exception**: Trivial methods whose behavior is self-evident from the code may omit docstrings.
  - **CRITICAL**: Compatibility information and bug-workaround details must never be deleted; they may be made concise but must be preserved. This rule takes precedence over all other documentation guidelines.
- **Comments**: All comments (including docstrings and inline comments) must be written in English only. Japanese is strictly prohibited in comments, except when it is necessary to describe argument values, data content, or user-facing text that must be in Japanese for functional reasons (e.g., dictionary entries, kana conversion tables, or when the comment itself is a sample of user input/output in Japanese). Any other use of Japanese in comments is not allowed.
  - **CRITICAL**: Compatibility information and bug-workaround details must never be deleted; they may be made concise but must be preserved. This rule takes precedence over all other comment guidelines.
- **Inline comments**: Only for non-obvious or bug-prone logic; omit obvious code comments.
  - **CRITICAL**: Compatibility information and bug-workaround details must never be deleted; they may be made concise but must be preserved.

## Integration points
- **EventSub webhooks** ([core/bot.py](../core/bot.py)): `Bot._subscribe_to_chat_events()` registers chat message, delete, and clear subscriptions.
- **OAuth flow** ([core/token_manager.py](../core/token_manager.py)): `TokenManager.start_authorization_flow()` handles Twitch login; tokens cached in `tokens.json`.
- **Engine registration**: Translation engines inherit `TransInterface`; TTS engines inherit `Interface`. Auto-register via `@init_subclass()`. Names must match INI `engine` entries.
- **Language detection** ([core/trans/manager.py](../core/trans/manager.py)): Engines with `has_dedicated_detection_api=True` (DeepL) detect-only; others return translated text during detection.
- **User type voice mapping** ([core/tts/parameter_manager.py](../core/tts/parameter_manager.py)): Maps Twitch user badges (STREAMER, MODERATOR, VIP, SUBSCRIBER, OTHERS, SYSTEM) to voice parameters per language.

## Data models (key patterns)
- **TranslationInfo** ([models/translation_models.py](../models/translation_models.py)): Stores content, src/tgt languages, translated text, translation flag.
- **TTSParam** ([models/voice_models.py](../models/voice_models.py)): Carries message, TTS parameters, and output file path through synthesis queue.
- **TTSInfo/UserTypeInfo**: Nested dataclasses organizing voice parameters by user type and language.

## Where to extend
- **New component**: Inherit [core/components/base.py](../core/components/base.py) (`Base`), implement `async_init()` and `close()`, register in [core/bot.py](../core/bot.py) (`Bot.setup_hook()`).
- **New translation engine**: Inherit [core/trans/interface.py](../core/trans/interface.py) (`TransInterface`), implement abstract methods, add INI entry under `[TRANSLATION] engine = <name>`, handle init errors in `initialize()`.
- **New TTS engine**: Inherit [core/tts/interface.py](../core/tts/interface.py) (`Interface`), set `engine_name` class var, implement synthesis method, add INI entry under `[CAST]`.

## Testing patterns
- Use `@pytest.fixture` to create reusable mocks (see [tests/test_bot.py](../tests/test_bot.py)).
- Mark async tests with `@pytest.mark.asyncio` (pytest-asyncio).
- Mock external dependencies with `unittest.mock.AsyncMock`, `MagicMock`, or `patch`.
- Place shared fixtures in conftest.py if used across multiple test files.

## Docs placement
- Analysis/design docs go in [docs/](../docs/); root-level exceptions: `README.md`, `LICENSE`.

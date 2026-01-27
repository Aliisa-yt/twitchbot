# Copilot Instructions for `twitchbot`

These instructions help AI coding agents work productively in this codebase. Focus on concrete, repo-specific practices and workflows.

## Architecture Overview
- Entry point: [twitchbot.py](../twitchbot.py) orchestrates startup: version check (Python 3.13+), logging setup, temp dir creation, dictionary loading, OAuth via `TokenManager`, then runs `core.bot.Bot`.
 - Bot runtime: [core/bot.py](../core/bot.py) extends `twitchio.ext.commands.Bot`. In `setup_hook()`, it initialises `SharedData` and adds components: `ChatEventsCog`, `Command`, `TimeSignalManager`.
- Shared managers: [core/shared_data.py](../core/shared_data.py) wires `TransManager` and `TTSManager` for use across components.
- Translation: [core/trans/manager.py](../core/trans/manager.py) selects engines (`google`, `deepl`, `google_cloud`) from config, performs forced-language parsing, detection, translation, usage quota.
- TTS: [core/tts/manager.py](../core/tts/manager.py) coordinates `ParameterManager` → `SynthesisManager` → `AudioPlaybackManager` with background tasks and `ExcludableQueue` for synthesis/playback. Audio files are saved under `config.GENERAL.TMP_DIR`.
- Config: [config/loader.py](../config/loader.py) converts/validates INI settings, maps chat color names to API colors, builds `VOICE_PARAMETERS` merging defaults and per-user-type, and enforces allowed translation engines.

## Critical Workflows
- Run locally (Windows): ensure `twitchbot.ini` exists; set env vars `TWITCH_API_CLIENT_ID` and `TWITCH_API_CLIENT_SECRET`; then run:
  ```powershell
  $env:TWITCH_API_CLIENT_ID="<client_id>"
  $env:TWITCH_API_CLIENT_SECRET="<client_secret>"
  python .\twitchbot.py [--owner OWNER_NAME] [--bot BOT_NAME]
  ```
  Optional command-line arguments override `twitchbot.ini` settings. First run opens a browser for OAuth and caches tokens to [tokens.json](../tokens.json).
- Build EXE: use VS Code task or run directly:
  ```powershell
  pyinstaller twitchbot.spec --clean
  ```
  The task `Build EXE with PyInstaller` injects venv `Scripts` into `PATH`.
- Tests: pytest with asyncio; network calls are faked via monkeypatch.
  ```powershell
  pytest -q
  ```
- Lint/Type check: configured in [pyproject.toml](../pyproject.toml).
  ```powershell
  ruff check .
  ruff format .
  mypy .
  ```

## Project Conventions & Patterns
- **File encoding and line endings**: All source code files must use UTF-8 encoding with LF (Unix-style) line endings. Do not use CRLF or other encodings. Configure your editor to enforce this (e.g., VS Code: `"files.encoding": "utf8"` and `"files.eol": "\n"`).
- Python version: built for Python 3.13; currently constrained to 3.13 due to library compatibility. Version check is enforced in [twitchbot.py](../twitchbot.py).
- **Type hints**: Always add type hints to method/function return types and local variables where possible. Use `from __future__ import annotations` to support forward references. Examples: `def get_name(self) -> str:`, `config: Config = Config()`, `result: Result = await engine.translate(...)`. Use `TYPE_CHECKING` blocks for imports needed only for type hints to avoid circular imports. This aids mypy type checking and code clarity.
- Typing/circular imports: keep `from __future__ import annotations` in modules. On Python 3.13 this project still relies on it to avoid circular import issues across packages.
- Logging: use `LoggerUtils.get_logger(__name__)`. File logs go to `debug.log` via rotating handler; TwitchIO logs are re-routed to share handlers (`_setup_twitchio_logger`). Do not re-initialize `LoggerUtils` after configured.
- Async tasks: background tasks are created with names (e.g., `"TTS_processing_task"`); graceful shutdown via `asyncio.Event` + `ExcludableQueue.shutdown()` and `TTSManager.close()`.
- Message output: chat messages trimmed to ~450 bytes via `ChatUtils.truncate_message`; console output trimmed to ~80 characters with byte-length heuristics.
- Translation flow: `TransManager.parse_language_prefix()` parses language prefixes; `detect_language()` sets `src_lang`; `determine_target_language()` chooses `tgt_lang` based on `NATIVE_LANGUAGE`, `SECOND_LANGUAGE`, and ignores.
- TTS flow: `ParameterManager.select_voice_usertype()` picks voice by user type; `prepare_tts_content()` normalises text; synthesis enqueues to playback via `Interface.play_callback`.
- Config rules: `ConfigLoader` reads `twitchbot.ini`, auto-converts types, validates Twitch usernames, maps chat color names to API colors, and builds `VOICE_PARAMETERS` per language/user type.
- **Exception raising**: When raising exceptions, always assign the error message to a variable first before passing it to the exception. This improves code clarity and aids debugging.
  ```python
  # Good: Assign message to variable first
  msg: str = "Invalid configuration value"
  raise ValueError(msg)
  
  # Avoid: Inline message
  raise ValueError("Invalid configuration value")
  ```
- **Unused function arguments**: Mark unused function or method arguments with `_ = arg1, arg2, ...` on the first line of code (immediately after docstrings/comments). This signals intent to lint tools like Ruff and improves code clarity.
  ```python
  def event_handler(self, payload: SomePayload, unused_param: str) -> None:
      """docstrings/comments"""
      _ = unused_param  # Signal unused argument
      # Process event logic
      logger.info("Event processed")
  ```

## Docstrings & Comments
- Use Google-style docstrings (Args/Returns/Raises/Attributes) for modules, public classes, and public functions; keep private helpers short but present when non-trivial.
- Module docstring must be the first statement, followed by a blank line, then imports (keep `from __future__ import annotations` immediately after the docstring).
- Write all docstrings and comments in English; avoid Japanese unless the feature explicitly requires Japanese text in runtime data.
- Keep inline comments sparse and purposeful; prefer clear naming over heavy commenting.
- Update docstrings when behavior or parameters change; avoid stale sections.

## Integration Points
- TwitchIO EventSub: `Bot._subscribe_to_chat_events()` subscribes for the owner to chat message, deletion, and clear events; `event_oauth_authorized()` manages tokens and dynamic subscriptions.
- OAuth & IDs: `TokenManager` handles browser-based authorization, token refresh, ID resolution via `twitchio.Client`. Tokens saved atomically to [tokens.json](../tokens.json).
- Engines: translation engines (`google`, `deepl`) from config; TTS engines under [core/tts/engines](../core/tts/engines/) (e.g., `voicevox`, `g_tts`, `cevio_*`). Some engines have OS/driver dependencies (PyAudio, soundfile).
- Dictionaries: language conversion uses files under [dic/](../dic/) when `TTS.KATAKANAISE` is enabled.

## Documentation Management
- **Project analysis documents**: Generate analysis and design documents (e.g., `PROJECT_STRUCTURE.md`, `HANDLER_INTEGRATION_ANALYSIS.md`) in the dedicated `[docs/](../docs/)` folder, not in the workspace root.
- **Root-level exceptions**: Documents like `README.md`, `LICENSE`, and specification files that are conventionally placed at the root level are excluded from this rule.
- **Purpose**: Keeps the workspace root clean while centralizing all analysis and design documentation.
- **Reference format**: Link to documents as `[docs/document_name.md](../docs/document_name.md)` from other files.

## Practical Guidance for Changes
- New bot components: inherit from `core.components.Base`, implement `async_init()` and `close()`, and register in `Bot.setup_hook()`.
- New translation/TTS engines: follow `TransInterface`/`Interface` registration patterns; add engine name to INI (`TRANSLATION.ENGINE` or voice `engine` entries) and handle initialization errors cleanly.
- External calls: prefer `aiohttp` for HTTP; keep code async; log errors via `LoggerUtils` and return clear results (avoid raising in hot paths unless critical).

## Quick References
- Entry: [twitchbot.py](../twitchbot.py) → [core/bot.py](../core/bot.py)
- Managers: [core/trans/manager.py](../core/trans/manager.py), [core/tts/manager.py](../core/tts/manager.py)
- Config: [config/loader.py](../config/loader.py), INI: [twitchbot.ini](../twitchbot.ini)
- Tests: [tests/](../tests/) (pytest-asyncio configured in [pyproject.toml](../pyproject.toml))

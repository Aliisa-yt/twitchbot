日本語版は[README_ja.md](README_ja.md)をご覧ください。

# Twitchbot

Modular Twitch chat bot with translation, TTS, STT, cache, and GUI support. It subscribes to chat events, translates messages, optionally reads them aloud, and can forward speech recognition results into the TTS pipeline. The entry point is `src/twitchbot.py`, which wires config, OAuth, and all feature components.

## Feature Modules
- Translation module: Multi-engine translation (`google`, `deepl`, `google_cloud`) with language detection flow.
- TTS module: Role-based cast settings (`CAST`). Supported engines: `gTTS` (free Google TTS), `Bouyomichan`, `CeVIO AI`, `CeVIO Creative Studio 7`, `VOICEVOX`, `COEIROINK` (v1/v2).
- STT module: Optional speech-to-text input pipeline (`STT`) with retry/backoff and confidence filtering. VAD supports two modes: `level` (dBFS threshold) and `silero_onnx` (Silero ONNX Runtime).
- Cache module: Translation and language-detection cache controls (`CACHE`) for TTL, entry limits, and optional export path.
- GUI module: Status bar, scrolling log, and STT level meter. When STT is enabled, also shows VAD threshold sliders and a mute button.

## Setup
- Python 3.14+
- Before running, register an application on [Twitch Developers](https://dev.twitch.tv/) and obtain your `CLIENT ID` and `CLIENT SECRET`. We do not cover the registration flow here; please follow Twitch's docs or a setup guide. When creating the app, add `http://localhost` to **OAuth Redirect URLs**.
- Twitch API credentials as environment variables:
  - `TWITCH_API_CLIENT_ID`
  - `TWITCH_API_CLIENT_SECRET`
- Install dependencies: `pip install .`
- Prepare `twitchbot.ini` from the template:
  1. Copy `twitchbot.ini.example` to `twitchbot.ini`
  2. Edit `twitchbot.ini` and set your Twitch channel owner name and bot account name
  3. Customize other settings as needed (translation engines, TTS parameters, etc.)
- **Log in to Twitch with the bot account**:
  - Before obtaining OAuth tokens, make sure you are logged into Twitch with the bot account in your browser.
  - If you are logged in with a different account, log out and log back in with the bot account.
  - Attempting to obtain tokens while logged in as a non-bot account will result in an error. In that case, log in with the bot account and run the command again.
- Obtain OAuth tokens:
  - Run `python src/setup_tokens.py [--owner OWNER_NAME] [--bot BOT_NAME]`
    - If the owner and bot names are already set in `twitchbot.ini`, you can run `python src/setup_tokens.py` without arguments.
  - This opens a browser for OAuth authorization and caches tokens to `tokens.db`.
  - Required before first run of the bot.
  - If `tokens.db` is deleted or corrupted after a successful authentication, an error may appear at startup. In that case, start over from the bot account login step above.

## Run

### Local Execution
1) Set the environment variables above.
2) Run `src/setup_tokens.py` if you haven't already (see Setup section).
3) From the repo root: `python src/twitchbot.py [--owner OWNER_NAME] [--bot BOT_NAME] [--debug] [--gui|--no-gui]`
   If `twitchbot.ini` is already configured, you can run `python src/twitchbot.py` without arguments.
   - `--owner OWNER_NAME` (optional): Twitch channel owner name; overrides `twitchbot.ini`
   - `--bot BOT_NAME` (optional): Bot account name; overrides `twitchbot.ini`
   - `-d`, `--debug` (optional): Enable debug mode for detailed logging
   - `-g`, `--gui` (optional): Launch with GUI interface (default)
   - `--no-gui` (optional): Launch in console-only mode
4) The bot runs in GUI mode by default, showing a status window. Use `--no-gui` for console-only mode.
5) Stop the bot with `Ctrl+C` (console mode) or close the GUI window.

### Build Executable with PyInstaller
The `.spec` file is provided; build the EXE from the repo root:
```powershell
pyinstaller twitchbot.spec --clean
```
The output executable will be in the `dist/twitchbot/` directory.

## Configuration

For detailed configuration options, refer to [CONFIGURATION_en.md](docs/CONFIGURATION_en.md).

Key configuration sections in `twitchbot.ini`:
- **[GENERAL], [TWITCH], [BOT]**: Debug behavior, owner/bot identity, and chat output behavior.
- **[TRANSLATION]**: Engine priority and language pair settings.
- **[DICTIONARY]**: Katakana/romaji conversion dictionaries used by text normalization.
- **[TTS], [TTS_FORMAT], [CAST]**: TTS enablement, formatting templates, and role-based voice assignment.
- **[STT]**: Speech-to-text engine (`google_cloud_stt` / `google_cloud_stt_v2`), retry/backoff policy, and forwarding behavior to TTS.
- **[VAD]**: VAD mode (`level` / `silero_onnx`), pre/post buffer (ms), and maximum segment duration.
- **[LEVELS_VAD]**: Start/stop thresholds (dBFS) for level-based VAD.
- **[SILERO_VAD]**: Model path, detection threshold, and thread count for Silero ONNX VAD.
- **[CACHE]**: Cache TTL, maximum entry limits per engine, and export path.
- **[GUI]**: GUI meter update rate.
- **[CEVIO_AI], [CEVIO_CS7], [BOUYOMICHAN], [VOICEVOX], [COEIROINK], [COEIROINK2]**: Per-engine connection/startup options.
- **[TIME_SIGNAL]**: Scheduled time announcements.

## Development

### Run Tests
```powershell
pytest -q
```

For coverage report:
```powershell
coverage run -m pytest tests/ -v
coverage report
coverage html  # generates HTML report in htmlcov/
```

### Linting and Type Checking
```powershell
ruff check .
ruff format .
mypy .
```

All settings are configured in [pyproject.toml](pyproject.toml).

## License
- Core project: MIT License (see [LICENSE](LICENSE)).
- The bundled alphabet-to-katakana conversion dictionary [dic/bep-eng.dic](dic/bep-eng.dic) comes from the [Bilingual Emacspeak Project](http://www.argv.org/bep/) and is licensed under GPL v2 (see [LICENSE-GPL-v2](LICENSE-GPL-v2)).

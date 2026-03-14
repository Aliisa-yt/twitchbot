日本語版は[README_ja.md](README_ja.md)をご覧ください。

# Twitchbot

Modular Twitch chat bot with translation, TTS, STT, cache, and GUI support. It subscribes to chat events, translates messages, optionally reads them aloud, and can forward speech recognition results into the TTS pipeline. The entry point is `twitchbot.py`, which wires config, OAuth, and all feature components.

## Feature Modules
- Translation module: Multi-engine translation (`google`, `deepl`, `google_cloud`) with language detection flow.
- TTS module: Role-based cast settings (`CAST`) and per-engine runtime settings (`CEVIO_AI`, `VOICEVOX`, etc.).
- STT module: Optional speech-to-text input pipeline (`STT`) with retry/backoff and confidence filtering.
- Cache module: Translation and language-detection cache controls (`CACHE`) for TTL and entry limits.
- GUI module: Optional desktop status/level meter (`GUI`) with configurable refresh rate.

## Setup
- Python 3.13+
- Before running, register an application on [Twitch Developers](https://dev.twitch.tv/) and obtain your `CLIENT ID` and `CLIENT SECRET`. We do not cover the registration flow here; please follow Twitch's docs or a setup guide. When creating the app, add `http://localhost` to **OAuth Redirect URLs**.
- Twitch API credentials as environment variables:
  - `TWITCH_API_CLIENT_ID`
  - `TWITCH_API_CLIENT_SECRET`
- Install dependencies: `pip install -r requirements.txt`
- Prepare `twitchbot.ini` from the template:
  1. Copy `twitchbot.ini.example` to `twitchbot.ini`
  2. Edit `twitchbot.ini` and set your Twitch channel owner name and bot account name
  3. Customize other settings as needed (translation engines, TTS parameters, etc.)
- Obtain OAuth tokens:
  - Run `python setup_tokens.py [--owner OWNER_NAME] [--bot BOT_NAME]`
  - This opens a browser for OAuth authorization and caches tokens to `tokens.db`
  - Required before first run of the bot

## Run

### Local Execution
1) Set the environment variables above.
2) Run `setup_tokens.py` if you haven't already (see Setup section).
3) From the repo root: `python twitchbot.py [--owner OWNER_NAME] [--bot BOT_NAME] [--debug] [--gui|--no-gui]`
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
- **[STT]**: Speech-to-text engine, input thresholds/buffers, retry policy, and forwarding behavior to TTS.
- **[CACHE]**: Cache TTL and maximum entry limits per engine.
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

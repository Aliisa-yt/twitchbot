日本語版は[README_ja.md](README_ja.md)をご覧ください。

# Twitchbot

Translation + TTS bot for Twitch chat. It subscribes to chat events, translates messages, and can read them aloud using the configured TTS engines. The entry point is `twitchbot.py`, which wires config, OAuth, translation, TTS, and bot components.

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

## Run

### Local Execution
1) Set the environment variables above.
2) From the repo root: `python twitchbot.py [--owner OWNER_NAME] [--bot BOT_NAME] [--debug]`
   - `--owner OWNER_NAME` (optional): Twitch channel owner name; overrides `twitchbot.ini`
   - `--bot BOT_NAME` (optional): Bot account name; overrides `twitchbot.ini`
   - `-d`, `--debug` (optional): Enable debug mode for detailed logging
3) First launch opens a browser for OAuth; tokens cache to `tokens.db`.
4) Stop the bot with `Ctrl+C`.

### Build Executable with PyInstaller
The `.spec` file is provided; build the EXE from the repo root:
```powershell
pyinstaller twitchbot.spec --clean
```
The output executable will be in the `dist/twitchbot/` directory.

## Configuration

For detailed configuration options, refer to [CONFIGURATION_en.md](docs/CONFIGURATION_en.md).

Key configuration areas:
- **Translation engines**: Google, DeepL, Google Cloud
- **TTS parameters**: Voice selection, speed, tone, volume
- **Chat formatting**: Display name, language codes, emotes
- **Time signals**: Scheduled announcements

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

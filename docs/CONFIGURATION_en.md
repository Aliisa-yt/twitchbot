# twitchbot.ini Configuration Guide

This document lists all sections and items in `twitchbot.ini`. Refer to "Format and Value Rules" for syntax and types. For voice settings details, see [VOICE_SETTINGS_en.md](VOICE_SETTINGS_en.md).

## Format and Value Rules

### File Structure

`twitchbot.ini` uses sections with key-value pairs.

```
[Section1]
Key1-1 = Value1-1
Key1-2 = Value1-2

[Section2]
Key2-1 = Value2-1
Key2-2 = Value2-2
```

Section names and keys are recommended to be uppercase. Lines starting with `#` are comments.

### Value Format

| Type | Description |
|:---:| --- |
| str | String. Must be enclosed in `""` and is case-sensitive. |
| int | Integer. Only numeric values. |
| bool | Boolean. Either `True` or `False`. |
| list[str] | Array of strings. Example: empty is `[]`, two items: `["foo", "bar"]`. |

---

## Section Descriptions

### [GENERAL]

| Item | Type | Description |
| --- |:---:| --- |
| DEBUG | bool | `True`: Outputs debug level and above to file, warning level and above to console.<br>`False`: Outputs warning level and above to both file and console. |

### [TWITCH]

| Item | Type | Description |
| --- |:---:| --- |
| OWNER_NAME | str | Specifies the broadcaster's username (login name, not display name). |

### [BOT]

| Item | Type | Description |
| --- |:---:| --- |
| BOT_NAME | str | Specifies the bot's username (login name, not display name). |
| COLOR | str | Specifies the bot name color displayed in chat. Refer to "[Available Colors](#available-colors)" below. |
| LOGIN_MESSAGE | str | Specifies the message output when the bot starts. |
| DONT_LOGIN_MESSAGE | bool | `True`: Outputs LOGIN_MESSAGE only to console.<br>`False`: Outputs to both console and chat. |
| SHOW_BYNAME | bool | `True`: Adds username to translated text.<br>`False`: Does not add. |
| SHOW_EXTENDEDFORMAT | bool | `True`: Adds user display name to translated text.<br>`False`: Does not add. |
| SHOW_BYLANG | bool | `True`: Adds language code information to translated text.<br>`False`: Does not add. |
| CONSOLE_OUTPUT | bool | `True`: Outputs chat content to console.<br>`False`: Does not output. |
| IGNORE_USERS | list[str] | Usernames to skip for TTS and translation. Typically chat management bot names. |

#### Available Colors

- New notation: *`blue`, `blue_violet`, `cadet_blue`, `chocolate`, `coral`, `dodger_blue`, `firebrick`, `golden_rod`, `green`, `hot_pink`, `orange_red`, `red`, `sea_green`, `spring_green`, `yellow_green`*
- Legacy notation: *`Blue`, `BlueViolet`, `CadetBlue`, `Chocolate`, `Coral`, `DodgerBlue`, `Firebrick`, `GoldenRod`, `Green`, `HotPink`, `OrangeRed`, `Red`, `SeaGreen`, `SpringGreen`, `YellowGreen`*

### [TRANSLATION]

| Item | Type | Description |
| --- |:---:| --- |
| ENGINE | list[str] | Translation engines to use. First entry has priority and can be switched via command.<br>Available: `google`, `deepl`, `google_cloud`.<br>For `deepl`, set environment variable `DEEPL_API_OAUTH`; for `google_cloud`, set `GOOGLE_CLOUD_API_OAUTH` with API keys. |
| GOOGLE_SUFFIX | str | Server suffix (e.g., `co.jp`) when using `google` translation engine. Does not affect other engines. |
| NATIVE_LANGUAGE | str | Specifies the ISO 639-1 language code for native (first) language. |
| SECOND_LANGUAGE | str | Specifies the ISO 639-1 language code for second language. |

### [DICTIONARY]

| Item | Type | Description |
| --- |:---:| --- |
| PATH | str | Specifies the base path for dictionary files (relative path allowed). |
| KATAKANA_DIC | list[str] | Dictionaries for converting English words to katakana. Multiple files allowed, loaded sequentially with overrides. |
| ROMAJI_DIC | str | Specifies the dictionary file name for converting romaji to katakana. |

### [TTS]

| Item | Type | Description |
| --- |:---:| --- |
| ORIGINAL_TEXT | bool | `True`: Reads out original text.<br>`False`: Does not read out. |
| TRANSLATED_TEXT | bool | `True`: Reads out translated text.<br>`False`: Does not read out. |
| ENABLED_LANGUAGES | list[str] | List of language codes to enable for TTS. Only specified languages are read out.<br>Empty means all languages are enabled. |
| KATAKANAISE | bool | `True`: Converts English words and romaji in Japanese to katakana.<br>`False`: Does not convert. |
| EMOTE_TEXT | bool | `True`: Reads out emotes.<br>`False`: Does not read out.<br>**Only effective when reading original text.** |
| LIMIT_SAME_EMOTE | int | Maximum number of same emote reads. 0 means unlimited. |
| LIMIT_TOTAL_EMOTES | int | Maximum number of total emote reads. 0 means unlimited. |
| LIMIT_CHARACTERS | int | Maximum character count for TTS. 0 means unlimited. |
| LIMIT_TIME | int | Maximum time (seconds) for TTS. 0 means unlimited. |
| ALLOW_TTS_TWEAK | bool | `True`: Allows voice parameter temporary modification commands.<br>`False`: Does not allow. |

### [TTS_FORMAT]

| Item | Type | Description |
| --- |:---:| --- |
| ORIGINAL_MESSAGE | dict[str:str] | Defines the TTS format for original text. |
| TRANSLATED_MESSAGE | dict[str:str] | Defines the TTS format for translated text. |
| REPLY_MESSAGE | dict[str:str] | Defines the TTS format for replies. |
| WAITING_COMMA | dict[str:str] | Defines the character to use as comma. |
| WAITING_PERIOD | dict[str:str] | Defines the character to use as period. |

### [CAST]

| Item | Type | Description |
| --- |:---:| --- |
| DEFAULT | list[dict[str:str]] | Default TTS voice settings. |
| STREAMER | list[dict[str:str]] | Settings for channel owner. Uses `DEFAULT` if not specified. |
| MODERATOR | list[dict[str:str]] | Settings for moderators. Uses `DEFAULT` if not specified. |
| VIP | list[dict[str:str]] | Settings for VIP users. Uses `DEFAULT` if not specified. |
| SUBSCRIBER | list[dict[str:str]] | Settings for subscribers. Uses `DEFAULT` if not specified. |
| OTHERS | list[dict[str:str]] | Settings for other users. Uses `DEFAULT` if not specified. |
| SYSTEM | list[dict[str:str]] | Settings for system messages. Uses `DEFAULT` if not specified. |

For voice setting format and parameter details, refer to [VOICE_SETTINGS_en.md](VOICE_SETTINGS_en.md).

### [CEVIO_AI]

| Item | Type | Description |
| --- |:---:| --- |
| EARLY_SPEECH | bool | `True`: Automatically increases reading speed for long text.<br>`False`: Does not change speed. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |

### [CEVIO_CS7]

| Item | Type | Description |
| --- |:---:| --- |
| EARLY_SPEECH | bool | `True`: Automatically increases reading speed for long text.<br>`False`: Does not change speed. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |

### [BOUYOMICHAN]

| Item | Type | Description |
| --- |:---:| --- |
| SERVER | str | Specifies the address and port number for external control. |
| TIMEOUT | float | Specifies the timeout in seconds. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |
| EXECUTE_PATH | str | Specifies the TTS engine executable file path (environment variables allowed). |

### [VOICEVOX]

| Item | Type | Description |
| --- |:---:| --- |
| SERVER | str | Specifies the address and port number for external control. |
| TIMEOUT | float | Specifies the timeout in seconds. |
| EARLY_SPEECH | bool | `True`: Automatically increases reading speed for long text.<br>`False`: Does not change speed. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |
| EXECUTE_PATH | str | Specifies the TTS engine executable file path (environment variables allowed). |

### [COEIROINK]

| Item | Type | Description |
| --- |:---:| --- |
| SERVER | str | Specifies the address and port number for external control. |
| TIMEOUT | float | Specifies the timeout in seconds. |
| EARLY_SPEECH | bool | `True`: Automatically increases reading speed for long text.<br>`False`: Does not change speed. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |
| EXECUTE_PATH | str | Specifies the TTS engine executable file path (environment variables allowed). |

### [COEIROINK2]

| Item | Type | Description |
| --- |:---:| --- |
| SERVER | str | Specifies the address and port number for external control. |
| TIMEOUT | float | Specifies the timeout in seconds. |
| EARLY_SPEECH | bool | `True`: Automatically increases reading speed for long text.<br>`False`: Does not change speed. |
| AUTO_STARTUP | bool | `True`: Automatically starts TTS engine.<br>`False`: Manual startup required. |
| EXECUTE_PATH | str | Specifies the TTS engine executable file path (environment variables allowed). |

### [TIME_SIGNAL]

| Item | Type | Description |
| --- |:---:| --- |
| TEXT | bool | `True`: Displays time signal messages in console.<br>`False`: Does not display. |
| VOICE | bool | `True`: Reads out time signal messages.<br>`False`: Does not read out. |
| CLOCK12 | bool | `True`: Outputs time signals in 12-hour format.<br>`False`: Outputs in 24-hour format. |
| AM_NAME | str | Prefix to use for AM. Only effective when CLOCK12 is `True`. |
| PM_NAME | str | Prefix to use for PM. Only effective when CLOCK12 is `True`. |

This feature was created only for testing scheduled processing using TwitchIO's routines class, so there are not many detailed settings.
If it's in the way, set both `TEXT` and `VOICE` to `False`, or comment out TimeSignalManager(self) in bot.Bot.setup_hook() and rebuild.

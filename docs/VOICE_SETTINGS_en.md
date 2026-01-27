# [CAST] Configuration Guide

This document explains how to configure voice settings in the [CAST] section. For an overview of [twitchbot.ini](twitchbot.ini), refer to [CONFIGURATION_en.md](CONFIGURATION_en.md).

## Format

Voice settings use the following format. Here's an example for `DEFAULT`:

```
DEFAULT = [
    {"lang" : "ja", "engine" : "cevio_ai", "cast" : "さとうささら", "param" : "v45,s50"},
    {"lang" : "all", "engine" : "gtts", "param" : "v95"},
    ]
```

Place multiple settings enclosed in `{}` within `[]`. Include the trailing `,`.

In this example, when the chat message language is `"ja"`, it uses engine `"cevio_ai"`, cast `"さとうささら"`, volume `45`, and speed `50`. For other languages, it uses engine `"gtts"` with volume `95`.

## Value Descriptions

1. `"lang"` value  
    Specifies the ISO 639-1 language code. Applied when matching the chat message language. Use `"all"` to apply to all languages.

2. `"engine"` value  
    Specifies the TTS engine name to use. Available values:
    - `"gtts"`: Uses gTTS (Google Text-to-Speech)
    - `"bouyomichan"`: Uses BouyomiChan
    - `"cevio_cs7"`: Uses CeVIO CS7
    - `"cevio_ai"`: Uses CeVIO AI
    - `"voicevox"`: Uses VOICEVOX
    - `"coeiroink"`: Uses COEIROINK ver1 series
    - `"coeiroink2"`: Uses COEIROINK ver2 series

3. `"cast"` value  
    Specifies the voice name when the engine has multiple voices. The specification method varies by engine. `"gtts"` ignores voice specification, so it can be omitted.

4. `"param"` value  
    Used when specifying parameters different from defaults.

    ```
    Format: "v(value),s(value),t(value),i(value),a(value)"
    ```

    The meaning of values varies by engine. Unsupported items are ignored. Order is arbitrary, and if the same item is written multiple times, the last value is effective.

    - v: Volume (e.g., `v100`)
    - s: Reading speed (e.g., `s100`). `"gtts"` is not supported.
    - t: Tone (e.g., `t50`). `"gtts"` is not supported.
    - i: Voice quality (e.g., `i55`). Only `"cevio_cs7"` and `"cevio_ai"` are supported.
    - a: Intonation (e.g., `a1.0`). `"gtts"` and `"bouyomichan"` are not supported.

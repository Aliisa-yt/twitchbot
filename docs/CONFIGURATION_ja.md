# twitchbot.ini 設定項目の説明

`twitchbot.ini` の各セクションと項目を一覧にまとめています。値の書き方や型は「書式と値のルール」を参照してください。音声設定の詳細は [VOICE_SETTINGS_ja.md](VOICE_SETTINGS_ja.md) で補足しています。

## 書式と値のルール

### ファイル構造

`twitchbot.ini` はセクションごとにキーと値を記述します。

```
[セクション1]
キー1-1 = 値1-1
キー1-2 = 値1-2

[セクション2]
キー2-1 = 値2-1
キー2-2 = 値2-2
```

セクション名とキーは大文字を推奨します。`#` から始まる行はコメント行です。

### 値の書式

| 型 | 説明 |
|:---:| --- |
| str | 文字列。必ず `""` で囲み、大文字小文字を区別します。 |
| int | 整数値。数値のみ記述します。 |
| bool | 真偽値。`True` または `False` のいずれかを指定します。 |
| list[str] | 文字列の配列。例: 空は `[]`、2 個なら `["foo", "bar"]` のように記述します。 |

---

## セクション別の説明

### [GENERAL]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| DEBUG | bool | `True`: debug 以上をファイル出力し、warning 以上をコンソール出力します。<br>`False`: warning 以上をファイル・コンソールに出力します。 |

### [TWITCH]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| OWNER_NAME | str | 配信者のユーザー名（表示名ではなくログイン名）を指定します。 |

### [BOT]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| BOT_NAME | str | BOT のユーザー名（表示名ではなくログイン名）を指定します。 |
| COLOR | str | チャットに表示される BOT 名の色を指定します。下記「[使用可能な色](#使用可能な色)」を参照してください。 |
| LOGIN_MESSAGE | str | BOT 起動時に出力するメッセージを指定します。 |
| DONT_LOGIN_MESSAGE | bool | `True`: LOGIN_MESSAGE をコンソールのみに出力します。<br>`False`: コンソールとチャットに出力します。 |
| SHOW_BYNAME | bool | `True`: 翻訳文にユーザー名を追加します。<br>`False`: 追加しません。 |
| SHOW_EXTENDEDFORMAT | bool | `True`: 翻訳文にユーザーの表示名を追加します。<br>`False`: 追加しません。 |
| SHOW_BYLANG | bool | `True`: 翻訳文に言語コード情報を追加します。<br>`False`: 追加しません。 |
| CONSOLE_OUTPUT | bool | `True`: チャット内容をコンソールへ出力します。<br>`False`: 出力しません。 |
| IGNORE_USERS | list[str] | 読み上げ・翻訳を行わないユーザー名。通常はチャット管理アプリのユーザー名を指定します。 |

#### 使用可能な色

- 新しい表記: *`blue`, `blue_violet`, `cadet_blue`, `chocolate`, `coral`, `dodger_blue`, `firebrick`, `golden_rod`, `green`, `hot_pink`, `orange_red`, `red`, `sea_green`, `spring_green`, `yellow_green`*
- 従来表記: *`Blue`, `BlueViolet`, `CadetBlue`, `Chocolate`, `Coral`, `DodgerBlue`, `Firebrick`, `GoldenRod`, `Green`, `HotPink`, `OrangeRed`, `Red`, `SeaGreen`, `SpringGreen`, `YellowGreen`*

### [TRANSLATION]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| ENGINE | list[str] | 使用する翻訳エンジン。先頭が優先され、コマンドで切り替え可能です。<br>利用可能: `google`, `deepl`, `google_cloud`。<br>`deepl` は環境変数 `DEEPL_API_OAUTH`、`google_cloud` は `GOOGLE_CLOUD_API_OAUTH` に API キーを設定してください。 |
| GOOGLE_SUFFIX | str | 翻訳エンジン `google` 利用時にアクセスするサーバーのサフィックス（例: `co.jp`）。他エンジンには影響しません。 |
| NATIVE_LANGUAGE | str | 母語（第一言語）の ISO 639-1 言語コードを指定します。 |
| SECOND_LANGUAGE | str | 第二言語の ISO 639-1 言語コードを指定します。 |

### [DICTIONARY]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| PATH | str | 辞書ファイルのベースパス（相対パス可）を指定します。 |
| KATAKANA_DIC | list[str] | 英単語をカタカナ読みする辞書。複数指定可で先頭から順に上書き読み込みします。 |
| ROMAJI_DIC | str | ローマ字をカタカナ読みする辞書ファイル名を指定します。 |

### [TTS]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| ORIGINAL_TEXT | bool | `True`: 原文を読み上げます。<br>`False`: 読み上げません。 |
| TRANSLATED_TEXT | bool | `True`: 翻訳文を読み上げます。<br>`False`: 読み上げません。 |
| ENABLED_LANGUAGES | list[str] | 読み上げを有効にする言語コードのリスト。指定された言語のみ読み上げます。<br>無指定はすべての言語を有効にします。 |
| KATAKANAISE | bool | `True`: 日本語中の英単語・ローマ字をカタカナ読みへ変換します。<br>`False`: 変換しません。 |
| EMOTE_TEXT | bool | `True`: エモートを読み上げます。<br>`False`: 読み上げません。<br>**原文の読み上げ時にのみ効果があります。** |
| LIMIT_SAME_EMOTE | int | 同一エモートの読み上げ上限数。0 で無制限です。 |
| LIMIT_TOTAL_EMOTES | int | エモートの読み上げ上限数。0 で無制限です。 |
| LIMIT_CHARACTERS | int | 読み上げる文字数上限。0 で無制限です。 |
| LIMIT_TIME | int | 読み上げる時間（秒）上限。0 で無制限です。 |
| ALLOW_TTS_TWEAK | bool | `True`: 音声パラメータ一時変更コマンドを許可します。<br>`False`: 許可しません。 |

### [TTS_FORMAT]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| ORIGINAL_MESSAGE | dict[str:str] | 原文の読み上げフォーマットを定義します。 |
| TRANSLATED_MESSAGE | dict[str:str] | 翻訳文の読み上げフォーマットを定義します。 |
| REPLY_MESSAGE | dict[str:str] | 返信時の読み上げフォーマットを定義します。 |
| WAITING_COMMA | dict[str:str] | 読点として使用する文字を定義します。 |
| WAITING_PERIOD | dict[str:str] | 句点として使用する文字を定義します。 |

### [CAST]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| DEFAULT | list[dict[str:str]] | デフォルトの読み上げ音声設定です。 |
| STREAMER | list[dict[str:str]] | チャンネルオーナー用の設定。未指定時は `DEFAULT` を使用します。 |
| MODERATOR | list[dict[str:str]] | モデレーター用の設定。未指定時は `DEFAULT` を使用します。 |
| VIP | list[dict[str:str]] | VIP ユーザー用の設定。未指定時は `DEFAULT` を使用します。 |
| SUBSCRIBER | list[dict[str:str]] | サブスクライバー用の設定。未指定時は `DEFAULT` を使用します。 |
| OTHERS | list[dict[str:str]] | その他のユーザー用の設定。未指定時は `DEFAULT` を使用します。 |
| SYSTEM | list[dict[str:str]] | システムメッセージ用の設定。未指定時は `DEFAULT` を使用します。 |

音声設定の書式やパラメータの詳細は [VOICE_SETTINGS_ja.md](VOICE_SETTINGS_ja.md) を参照してください。

### [CEVIO_AI]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| EARLY_SPEECH | bool | `True`: 長文時に読み上げ速度を自動で速めます。<br>`False`: 速度を変えません。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |

### [CEVIO_CS7]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| EARLY_SPEECH | bool | `True`: 長文時に読み上げ速度を自動で速めます。<br>`False`: 速度を変えません。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |

### [BOUYOMICHAN]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| SERVER | str | 外部制御用のアドレスとポート番号を指定します。 |
| TIMEOUT | float | タイムアウト秒数を指定します。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |
| EXECUTE_PATH | str | TTS エンジン実行ファイルのパス（環境変数利用可）を指定します。 |

### [VOICEVOX]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| SERVER | str | 外部制御用のアドレスとポート番号を指定します。 |
| TIMEOUT | float | タイムアウト秒数を指定します。 |
| EARLY_SPEECH | bool | `True`: 長文時に読み上げ速度を自動で速めます。<br>`False`: 速度を変えません。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |
| EXECUTE_PATH | str | TTS エンジン実行ファイルのパス（環境変数利用可）を指定します。 |

### [COEIROINK]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| SERVER | str | 外部制御用のアドレスとポート番号を指定します。 |
| TIMEOUT | float | タイムアウト秒数を指定します。 |
| EARLY_SPEECH | bool | `True`: 長文時に読み上げ速度を自動で速めます。<br>`False`: 速度を変えません。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |
| EXECUTE_PATH | str | TTS エンジン実行ファイルのパス（環境変数利用可）を指定します。 |

### [COEIROINK2]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| SERVER | str | 外部制御用のアドレスとポート番号を指定します。 |
| TIMEOUT | float | タイムアウト秒数を指定します。 |
| EARLY_SPEECH | bool | `True`: 長文時に読み上げ速度を自動で速めます。<br>`False`: 速度を変えません。 |
| AUTO_STARTUP | bool | `True`: TTS エンジンを自動起動します。<br>`False`: 手動起動が必要です。 |
| EXECUTE_PATH | str | TTS エンジン実行ファイルのパス（環境変数利用可）を指定します。 |

### [TIME_SIGNAL]

| 項目 | 型 | 説明 |
| --- |:---:| --- |
| TEXT | bool | `True`: 時報メッセージをコンソールに表示します。<br>`False`: 表示しません。 |
| VOICE | bool | `True`: 時報メッセージの読み上げを行います。<br>`False`: 読み上げません。 |
| CLOCK12 | bool | `True`: 時報を 12 時間制で出力します。<br>`False`: 24 時間制で出力します。 |
| AM_NAME | str | 午前に使う接頭語。CLOCK12 が `True` の場合のみ有効です。 |
| PM_NAME | str | 午後に使う接頭語。CLOCK12 が `True` の場合のみ有効です。 |

TwitchIO の routines クラスを使用した定時処理の動作確認用に作っただけのため、あまり細かい設定はありません。
邪魔な場合は、`TEXT` と `VOICE` を両方 `False` にするか、bot.Bot.setup_hook() 内の TimeSignalManager(self) をコメントアウトして、再ビルドしてください。

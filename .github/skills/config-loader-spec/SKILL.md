---
name: config-loader-spec
description: 設定ファイル(twitchbot.ini)の読み込み・設定値のバリデーション・変換を定義するスキル
keywords: config, loader, validation, configparser, ini
files: ./config/loader.py
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。
この文書は、twitchbot.ini の読み込みと設定値の検証に関する共通方針を定義します。
設定の読み込みと検証を一元化することで、コードの重複を減らし、設定ミスによる障害を防止します。

## 1. 適用範囲

- 対象は config.loader.ConfigLoader と、その内部フォーマッタおよび検証処理。
- ローダーの入力は INI 文字列であり、出力は models.config_models.Config インスタンス。
- 仕様変更時はこの SKILL・実装・tests/config/test_loader.py を同時更新する。

## 2. 読み込みフロー

- 設定ファイルは UTF-8 で読み込む。
- 指定ファイルが存在しない場合は ConfigFileNotFoundError で即時失敗する。
- configparser でパース不能な場合は ConfigFormatError を送出する。
- 読み込み後、次の順で処理する。
	- Config のデフォルト値を初期化。
	- INI に存在するキーのみ上書き（未定義キーは既定値を維持）。
	- CAST から VOICE_PARAMETERS を自動構築。
	- CLI 引数 override を適用（owner, bot, debug）。
	- 最終バリデーションを実行。

## 3. 型変換ルール

- bool/int/float は専用変換で処理する。
	- bool: ConfigParser.getboolean を使用。
	- int: 一旦 float 化してから int 化する（例: "1.0" -> 1）。
	- float: 文字列を float 化する。
	- int/float は先頭末尾の引用符と % 記号を除去してから解釈する。
- それ以外（list, dict, str など）は ast.literal_eval で評価する。
- 型変換エラーは ConfigValueError / ConfigTypeError / ConfigFormatError として扱う。

## 4. デフォルトと欠損時の扱い

- INI にキーが存在しない場合、その項目は dataclass 側のデフォルト値を維持する。
- セクション未定義時も同様にデフォルトで動作する。
- STT セクションが無い場合は STT を無効（ENABLED=False）として扱う。
- ただし設定ファイル自体の不在は許容しない（起動失敗）。

## 5. CAST / VOICE_PARAMETERS 構築規約

- VOICE_PARAMETERS は INI から直接読まない。CAST から合成する。
- DEFAULT を全ユーザー種別（streamer/moderator/vip/subscriber/others/system）のベースとする。
- ユーザー種別の言語指定がある場合は同一言語キーを上書きする。
- 1 エントリ内の主要キーは lang / engine / cast / param。
- param はカンマ区切りで以下を受理する。
	- v: volume
	- s: speed
	- t: tone
	- a: alpha
	- i: intonation
- param 値は整数または小数を受理し、小数は 100 倍して int 化する（例: v1.0 -> 100）。
- 未知の param プレフィックスや不正値は ConfigValueError。

## 6. バリデーション規約

### 6.1 ユーザー名

- TWITCH.OWNER_NAME と BOT.BOT_NAME は ^[a-zA-Z0-9_]{4,25}$ を満たす必要がある。
  - この正規表現は Twitch のユーザー名ルールに基づいている。そのため Twitch が将来ルールを変更した場合はこの正規表現も更新する必要がある。
- 形式違反は ConfigFormatError。
- 大文字を含む場合は warning ログのみ（エラーにはしない）。

### 6.2 TRANSLATION.ENGINE

- 受理リストは google / deepl / google_cloud。
- 値は str または list[str] のみ許可。
- 型不一致は ConfigTypeError。
- 受理リスト外の値は warning ログ（起動停止しない）。

### 6.3 BOT.COLOR

- API カラー（snake_case）と旧チャットコマンドカラー（PascalCase）の両方を受理する。
- 旧表記が来た場合は API 表記に正規化して情報ログを出す。
- 非対応色は ConfigValueError。

### 6.4 STT（ENABLED=True 時のみ厳格検証）

- ENGINE 必須、かつ google_cloud_stt / google_cloud_stt_v2 のいずれか。
- INPUT_DEVICE と LANGUAGE は空文字不可。
- 数値範囲:
	- SAMPLE_RATE >= 8000
	- CHANNELS >= 1
	- VAD.PRE_BUFFER_MS >= 0
	- VAD.POST_BUFFER_MS >= 0
	- VAD.MAX_SEGMENT_SEC >= 1
	- LEVELS_VAD.START, LEVELS_VAD.STOP は -60.0 から 0.0（VAD.MODE=level のとき）
	- LEVELS_VAD.START >= LEVELS_VAD.STOP（VAD.MODE=level のとき）
	- SILERO_VAD.THRESHOLD は 0.0 から 1.0（VAD.MODE=silero_onnx のとき）
	- SILERO_VAD.ONNX_THREADS は 0 から 8（VAD.MODE=silero_onnx のとき）
	- RETRY_MAX >= 0
	- RETRY_BACKOFF_MS >= 0
- 違反は ConfigValueError。

## 7. 例外・警告方針

- 失敗系は ConfigLoaderError 派生へ正規化して呼び出し元へ伝播する。
- 主な使い分け:
	- ConfigFileNotFoundError: ファイル不在
	- ConfigFormatError: パース失敗・総称的な不正
	- ConfigValueError: 値として不正
	- ConfigTypeError: 型として不正
- 仕様上の軽微不整合は warning で継続する。
	- 例: TRANSLATION.ENGINE の未知値、ユーザー名の非 lowercase

## 8. 外部インターフェース契約

- コンストラクタは config_filename と script_name を必須とする。
- CLI 上書きは owner, bot, debug を受理する。
- 最終出力は辞書ではなく Config オブジェクト（loader.config）を公開契約とする。
- 設定ファイル（twitchbot.ini）は読み取り専用として扱う。実行時の書き込みは禁止する。

## 9. テスト観点

- 少なくとも次をテストで担保する。
	- ファイル不在時の例外
	- bool/int/float/literal_eval の型変換失敗
	- COLOR 正規化
	- CLI 上書き
	- CAST param 解析
	- STT の有効時厳格検証と無効時スキップ

## 10. 実装変更時の更新指針

- 許容値リストを変更したら、この SKILL の該当節と tests/config/test_loader.py を更新する。
- INI 項目追加時は models.config_models.Config と docs/CONFIGURATION_ja.md / docs/CONFIGURATION_en.md を同期する。
- エラー種別や継続/停止方針を変える場合は、呼び出し元（twitchbot.py / setup_tokens.py）のハンドリング影響を確認する。

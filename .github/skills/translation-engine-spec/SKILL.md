name: translation-engine-spec
description: src/core/trans/engines の翻訳エンジン契約、認証分岐、例外正規化、クォータ仕様ガイド
keywords: translation-engine, transinterface, deepl, google, google-cloud, auth, exception-mapping, rate-limit, quota

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `src/core/trans/engines/` 配下の翻訳エンジンクラスを変更・追加する際の実装ガイドです。
対象は主に `DeeplTranslation` / `GoogleTranslation` / `GoogleCloudTranslation` と、
Google向け補助実装 `AsyncTranslator` です。

## 1. 責務と共通契約

- すべてのエンジンは `TransInterface` を実装し、`fetch_engine_name()` で一意名を返す。
- `TransInterface.__init_subclass__()` により、エンジンクラスは自動登録される。
- `initialize()` では `engine_attributes` を**一度だけ**設定する（再設定は `RuntimeError`）。
- `detect_language()` は `Result.detected_source_lang` を必ず返す前提で扱われる。
- `translation()` は `Result.text` と `Result.detected_source_lang` を返し、失敗時は専用例外を送出する。
- レート制限判定は `TranslationRateLimitError` を基準に、`TransManager` 側の適応バックオフへ連携される。

## 2. エンジン属性（EngineAttributes）

- `name`: エンジン識別名。`fetch_engine_name()` と整合させる。
- `supports_dedicated_detection_api`:
	- `google_cloud` は `True`（検出専用APIあり）
	- `google` / `deepl` は `False`（検出で翻訳APIを兼用）
- `supports_quota_api`:
	- `deepl` は `True`（使用量取得APIあり）
	- `google` / `google_cloud` は `False`

## 3. エンジン別仕様

### 3.1 `DeeplTranslation` (`src/core/trans/engines/trans_deepl.py`)

- 認証: 環境変数 `DEEPL_API_OAUTH`（`get_authentication_key()` 経由）を使用する。
- 初期化:
	- `DeepLClient` を生成し、`_inst` setter 内で `_get_usage()` を呼んで可用性を確定する。
	- インスタンス登録時に `__available = True` を即時設定しない点が重要（使用量確認結果を優先）。
- 言語コード変換:
	- `Language` 定数から `_source_codes` / `_target_codes` を生成する。
	- 中国語 (`zh-CN` / `zh-TW`) は `ZH` に正規化する。
- 翻訳:
	- `src_lang` / `tgt_lang` を DeepL 形式へ変換して `translate_text()` を呼ぶ。
	- 未対応言語は `NotSupportedLanguagesError`。
- 例外分類:
	- `QuotaExceededException` -> `TranslationQuotaExceededError`（同時に `__available=False`）
	- `TooManyRequestsException` -> `TranslationRateLimitError`
	- `AuthorizationException` / `ConnectionException` / `DeepLException` -> `TranslateExceptionError`
- クォータ:
	- `get_quota_status()` は `_get_usage()` 実行後に `CharacterQuota` を返す。

### 3.2 `GoogleTranslation` (`src/core/trans/engines/trans_google.py`)

- 認証: APIキー不要（公開Web API相当の挙動）。
- 初期化:
	- `AsyncTranslator(url_suffix=config.TRANSLATION.GOOGLE_SUFFIX)` を生成する。
	- `supports_dedicated_detection_api=False`, `supports_quota_api=False`。
- 言語検出:
	- 専用検出APIを持たないため `detect_language()` は `translation()` を再利用する。
	- そのため検出時点で翻訳文が返る（`TransManager` が `translated_text` へ反映）。
- 例外分類:
	- `HTTPTooManyRequests` -> `TranslationRateLimitError`
	- それ以外の Google/HTTP 例外 -> `TranslateExceptionError`
- クォータ:
	- APIで取得しないため固定値（`count=0`, `limit=500000`, `limit_reached=False`）を返す。

### 3.3 `GoogleCloudTranslation` (`src/core/trans/engines/trans_google_cloud.py`)

- 認証方式:
	1. 環境変数 `GOOGLE_CLOUD_API_OAUTH` がある場合は API キー認証
	2. ない場合は `GOOGLE_APPLICATION_CREDENTIALS` を使うデフォルト認証
- APIキー認証:
	- `APIKeySession` で全リクエストURLへ `key=` を付与する。
	- private member 依存を避けるため、`translate.Client(..., _http=session)` で注入する。
- 初期化時確認:
	- `get_languages()` を呼び接続テストを行う。
- 言語検出:
	- `detect_language()` は検出専用で `Result.text=None` を返す。
	- `confidence` は `metadata` に格納する。
- 翻訳:
	- `translate()` の戻りから `translatedText` / `detectedSourceLanguage` を抽出する。
	- `BadRequest` は `NotSupportedLanguagesError`。
	- `TooManyRequests` は `TranslationRateLimitError`。
	- その他 `GoogleAPIError` は `TranslateExceptionError`。
- クォータ:
	- 直接取得APIがないためローカル固定値を返す。

## 4. `AsyncTranslator` の要点

- 5000文字以上の入力は `GoogleError` で拒否する。
- HTTPステータスは以下に分類する。
	- 429 -> `HTTPTooManyRequests`
	- 4xx/5xx -> `HTTPError`
	- 3xx -> `HTTPRedirection`
- Google応答のパースに失敗した場合は `ResponseFormatError` を送出する。
- URLライク文字列では `detected_source_lang="und"` となるケースがあり、
	上位（`TransManager`）で翻訳スキップ判定に使われる。

## 5. `TransManager` 連携時の重要点

- エンジン選択は `TransInterface.registered` を元に動的解決される。
- `has_dedicated_detection_api` が `False` のエンジンは、検出時の `Result.text` を翻訳文として利用される。
- `is_rate_limit_error()` 判定結果により、適応バックオフ（クールダウン）が適用される。
- エンジンが `is_available=False` になった場合、アクティブ一覧から除外されフォールバック対象になる。

## 6. テスト観点（最小セット）

- 各エンジンで認証未設定時に `is_available` と初期化ログが想定どおりになること。
- 未対応言語・レート制限・一般API失敗が専用例外へ正規化されること。
- 検出API有無フラグと `detect_language()` の戻り仕様が一致すること。
- `AsyncTranslator` のHTTP分類（429/4xx/5xx/3xx）が期待どおりに動くこと。
- `close()` 後に再初期化可能な状態へ戻ること。

## 7. 修正時チェックリスト

1. `fetch_engine_name()` の重複や空名で登録破壊が起きていないか。
2. `initialize()` で `engine_attributes` を二重設定していないか。
3. レート制限例外が `TranslationRateLimitError` に正しく正規化されているか。
4. 検出API有無フラグと `detect_language()` の実装が一致しているか。
5. Deeplの `_source_codes` / `_target_codes` 変換で言語コード欠落がないか。
6. Google Cloud の認証分岐（APIキー / デフォルト認証）が壊れていないか。
7. `close()` 実行後にインスタンス状態（`_inst`, usage, availability）が再初期化可能な形で戻るか。

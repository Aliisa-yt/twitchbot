name: translation-engine-spec
description: src/core/trans/engines の翻訳エンジン契約、認証分岐、例外正規化、クォータ仕様ガイド
keywords: translation-engine, transinterface, deepl, google, google-cloud, auth, exception-mapping, rate-limit, quota

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `src/core/trans/engines/` 配下の翻訳エンジンクラスを変更・追加する際の実装ガイドです。
対象は主に `DeeplTranslation` / `GoogleTranslation` / `GoogleCloudTranslation` と、
Google向け補助実装 `AsyncTranslator` です。

## 1. 責務と共通契約

- すべてのエンジンは `TransInterface` を実装し、静的メソッド `fetch_engine_name()` で一意名を返す。
- `TransInterface.__init_subclass__()` により、エンジンクラスは `TransInterface.registered`へ自動登録される。
- `fetch_engine_name()` が空文字または文字列以外を返す場合は登録しない。
- 同じエンジン名が登録済みの場合は `ValueError` を送出する。
- `initialize()` では `engine_attributes` を一度だけ設定する。再設定は `RuntimeError` を送出する。
- `EngineAttributes` はエンジン名、専用検出APIの有無、クォータAPIの有無を保持する。
- `detect_language()` は `Result` を返す。専用検出APIがない場合は翻訳処理を再利用し、検出時の翻訳文を `text` に含める。
- 専用検出APIがある場合は検出専用処理を呼び、翻訳文が不要なため通常は `text=None` を返す。
- `translation()` は翻訳文と検出されたソース言語を `Result` に格納する。失敗時は専用例外へ正規化する。
- レート制限判定は基本実装で `TranslationRateLimitError` を判定し、必要に応じてエンジン固有実装へ委譲できる。
- `is_available` はエンジンが現在利用可能かを示す。初期化失敗やクォータ枯渇時は現在のインスタンスから除外できるようにする。
- `close()` 後は再初期化できるように内部インスタンスと利用状態をリセットする。

## 2. エンジン属性（EngineAttributes）

- `name`: エンジン識別名。設定値と `fetch_engine_name()` と完全に一致させる。
- `supports_dedicated_detection_api`: 専用言語検出APIの有無。
  - `google_cloud`: `True`
  - `google`: `False`
  - `deepl`: `False`
- `supports_quota_api`: クォータ／使用量取得APIの有無。
  - `deepl`: `True`
  - `google`: `False`
  - `google_cloud`: `False`
- 設定ローダーで許可されるエンジン名は `google` / `deepl` / `google_cloud`。

## 3. エンジン別仕様

### 3.1 `DeeplTranslation` (`src/core/trans/engines/trans_deepl.py`)

- エンジン名: `deepl`
- 認証: 環境変数 `DEEPL_API_OAUTH` を `get_authentication_key()` 経由で使用する。
- 初期化:
  - `DeepLClient` を生成し、`_inst` setter 内の `_get_usage()` でクォータを取得する。
  - クライアント登録時に利用可否を無条件で `True` にしない。`limit_reached` が `False` の場合のみ利用可能にする。
  - 認証失敗時はクライアント／使用量／利用可否を未初期化状態へ戻し、`TranslateExceptionError` を送出する。
- 言語コード変換:
  - `Language` 定数から `_source_codes` / `_target_codes` を生成する。
  - 両マッピングが既に生成済みなら再生成せずデバッグログを出す。
    - リージョン付き定数は現在の互換処理に従いスキップまたはエイリアスへ変換する。
  - 中国語の互換エイリアス `zh-CN` / `zh-TW` はソースコードを `ZH` に正規化し、ターゲットコードは `zh-Hans` / `zh-Hant` 相当へ割り当てる。
  - 通常のターゲット言語にはデフォルトリージョン上書き（de/en/es/fr/pt/zh）が適用される。
- 翻訳:
  - `src_lang` / `tgt_lang` をマッピングで DeepL形式へ変換し、未指定ソースは `None` を渡す。
  - 未対応言語は `NotSupportedLanguagesError`。
  - `TextResult` 単体またはリストを受け入れ、リストの場合は先頭要素を使用する。
  - 戻り値の検出ソース言語を小文字へ正規化し、metadata に `"engine": "deepl"` を格納する。
- 例外分類:
  - `QuotaExceededException` -> `TranslationQuotaExceededError`（利用可否を `False` にする）
  - `TooManyRequestsException` -> `TranslationRateLimitError`
  - `AuthorizationException` / `ConnectionException` / `DeepLException` / 不正な引数型 -> `TranslateExceptionError`
- クォータ:
  - `_get_usage()` は同期API呼び出しのため `asyncio.to_thread()` 越しに実行する。
  - 使用量の `count` / `limit` を `CharacterQuota` に設定し、クォータAPIがあるため `is_quota_valid=True` を返す。
  - APIで値が返らない場合は使用文字数を `0`、上限を `500000` とする。
  - `_usage` 未設定時は `TranslateExceptionError`。
  - バージョンが `_EXPECTED_DEEPL_VERSION = "1.33.0"` と異なる場合は起動時に警告する。
  - `close()` はクライアント、使用量、利用可否をリセットする。

### 3.2 `GoogleTranslation` (`src/core/trans/engines/trans_google.py`)

- エンジン名: `google`
- 認証: APIキー不要。`googletrans`互換クライアントを経由する。
- 初期化:
  - `AsyncTranslator(url_suffix=config.TRANSLATION.GOOGLE_SUFFIX)` を生成する。
  - `supports_dedicated_detection_api=False`, `supports_quota_api=False`。
  - インスタンス生成時の `AttributeError` / `ValueError` は初期化失敗として `RuntimeError` を送出する。
- 言語検出:
  - 専用検出APIを持たないため `detect_language()` は `translation()` を再利用する。
  - 検出時点の翻訳文が `Result.text` として返され、上位でターゲット言語と一致する場合に再利用できる。
- 例外分類:
  - `InvalidLanguageCodeError`, `ResponseFormatError`, `GoogleError`, `HTTPConnectionError`, `HTTPError`, `HTTPTimeoutError`, `HTTPRedirection` -> `TranslateExceptionError`
  - `HTTPTooManyRequests` -> `TranslationRateLimitError`
- クォータ:
  - クォータAPIがないため `count=0`, `limit=0`, `is_quota_valid=False`, `limit_reached=False` を返す。
  - `is_available` は常に `True`。
  - `close()` は互換クライアントのHTTPクライアントを閉じ、内部インスタンスを `None` に戻す。

### 3.3 `GoogleCloudTranslation` (`src/core/trans/engines/trans_google_cloud.py`)

- エンジン名: `google_cloud`
- 認証方式:
  - `get_authentication_key()` により環境変数 `GOOGLE_CLOUD_API_OAUTH` を確認する。
  - APIキーがある場合は `APIKeySession` と `translate.Client(credentials=AnonymousCredentials(), _http=session)` を使用する。
  - APIキーがない場合は `translate.Client()` を使用し、`GOOGLE_APPLICATION_CREDENTIALS` 等のデフォルト認証を利用する。
  - APIキーはリクエストURLへ `?key=...` または `&key=...` として追加される。
  - `APIKeySession.request()` は `AuthorizedSession` をラップする。
- 初期化時確認:
  - `get_languages()` を同期呼び出しし、接続テストを行う。
  - `ImportError` はライブラリ不足の `RuntimeError`、認証例外は `TranslateExceptionError` へ正規化する。
  - それ以外の初期化例外はクライアント初期化失敗として `RuntimeError` を送出する。
- 言語検出:
  - `detect_language()` は `asyncio.to_thread()` 越しに `self._inst.detect_language()` を呼ぶ。
  - 戻りの `"language"` を小文字へ正規化し、`Result.text=None` を返す。
  - `"confidence"` が数値化できる場合は文字列へ変換し、失敗時は `"unknown"` とする。`metadata` に格納する。
  - `TooManyRequests` / `ResourceExhausted` はレート制限、その他の `GoogleAPIError` は一般翻訳例外として扱う。
- 翻訳:
  - `translate()` を `format_="text"`、ターゲット言語、ソース言語付きで呼ぶ。
  - 戻りから `translatedText` を必須項目として抽出し、`detectedSourceLanguage` はなければ指定ソース言語を使用する。
  - 検出言語がある場合は小文字へ正規化し、metadata に `"engine": "google_cloud"` を格納する。
  - `BadRequest` は `NotSupportedLanguagesError`。
  - `TooManyRequests` / `ResourceExhausted` は `TranslationRateLimitError`。
  - その他の `GoogleAPIError` は `TranslateExceptionError`。
- クォータ:
  - 直接取得APIがないため `count=0`, `limit=0`, `is_quota_valid=False` を返す。
  - `is_available` は常に `True`。
  - `close()` は内部クライアントを `None` に戻す。

## 4. `AsyncTranslator` の要点

- 互換クライアントは `googletrans.Translator` をラップし、必ず `raise_exception=True` を設定する。
- `service_urls` は `translate.google.<正規化済みsuffix>`。未登録のsuffixは `"com"`へフォールバックする。
- HTTPクライアントには指定されたタイムアウトを `httpx.Timeout` として渡す。
- 空文字は `GoogleError`、`len(text) >= 5000` の入力も `GoogleError` で拒否する。
- `googletrans`の戻りが `text` / `src` を文字列として持たない場合は `ResponseFormatError`。
- `close()` は内部HTTPクライアントの `aclose()` を呼ぶ。
- HTTPステータスは以下に分類する。
  - `httpx.TimeoutException` -> `HTTPTimeoutError`
  - `httpx.NetworkError` -> `HTTPConnectionError`
  - 429 -> `HTTPTooManyRequests`
  - 300〜399 -> `HTTPRedirection`
  - その他のHTTP失敗 -> `HTTPError`
  - `ValueError` -> `InvalidLanguageCodeError`
  - 予期しない例外はステータス文字列を抽出できれば該当ステータスへ正規化し、できなければ `GoogleError`
- 文字列に含まれるステータス抽出は `Unexpected status code "(?P<status>\d{3})"` を使用する。
- URLライク文字列では `detected_source_lang="und"` となるケースがあり、上位の `TransManager` で翻訳スキップ判定に使われる。

## 5. `TransManager` 連携時の重要点

- エンジン選択は設定された名前を `TransInterface.registered`へ動的解決し、初期化成功したエンジンだけを有効一覧へ追加する。
- 初期化時の `RuntimeError` / `TranslateExceptionError` は該当エンジンをスキップし、起動を継続する。
- 未登録名はロードせずクリティカルログを出す。
- アクティブ一覧はクラス変数 `_trans_engine` とインスタンス辞書 `_trans_instance` を常に整合させる。
- `fetch_engine_names()` / `update_engine_names()` はコマンド経由の切替に使用する。
- `update_engine_names()` は登録済み名だけを有効化し、未登録名は警告ログを出して無視する。
- `has_dedicated_detection_api=False` のエンジンは、検出時の `Result.text` を翻訳文として `TranslationInfo.translated_text`へ設定できる。
- 専用検出APIがないエンジンでは、検出段階の翻訳文がターゲット言語と一致すると翻訳処理を再利用する。
- 検出キャッシュと翻訳キャッシュを優先し、同一要求の重複処理を削減する。
- キャッシュキーとin-flightキーはソース文、ソース言語、ターゲット言語、エンジン名を含む。
- レート制限判定は `trans_info.engine.is_rate_limit_error()` に委譲し、適応バックオフへ連携する。
- レート制限クールダウン中は検出／翻訳を短絡する。ログは一定間隔に制限する。
- エンジンが `is_available=False` になった場合は `refresh_active_engine_list()` で先頭エンジンを除外し、次のエンジンへフォールバックできる。
- 有効エンジンがなくなった場合は翻訳をスキップし、原文を維持する。
- 翻訳失敗時は `TranslationInfo` の重要項目を破壊しない。特に `content`、`src_lang`、`tgt_lang`、`is_translate` を維持する。

## 6. テスト観点（最小セット）

- 各エンジンで認証未設定時の `is_available` と初期化ログ／例外が想定どおりになること。
- 未登録エンジン名、重複登録名、空名が登録を壊さないこと。
- `engine_attributes` の二重設定が `RuntimeError`になること。
- 未対応言語・クォータ枯渇・レート制限・一般API失敗が専用例外へ正規化されること。
- 検出API有無フラグと `detect_language()` の `Result.text` 仕様が一致すること。
- DeepLのリージョンコード変換、中国語互換エイリアス、クォータ取得を確認すること。
- Googleの `5000文字`境界、suffix正規化、strict `raise_exception`、HTTP分類を確認すること。
- Google CloudのAPIキー認証、デフォルト認証、検出confidence、BadRequest分類を確認すること。
- `AsyncTranslator`の429、タイムアウト、ネットワーク、リダイレクト、一般HTTP、レスポンス形式不正を確認すること。
- `close()` 後にクライアント、使用量、利用可否が再初期化可能な状態へ戻ること。
- クォータ枯渇時に有効エンジン一覧から除外され、次エンジンへフォールバックすること。
- 翻訳失敗時に `TranslationInfo` の重要フィールドが破壊されないこと。

## 7. 修正時チェックリスト

1. `fetch_engine_name()` の重複や空名で登録破壊が起きていないか。
2. `initialize()` で `engine_attributes` を二重設定していないか。
3. レート制限例外が `TranslationRateLimitError` に正しく正規化されているか。
4. 検出API有無フラグと `detect_language()` の実装が一致しているか。
5. DeepLの `_source_codes` / `_target_codes` 変換で言語コード欠落がないか。
6. DeepLのクライアント生成時に `_get_usage()` が実行され、クォータ枯渇時に利用可否が正しく更新されるか。
7. Googleの互換ラッパーでsuffix正規化、文字数境界、strict例外設定が維持されているか。
8. Google Cloudの認証分岐（APIキー / デフォルト認証）が壊れていないか。
9. Google Cloud検出時の`confidence`、翻訳時の`detectedSourceLanguage`抽出が維持されているか。
10. `close()` 実行後にインスタンス状態（`_inst`, usage, availability）が再初期化可能な形で戻るか。

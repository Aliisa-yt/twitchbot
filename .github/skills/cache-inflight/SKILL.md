---
name: cache-inflight
description: TranslationCacheManager と InFlightManager の TTL運用、重複抑止、競合制御の実装指針
keywords: [translation-cache, inflight, sqlite, ttl, deduplication, future-merge, concurrency]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は翻訳キャッシュと in-flight 重複防止の現在の実装ルールです。

## 1. TranslationCacheManager の責務

- `src/core/cache/cache_manager.py` の `TranslationCacheManager` は、SQLite（WALモード）で翻訳キャッシュと言語検出キャッシュを管理する。
- 翻訳キャッシュは `translation_cache`、言語検出キャッシュは `language_detection_cache` に保存する。
- スキーマ情報は `cache_metadata` の `schema_version` に保存し、現在のスキーマバージョンは `DB_SCHEMA_VERSION = 1` である。
- TTLに基づく期限切れ削除、エンジン別キャッシュと共通キャッシュのフォールバック、エンジン別LRU容量制限を行う。
- 翻訳キャッシュのヒット時に `last_used_at` と `hit_count` を更新する。
- キャッシュ統計取得と詳細エクスポートも担当する。

## 2. 初期化・終了・コンポーネント連携

- `SharedData.async_init()` が `TranslationCacheManager` と `InFlightManager` を生成し、`TransManager` に両方を注入する。
- `CacheServiceComponent.component_load()` はキャッシュDBを初期化し、辞書 `dic/translation_cache.dic` の定義済みキャッシュを登録する。
- 初期化成功時は `_is_initialized=True`、失敗時は `_is_initialized=False` とする。
- 初期化失敗時は `critical` または `exception` ログを出し、キャッシュ検索・登録は安全に no-op または `None/False` を返す。
- `component_teardown()` はDB接続を閉じ、初期化フラグを解除する。
- `InFlightServiceComponent` は `TranslationServiceComponent` と `CacheServiceComponent` に依存して初期化される。
- キャッシュメンテナンスは通常2時間間隔で実行する。最初の実行は20秒後に遅延される。

## 3. キャッシュキーと対象外条件

- キャッシュキー生成ユーティリティは `src/utils/cache_utils.py` の `CacheUtils` にある。
- 翻訳キャッシュでは原則として `generate_translation_hash_key(source_text, source_lang, target_lang, translation_profile, engine)` を使う。
- 内部ではUnicode正規化後の `source_text`、`source_lang`、`target_lang`、`translation_profile`、正規化したエンジン名をSHA-256で結合する。
- エンジン名は `None` と空文字を共通キャッシュとして扱う。
- `HASH_TEXT_LENGTH_LIMIT` は現在50文字で、`len(source_text) <= 50` の場合のみ対象となる。コメント上の「UTF-8文字数」は実装上の文字数とは一致しない可能性がある。制限が50以下ならその値を上限として扱う。
- `HASH_TEXT_LENGTH_LIMIT <= 0` は長さ制限なしを意味する。
- 空文字などの制御は呼び出し側の別条件（翻訳では `not trans_info.content` 等）で行う。`is_hash_eligible("")` は現実装では長さ制限内なので、単独ではキャッシュキー対象外にならない。
- 対象外の文字列は、候補キーが生成されてもキャッシュ検索・登録で即時no-opにする。

## 4. 翻訳キャッシュ検索・登録

- キャッシュ検索はエンジン指定ありの場合、エンジン別キーを最初に検索し、ミス時に共通キャッシュ（engine空文字）へフォールバックする。
- エンジンを指定しない検索は共通キャッシュのみを検索する。
- ヒット時はエントリの `last_used_at` を現在時刻へ更新し、`hit_count` をインクリメントする。
- エントリがTTL超過なら検索時に削除し、ヒットとして返さない。
- 翻訳キャッシュの登録は指定されたエンジン別エントリを保存する。
- `TransManager.write_translation_cache()` はエンジン別登録に加え、共通キャッシュへも同じ翻訳結果を登録する。成功判定はエンジン別登録の結果を返す。
- 再登録時は翻訳本文と `last_used_at` を更新し、既存の `created_at` と `hit_count` は維持する。
- 登録失敗は翻訳本体フローを止めず、ログを出して `False` を返す。

## 5. 言語検出キャッシュ

- 言語検出キャッシュのキーは正規化済みの元テキストそのもの（`normalized_source`）である。
- 設定から検出済みの言語を登録するときは、辞書由来定義を含めて既存エントリを上書きできる。
- デフォルトのconfidenceは `1.0` である。
- ヒット時は `last_used_at` のみ更新する。検索時のTTL超過エントリは削除して返さない。
- `INSERT OR REPLACE` を使う登録処理では、再登録時のタイムスタンプ更新を含む置換として扱う。

## 6. DB・TTL・容量制限

- DBファイルはリポジトリルートの `translation_cache.db`（`TRANSLATION_CACHE_DB_PATH`）である。
- SQLite接続は `check_same_thread=False`、`journal_mode=WAL`、`busy_timeout=5000`で設定する。
- DB操作は `_lock: asyncio.Lock` により直列化する。
- 設定クラス `models.config_models.Cache` のフィールドがキャッシュ設定の型と既定値を定義する。
- デフォルト値:
  - 翻訳キャッシュTTL: `TTL_TRANSLATION_DAYS_DEFAULT = 7`
  - 設定名 `TTL_TRANSLATION_DAYS`
  - 設定名 `TTL_LANGUAGE_DETECTION_DAYS = 30`
  - エンジンごとの最大件数: `MAX_ENTRIES_PER_ENGINE_DEFAULT = 200`
  - 設定名 `MAX_ENTRIES_PER_ENGINE`
- コンストラクタは各設定値を正の整数として検証し、不正または欠落時はクラス既定値へフォールバックする。
- リポジトリの `twitchbot.ini` の[CACHE]設定値は既定値とは異なる運用値を持つため、実装変更時はこの値を固定仕様として扱わない。
- 定期メンテナンスと検索時の検索は、`last_used_at` に基づいて期限切れを削除する。
- エンジンごとの件数が上限を超えると、`last_used_at` 昇順、同点なら `hit_count` 昇順で古いエントリを削除する。
- 共通キャッシュも `engine=""` として件数・LRU管理の対象になる。
- スキーマ変更時は既存DBとの互換性を確認し、列追加時の既定値を設計する。互換性維持後に `DB_SCHEMA_VERSION` を更新する。
- スキーマバージョン不一致は初期化を失敗させずwarningを出す。

## 7. InFlightManager の責務

- `InFlightManager` は `_inflight: dict[str, asyncio.Future[Result]]` に同一キーの共有Futureを保持する。
- 最初のリクエストがキーを登録し、同時リクエストは既存Futureの完了を待つ。
- Futureの完了時に待機側へ `Result` または例外を配布する。
- `INFLIGHT_TIMEOUT_SEC` の既定値は2.0秒である。
- `_lock: asyncio.Lock` を使って登録、結果配布、例外配布、teardown時の状態操作を直列化する。

## 8. 重複抑止フロー

1. `TransManager._build_translation_hash_key()` が言語ペアとエンジン名を含むキーを生成する。
2. `mark_inflight_start()` は未初期化または空キーなら `None` を返す。
3. キー未登録なら新しいFutureを作成し、呼び出し側を先行処理として返す。
4. キー登録済みなら既存Futureを `asyncio.wait_for(asyncio.shield(...), timeout=2.0秒)` で待つ。
5. 先行処理が翻訳成功すると `store_inflight_result()` がFutureへ `Result` を設定する。
6. 翻訳失敗時は `store_inflight_exception()` がFutureへ例外を設定する。
7. 待機側は共有結果を翻訳本文へ反映し、重複翻訳を発生させない。
8. 結果・例外配布時はキーを辞書から削除する。

## 9. タイムアウト・キャンセル・終了

- 待機側のタイムアウトでは待機側のみが `TimeoutError` を受け取る。共有Futureをキャンセルせず、待機側実装側で現在のエントリが同じFutureなら辞書から削除する。
- 従って、先行処理がタイムアウト後も動き続ける場合、遅れた待機側の期限切れによりキーが解放されることがある。
- 共有Futureがキャンセル済みの場合は待機側へキャンセル理由を含む `TimeoutError` に変換する。
- `store_inflight_result()` または `store_inflight_exception()` は、Futureが未完了なら結果または例外を配布し、完了済みなら警告する。
- `mark_inflight_start()` の待機側例外は `TransManager` が通常の翻訳失敗処理へ渡す。
- `component_teardown()` は未完了Futureをキャンセルし、辞書をクリアして初期化フラグを解除する。

## 10. テスト観点

- キャッシュ未初期化時に検索が `None`、登録が `False` を返すこと。
- 50文字を超えるテキスト、空キー、未初期化状態がキャッシュ対象外になること。
- エンジン別ヒット時にエンジン別エントリを更新すること。
- エンジン別ミス時に共通キャッシュへフォールバックすること。
- 翻訳登録時にエンジン別と共通キャッシュへ登録されること。
- 再登録時に `hit_count` と `created_at` を維持すること。
- 期限切れエントリが検索時と定期メンテナンス時の両方で削除されること。
- エンジン別LRU容量制限が正しく適用されること。
- 言語検出キャッシュの辞書上書きとTTL削除が正しく動くこと。
- 同一キー同時リクエストで翻訳実行が先行処理1回に集約されること。
- 待機側タイムアウト時に共有Futureがキャンセルされず、キー残留処理が安全であること。
- 先行処理例外が待機側へ伝播し、エントリが残らないこと。
- teardown後にDB接続とin-flight状態が解放されること。

## 11. 修正時チェックリスト

1. キャッシュ未初期化時に呼び出し側が安全に `None/False` を扱えるか。
2. DB例外時にBot全体へ例外を伝播させないか。
3. キャッシュキー生成対象外条件と空文字・長文の呼び出し条件に矛盾がないか。
4. in-flightタイムアウト時に共有Futureとキーのライフサイクルが説明通りか。
5. エンジン別キャッシュと共通キャッシュのフォールバックが意図通りか。
6. 再登録時に `created_at` と `hit_count` を不必要に消していないか。
7. TTL、LRU容量、定期メンテナンスの変更が設定値と整合しているか。

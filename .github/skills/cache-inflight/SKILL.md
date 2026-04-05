---
name: cache-inflight
description: TranslationCacheManager と InFlightManager の TTL運用、重複抑止、競合制御の実装指針
keywords: [translation-cache, inflight, sqlite, ttl, deduplication, future-merge, concurrency]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は翻訳キャッシュと in-flight 重複防止の実装ルールです。

## 1. TranslationCacheManager の責務

- SQLite（WALモード）で翻訳キャッシュと言語検出キャッシュを管理する。
- TTLに基づく期限切れ削除を行う。
- エンジン別キャッシュと共通キャッシュのフォールバックを扱う。
- ヒット時に `last_used_at` と `hit_count` を更新する。

## 2. 初期化と終了

- `component_load()` でDB初期化を行い、成功時に `is_initialized=True` にする。
- 初期化失敗時は `critical` ログを出し、利用側はキャッシュ未使用で継続できる設計にする。
- `component_teardown()` でDB接続を安全に閉じる。

## 3. キャッシュ検索方針

- キャッシュキーは `CacheUtils.generate_translation_hash_key()` で生成する（定義: `src/utils/cache_utils.py`）。
  - source_text のキャラクタ数が `HASH_TEXT_LENGTH_LIMIT`（現犰値: 50）を超える場合は `None` を返し、キャッシュ対象外となる。
  - 空文字・短すぎるテキストもこの判定で除外される場合がある。
- キャッシュキー生成対象外の文字列は保存・検索しない。
- エンジン指定ありでミスした場合は共通キャッシュ（engine空）へフォールバックする。
- 期限切れ判定は検索時にも実施し、見つかった古いデータを除去する。

## 4. DB運用上の注意

- SQLite は WAL モード前提で、読み取りと書き込みの競合を緩和する。
- DBファイルはリポジトリルート直下の `translation_cache.db`（定数: `TRANSLATION_CACHE_DB_PATH`）。
- TTL デフォルト値（クラス定数）:
  - 翻訳キャッシュ: `TTL_TRANSLATION_DAYS_DEFAULT = 7` 日。
  - 言語検出キャッシュ: `TTL_LANGUAGE_DETECTION_DAYS_DEFAULT = 30` 日。
  - エンジンごとの最大エントリ数: `MAX_ENTRIES_PER_ENGINE_DEFAULT = 200`。
- TTLメンテナンスと通常検索が衝突しないよう、更新順序とロック範囲を固定する。
- スキーマ更新が必要な変更では、既存DBとの後方互換性（列追加、既定値）を先に確認する。スキーマ変更時は `DB_SCHEMA_VERSION` を更新する。
- キャッシュ保存失敗は warning/error ログに留め、翻訳本体フローを止めない。

## 5. InFlightManager の責務

- 同一キャッシュキーの同時翻訳をFutureで合流させ、重複翻訳を防ぐ。
- 先行リクエスト完了時に待機側へ結果または例外を配布する。
- タイムアウトやキャンセル時に in-flight 状態を解放する。

## 6. 競合と例外ハンドリング

- `asyncio.Lock` で `_inflight` およびDB操作の競合を抑制する。
- `component_teardown()` では未完了Futureをキャンセルし、内部状態をクリアする。
- 空キー（`None`/空文字）は早期リターンし、警告ログを残す。

## 7. データフロー（重複抑止）

1. 呼び出し側がキャッシュキーを生成して in-flight 登録を試みる。
2. 先行処理が存在すれば既存 Future を待機し、存在しなければ先行処理になる。
3. 先行処理は翻訳実行後に結果を Future へ設定し、必要ならキャッシュへ保存する。
4. 待機側は同じ結果または例外を受け取り、重複翻訳を発生させない。
5. 完了・失敗・タイムアウトのすべてで in-flight エントリを解放する。

## 8. テスト観点（最小セット）

- 同一キー同時リクエストで翻訳実行が1回に集約されること。
- 先行処理例外が待機側へ正しく伝播し、キー残留しないこと。
- 期限切れデータが検索時に除去され、古い値を返さないこと。
- エンジン別ミス時に共通キャッシュへフォールバックすること。
- teardown 後に DB 接続と in-flight 状態が解放されること。

## 9. 修正時チェックリスト

1. キャッシュ未初期化時に呼び出し側が安全に `None` ハンドリングできるか。
2. DB例外時にBot全体へ例外を伝播させないか。
3. in-flight タイムアウト後にキー残留がないか。
4. フォールバック検索の挙動が意図通りか。
5. TTLや容量制限変更時にメンテナンス処理との整合が取れているか。

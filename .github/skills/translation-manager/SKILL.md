---
name: translation-manager
description: TransManager のエンジン管理、言語検出、キャッシュ/in-flight連携、バックオフ制御の実装指針
keywords: [transmanager, translation, language-detection, engine-fallback, cache, inflight, adaptive-backoff, rate-limit]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `TransManager` を扱う際の運用ガイドです。
翻訳エンジンの切替、言語検出、キャッシュ、in-flight 協調、レート制限緩和を含みます。

## 1. 責務

- 設定から翻訳エンジンを初期化し、有効エンジン一覧を管理する。
- 言語検出を実行し、翻訳要否を `TranslationInfo` に反映する。
  - `TranslationInfo` のフィールドは `src/models/translation_models.py` で定義: `content`, `src_lang`, `tgt_lang`, `translated_text`, `is_translate`, `engine`。
- 翻訳を実行し、必要に応じてキャッシュへ保存する。
- レート制限を検出し、指数バックオフで一時的に翻訳を抑制する。
- engine無効化時にアクティブ一覧を更新し、次エンジンへフォールバック可能にする。
- 有効エンジンが1つも残らない場合、翻訳をスキップして原文のまま上位へ返す（`is_translate` は維持）。

## 2. 初期化とエンジン管理

- `initialize()` で `config.TRANSLATION.ENGINE` を順に解決する。
- 未登録エンジン名はロードしない（`critical` ログ）。
- 初期化成功エンジンのみクラス変数のエンジン一覧へ登録する。
- コマンド経由の切替は `fetch_engine_names()` / `update_engine_names()` を使用する。

## 3. 言語検出の注意点

- 空文字は検出対象外として `False` を返す。
- 検出キャッシュヒット時はその結果を優先する。
- 検出専用APIがないエンジンは、検出段階で翻訳文が返ることがある。
- `und`（判定不能）の扱いなど、URLライク文字列の例外ケースを維持する。

## 4. レート制限対策

- レート制限判定はエンジン実装の `is_rate_limit_error()` に委譲する。
- 連続発生時は指数バックオフでクールダウン時間を増やす。
  - 基準クールダウン: `1.0` 秒（`ADAPTIVE_LIMITER_BASE_COOLDOWN_SEC`）。
  - 最大クールダウン: `30.0` 秒（`ADAPTIVE_LIMITER_MAX_COOLDOWN_SEC`）。
  - リセットまでの対待時間: `60.0` 秒（`ADAPTIVE_LIMITER_RESET_SEC`）。
- クールダウン中は翻訳を短絡して過負荷を回避する。
- ログは一定間隔に制限し、同一警告の連打を避ける。

## 5. キャッシュ・in-flight 連携

- 可能な場合は翻訳キャッシュを先に引き、同一要求の重複処理を削減する。
- in-flight 管理で同一キーの同時翻訳を合流させる。
- 例外時も in-flight 状態を解放する実装を維持する。

## 6. テスト観点（最小セット）

- エンジン初期化時に無効/未知エンジンがスキップされ、起動継続できること。
- 検出専用APIなしエンジンで、検出段階の翻訳文取り扱いが想定どおりであること。
- レート制限例外発生時にバックオフが適用され、クールダウン中に短絡されること。
- キャッシュヒット・in-flight 合流で重複翻訳が抑制されること。
- 失敗系で `TranslationInfo` の重要フィールド（`content`, `tgt_lang`, `is_translate`）が破壊されないこと。
- 有効エンジンが全て無効になった場合に、翻訳をスキップし原文を維持するか warning ログが出ること。

## 7. 修正時チェックリスト

1. エンジン一覧の更新がクラス変数と整合しているか。
2. 検出失敗/翻訳失敗時に `TranslationInfo` が破壊的に壊れないか。
3. レート制限時にバックオフが働き、連打呼び出しを抑制できるか。
4. キャッシュキー生成条件が変更時も一貫しているか。
5. 例外時のログレベル（warning/error/critical）が妥当か。

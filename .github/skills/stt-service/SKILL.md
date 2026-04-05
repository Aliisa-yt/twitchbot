---
name: stt-service
description: STTServiceComponent と STTManager の初期化、録音〜転送フロー、停止制御の実装指針
keywords: [stt, speech-to-text, recorder, processor, forwarding, mute, threshold, teardown]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は STT 機能（`STTServiceComponent` / `STTManager`）を変更する際の指針です。

## 1. 責務分担

- `STTServiceComponent`
  - コンポーネントライフサイクルを管理する。
  - 設定有効時のみ STT を初期化する。
  - STT結果をチャット表示・TTS転送へ橋渡しする。
- `STTManager`
  - エンジン初期化、録音監視、セグメント処理タスクを管理する。
  - ミュートや閾値調整など実行時制御を提供する。

## 2. ロード/ティアダウン

### `component_load()`
- `self.config.STT.ENABLED` を評価し、有効時のみ `stt_manager.async_init()` を呼ぶ。
- 設定欠落は `AttributeError` を捕捉し、警告ログでスキップする。

### `component_teardown()`
- `with suppress(AttributeError)` で `stt_manager.close()` を安全に呼ぶ。
- STT未初期化ケースでもシャットダウン全体を妨げない。

## 3. STT結果転送

- 空文字結果は無視する。
- チャット送信は開発用フラグで明示的に有効化された場合のみ行う。
- 通常はコンソール出力し、必要に応じて TTS へ転送する。
- TTS転送時は音声パラメータ欠落（例: `KeyError`）を許容して警告ログにする。

## 4. STTManager 側の重要点

- エンジン名から `STTInterface.registered` を解決し、失敗時は `critical` ログで中断する。
  - サポートエンジン: `google_cloud_stt` (`GoogleCloudSpeechToText`)、`google_cloud_stt_v2` (`GoogleCloudSpeechToTextV2`)。
- 録音のサンプルレート・チャンネル数は固定値（`_FIXED_SAMPLE_RATE = 16000` Hz、`_FIXED_CHANNELS = 1`）。
  - 設定有効時の楽曲はこの値を前提にコーディングする。
- `STTRecorder` と `STTProcessor` を組み立て、プロセッサタスクを起動する。
- `close()` では terminate event と queue shutdown を先に行い、残タスクを回収する。
- マイク環境不備など `RuntimeError` は warning で扱い、Bot全体停止を避ける。

## 5. データフロー（録音〜転送）

1. `STTRecorder` が音声セグメントを生成して入力キューへ積む。
2. `STTProcessor` がキューから取り出し、エンジン `transcribe()` を実行する。
3. `STTResult` が空文字でなければ `STTServiceComponent._on_stt_result()` へ返す。
4. 結果をログ/コンソールへ出力し、条件に応じて TTS 転送する。
5. シャットダウン時は terminate event により処理ループを停止し、キュー解放を完了させる。

## 6. 失敗時の設計方針

- 初期化失敗は STT 機能のみ無効化し、Bot 全体は継続する。
- 転写失敗はセグメント単位で隔離し、後続セグメント処理を継続する。
- 未初期化状態での操作（mute/threshold など）は例外または no-op を契約に合わせて統一する。
- 終了処理の例外は握りつぶさず warning 以上で可視化し、プロセス終了の妨げにしない。

## 7. マイクデバイス消失・復帰時の方針

### 7.1 消失時（抜線・OS側の無効化・ドライバ瞬断）
- `STTRecorder` は入力コールバック停止またはストリーム消失を監視し、異常を検知したら warning を出す。
- 検知後は即時に STT 全体を停止せず、録音入力だけを再接続対象として扱う。
- `STTProcessor` は終了させず、既存キュー処理を継続可能な状態を保つ。
- 再接続失敗は warning で継続記録し、Bot 全体停止に波及させない。

### 7.2 復帰時（デバイス再接続・OS復旧）
- `STTRecorder` の watchdog が一定間隔で再接続を試行し、成功時は info ログを残して監視を継続する。
- 復帰は原則自動で行い、`STTManager.async_init()` の再実行を必須にしない。
- 復帰後は通常のセグメント生成と `STTProcessor` への転送が再開される前提を維持する。

### 7.3 デバイス選択とフォールバック
- `INPUT_DEVICE` が固定名/固定インデックスの場合は、その指定先で再接続を試みる。
- `INPUT_DEVICE=default`（または未指定）の場合は利用可能デバイス候補へフォールバック可能な実装を維持する。
- 入力ストリーム再開不能時は、利用可能な入力デバイス一覧を警告ログへ出し、運用側で再設定可能にする。

## 8. テスト観点（最小セット）

- STT 無効設定で `async_init()` が呼ばれないこと。
- STT 初期化失敗時に他コンポーネント起動を阻害しないこと。
- STT 結果が空文字のとき転送されないこと。
- TTS 転送時に音声パラメータ欠落が warning で処理継続されること。
- `close()` 実行後に録音/処理タスクとキューが残留しないこと。
- 入力コールバック停止時に watchdog が再接続を試行すること。
- マイク消失中に再接続失敗ログを出しつつ、Bot 全体が継続すること。
- マイク復帰後に再接続成功ログが出て、セグメント処理が再開すること。
- `INPUT_DEVICE=default` 時に再接続で候補デバイスへフォールバックできること。

## 9. 修正時チェックリスト

1. STT無効設定時に安全にスキップできるか。
2. STT初期化失敗時でも他コンポーネントが起動継続できるか。
3. 終了時に録音/処理タスクがリークしないか。
4. STT→TTS転送の条件分岐が意図通りか。
5. `mute` / `threshold` 操作が未初期化時に適切に失敗または保持されるか。
6. マイクデバイス消失時に STT 機能のみ degraded 状態になり、全体停止しないか。
7. 復帰時に `STTRecorder` の自動再接続だけでパイプラインが再開するか。

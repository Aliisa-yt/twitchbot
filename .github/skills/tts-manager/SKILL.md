---
name: tts-manager
description: TTSManager のキュー連携、合成/再生/削除タスク、障害分離と終了処理の実装指針
keywords: [tts-manager, synthesis-queue, playback-queue, file-cleanup, background-task, cancellation, shutdown]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `TTSManager` 周辺（`ParameterManager` / `SynthesisManager` / `AudioPlaybackManager`）の
運用・拡張時の注意点をまとめたものです。

## 1. 構成

- `synthesis_queue`: 音声合成待ちキュー。
- `playback_queue`: 再生待ちキュー（`ExcludableQueue` を使いチャットクリア時に特定エントリを除外できる）。
- `deletion_queue`: 一時音声ファイル削除キュー。
- `task_terminate_event`: 終了シグナル（`asyncio.Event`）。
- `background_tasks`: 合成・再生・ファイル掃除の常駐タスク集合（`set[asyncio.Task[None]]`; タスク参照を強参照で保持しGCを防ぐ）。
- `ParameterManager`: ユーザー種別（streamer/moderator/vip/subscriber/others/system）に応じてTTSパラメータ（言語・エンジン・キャスト・音量/速度/音調など）を選択する責務を担う。TTSManagerから分離されており、コンポーネント側で重複ロジックを持たない。

## 2. 初期化

- `initialize()` は二重起動を避ける（既存タスクがあれば再初期化しない）。
- 背景タスクは以下を起動する。
  - `tts_processing_task`
  - `playback_queue_processor`
  - `audio_file_cleanup_task`
- TTSエンジン登録は `Interface` の登録情報を使い、`EngineContext` は `SynthesisManager._create_handler_map()` で生成して各エンジンへ渡す。

## 3. 終了処理

- `task_terminate_event` をセットしてループ停止を通知する。
- 各キューへ `shutdown()` を呼び、待機中タスクを解放する。
- 背景タスクを待ち合わせ、未完了タスクは警告ログで可視化する。
- 最後に `background_tasks` をクリアして再利用可能状態に戻す。

## 4. 運用上の注意

- 音声パラメータ選択は `ParameterManager` に委譲し、コンポーネント側で重複ロジックを持たない。
- キューに投入する前に `prepare_tts_content()` で正規化し、`None` を許容する。
- 再生中断やチャットクリアと干渉するため、再生キュー操作は順序を守って行う。

## 5. データフロー（投入〜削除）

1. 呼び出し側が `TTSParam` を生成し、`synthesis_queue` へ投入する。
2. 合成タスクが音声データを生成し、再生用データを `playback_queue` へ送る。
3. 再生タスクが再生処理を実行し、完了後に削除対象を `deletion_queue` へ送る。
4. 掃除タスクが一時音声ファイルを削除し、残留ファイルを防ぐ。
5. 終了時は terminate event と queue shutdown で全ループを停止する。

## 6. 失敗時の設計方針

- 合成失敗は1メッセージ単位で隔離し、再生キューへ不正データを流さない。
- 再生失敗や削除失敗は warning/error で記録し、後続処理を止めない。
- シャットダウン中の `CancelledError` は想定内として扱い、タスク回収を優先する。
- キュー停止後の put/get 例外はリーク検知ログを残しつつ終了パスを維持する。

## 7. テスト観点（最小セット）

- `initialize()` 二重呼び出し時に背景タスクが重複起動しないこと。
- 合成失敗時に再生キューへ投入されないこと。
- チャットクリア/停止時に再生中断とキュー掃除の順序が保持されること。
- `close()` 後に `background_tasks` が空になり再初期化可能であること。
- 削除キュー滞留時にログで観測可能なこと。

## 8. 修正時チェックリスト

1. 新規タスク追加時に `close()` で確実に終了できるか。
2. キュー停止処理でハングしないか。
3. 合成失敗時に再生タスクへ不正データが流れないか。
4. ファイル削除キューが詰まったときのログ可観測性があるか。
5. 音声設定変更が既存ユーザータイプ選択に影響しないか。

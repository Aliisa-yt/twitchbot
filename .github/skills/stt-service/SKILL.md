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

- 空文字または空白のみの結果は無視する。
- `CONFIDENCE_THRESHOLD` と結果の confidence の両方が設定されている場合、confidence が閾値未満の結果を破棄する。
- `dic/stt_result_ignore_words.dic`（`DICTIONARY.PATH` があればその配下）にあるフレーズを結果が含む場合も破棄する。照合は大文字小文字を区別する部分文字列一致。
- `STT.DEBUG=True` の場合は結果テキストと confidence をコンソールへ表示し、チャット送信と TTS 転送は行わない。
- 通常モードでは結果をチャットへ送信する。加えて `STT.FORWARD_TO_TTS` が bool の `True` の場合に限り、`stt_message` イベントを通じて後続処理へ渡す。`False` や `None` では転送しない。

## 4. STTManager 側の重要点

- `STTServiceComponent` が `STT.ENABLED` を確認して初期化を呼ぶ。`STTManager.async_init()` 自体は `ENABLED` を判定しない。
- エンジン名から `STTInterface.registered` を解決し、未登録時は `critical` ログを出して初期化を中断する。
  - サポートエンジン: `google_cloud_stt` (`GoogleCloudSpeechToText`)、`google_cloud_stt_v2` (`GoogleCloudSpeechToTextV2`)。
- 録音のサンプルレート・チャンネル数は固定値（`_FIXED_SAMPLE_RATE = 16000` Hz、`_FIXED_CHANNELS = 1`）。`STT.SAMPLE_RATE` と `STT.CHANNELS` は現在使われない。
- `STTRecorder` と `STTProcessor` を組み立て、録音開始後にプロセッサタスクを起動する。`GENERAL.TMP_DIR` が未設定の場合や Silero VAD モデルが見つからない場合など、セットアップ中の一部の `RuntimeError` は `async_init()` から呼び出し元へ伝播する。
- エンジン初期化時の `RuntimeError` は warning を出して戻る。入力監視開始時の `RuntimeError` は manager が error ログを出して戻り、manager は無効状態のままになる。
- `close()` は terminate event と queue shutdown を先に行い、recorder の close が正常終了した場合はプロセッサタスクを最大 2 秒待機する。残ったタスクをキャンセルして回収する。recorder の close が例外を送出すると、その後のタスク回収は実行されず例外が伝播する。
- queue shutdown は通常の非即時 shutdown であり、キュー内の未処理セグメントや一時音声ファイルを明示的には purge しない。close 後の同じ manager/queue の再利用もできないため、manager instance は一度の起動ライフサイクルで使う。
- `set_thresholds()` と `set_vad_threshold()` は recorder 未初期化時に `RuntimeError` を送出する。`set_mute()` は初期化前でも値を保持するが、初期化時に設定の `STT.MUTE` が適用される。

## 5. データフロー（録音〜転送）

1. `STTRecorder` が音声セグメントを生成して入力キューへ積む。
2. `STTProcessor` がキューから取り出し、エンジン `transcribe()` をセグメントごとに 1 回だけ実行する。失敗したセグメントをアプリ側で自動再送せず、エラーを上位へ返して次のセグメントへ進む。`STTRetriableError` は同一セグメントの即時再試行を意味せず、エンジンを利用可能なまま次の独立したリクエストを許可する分類とする。SDK 内部の再試行は [Google Cloud API 例外処理 SKILL](../google-cloud-api-exception/SKILL.md) に従い、API / メソッドごとに別途確認する。
3. 転写結果があれば、空文字かどうかにかかわらず `STTServiceComponent._on_stt_result()` を呼ぶ。空文字の除外と confidence/辞書フィルタは component 側で行う。
4. 採用結果は debug モードならコンソール表示のみ、通常モードならチャット送信し、設定に応じてイベント経由で転送する。
5. 各セグメントの一時音声ファイルは処理後に削除する。
6. シャットダウン時は terminate event と queue shutdown により処理ループを停止し、録音と残タスクを回収する。現在の close は未処理キュー項目を drain/purge しないため、終了時に backlog がありうる運用では未処理セグメントの一時ファイル cleanup を別途考慮する。

## 6. 失敗時の設計方針

- 未登録エンジン、エンジン初期化失敗、入力監視開始失敗は manager を有効化せずに戻る。セットアップ中の未処理例外は `STTServiceComponent.component_load()` では `AttributeError` 以外を捕捉しないため、コンポーネントのロード失敗として呼び出し元へ伝播しうる。
- 転写処理中の STT 例外や予期しない例外はセグメント単位で処理を終了し、次のセグメントへ進む。一方、結果 callback から例外が送出されると processor ループは終了するため、callback 側で失敗を隔離する必要がある。
- 未初期化状態の操作: mute は値を保持し、threshold/VAD threshold は `RuntimeError` を送出する。
- `STTManager.close()` は recorder の close 例外を包括的には捕捉しない。component teardown も `AttributeError` 以外を捕捉しないため、終了処理の例外が呼び出し元へ伝播する場合がある。processor タスクの失敗は終了時に warning ログへ記録する。
- close は queue shutdown を解除せず、キュー内の未処理セグメントとその一時ファイルを削除しない。manager を再初期化する設計や終了時の backlog がある場合、この制約を考慮する。

## 7. マイクデバイス消失・復帰時の方針

### 7.1 消失時（抜線・OS側の無効化・ドライバ瞬断）
- `STTRecorder` は監視中に 1 秒間隔で入力状態を確認する。ストリーム消失、または 2 秒を超える入力コールバック停止を検知すると warning を出す。
- 検知後は即時に STT 全体を停止せず、録音入力だけを再接続対象として扱う。
- `STTProcessor` は終了させず、既存キュー処理を継続可能な状態を保つ。
- 再接続は最低 3 秒の間隔を空けて試行する。失敗は warning で記録し、再接続が成功するまで監視を継続する。

### 7.2 復帰時（デバイス再接続・OS復旧）
- `STTRecorder` の watchdog が再接続を試行し、成功時は info ログを残して監視を継続する。
- 復帰は原則自動で行い、`STTManager.async_init()` の再実行を必須にしない。
- 復帰後は通常のセグメント生成と `STTProcessor` への転送が再開される前提を維持する。

### 7.3 デバイス選択とフォールバック
- `INPUT_DEVICE` が固定名/固定インデックスの場合は、その指定先だけで再接続を試みる。数字の文字列はデバイス index に変換される。
- `INPUT_DEVICE=default`（または未指定）の場合はシステム既定デバイスを先に試し、失敗した場合は入力可能デバイスの index を順に試す。
- 初回ストリーム開始または再接続に失敗した場合、利用可能な入力デバイス一覧を warning ログへ出し、運用側で再設定できるようにする。

## 8. テスト観点（最小セット）

- STT 無効設定で `async_init()` が呼ばれないこと。
- STT 初期化失敗時に他コンポーネント起動を阻害しないこと。
- 空文字、confidence 閾値未満、無視辞書フレーズ一致の結果がチャット/TTSへ送られないこと。
- debug モードではコンソール表示のみ、通常モードではチャット送信し、`FORWARD_TO_TTS=True` の場合にのみ転送イベントが発行されること。
- STT ドメイン転写失敗時に同一セグメントを再送せず、後続セグメントの処理へ進むこと。
- `close()` 実行後に録音/処理タスクが残留しないことと queue が shutdown されることを確認し、未処理セグメントや一時ファイルが残りうる現在の挙動も検証対象に含めること。
- 入力コールバック停止またはストリーム消失時に watchdog が再接続を試行すること。
- マイク消失中に再接続失敗ログを出しつつ、Bot 全体が継続すること。
- マイク復帰後に再接続成功ログが出て、セグメント処理が再開すること。
- `INPUT_DEVICE=default` 時に既定デバイス失敗後、候補デバイスへフォールバックできること。

## 9. 修正時チェックリスト

1. STT無効設定時に安全にスキップできるか。
2. エンジン/入力監視の失敗と未処理のセットアップ例外を区別し、component load の結果が適切か。
3. 終了時に録音/処理タスクがリークしないか。
4. debug/通常モード、confidence/辞書フィルタ、STT→チャット/TTS転送の条件分岐が意図通りか。
5. `mute` / `threshold` 操作の未初期化時の挙動と、初期化時の `STT.MUTE` 適用が意図通りか。
6. マイクデバイス消失時に STT 機能のみ degraded 状態になり、全体停止しないか。
7. 復帰時に `STTRecorder` の自動再接続だけでパイプラインが再開するか。

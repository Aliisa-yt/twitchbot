name: tts-engine-spec
description: src/core/tts/engines のTTSエンジン契約、合成パラメータ仕様、例外設計ガイド
keywords: tts-engine, ttsinterface, exception-mapping, parameter-spec

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `src/core/tts/engines/` 配下のTTSエンジンクラスを変更・追加する際の実装ガイドです。
対象は主に `VoiceVox` / `CoeiroInk` / `CoeiroInk2` / `CevioAI` / `CevioCS7` /
`BouyomiChanSocket` / `GoogleText2Speech` と、VOICEVOX互換向け共通基盤 `VVCore` です。

## 1. 責務と共通契約

- すべてのエンジンは `Interface` を実装し、`fetch_engine_name()` で一意名を返す。
- `Interface.__init_subclass__()` により、エンジンクラスは自動登録される。
- `initialize_engine()` は必ず `super().initialize_engine(tts_engine, context)` を呼び、`SERVER/TIMEOUT/EARLY_SPEECH/AUTO_STARTUP/EXECUTE_PATH` を `_TTSConfig` に反映する。
- `speech_synthesis()` の責務は「音声生成」+「必要なら `ttsparam.filepath` 設定」+「必要なら `play()` 呼び出し」。
- ファイル生成型エンジンは `create_audio_filename()` と `save_audio_file()` を使用し、フォーマット制約と例外正規化を `Interface` 側へ委譲する。
- `linkedstartup=True` の場合、`handler.execute` / `handler.termination` 経由で外部プロセス起動・停止が行われる。

## 2. インターフェース契約と共通仕様

- `fetch_engine_name()`:
	- `Interface.register_engine()` のキーになるため、空文字や重複名は登録衝突を引き起こす。
	- `VVCore` の実装は空文字（抽象基底用途）であり、実運用クラスは必ずオーバーライドする。
- `create_audio_filename(prefix=None, suffix="wav")`:
	- `suffix` は `wav`/`mp3` のみ対応。未対応は `TTSNotSupportedError`。
	- 保存先は `EngineContext.audio_save_directory`（`src/core/tts/tts_interface.py` で定義）。
- `save_audio_file(filepath, data)`:
	- `bytes` または `BytesIO` のみ受理。
	- 既存ファイルは `TTSFileExistsError`、作成失敗は `TTSFileCreateError` に正規化。
- `play(ttsparam)`:
	- `EngineContext.play_callback` が `initialize_engine()` で設定済みであることを前提に、再生キューへ連携する。
- `_TTSConfig`:
	- `SERVER` は `http(s)://host:port` を許容し、ポート範囲は `49152-65535`。
	- `TIMEOUT<=0` や不正値はデフォルト `10.0` 秒へフォールバック。

## 3. エンジン別仕様

### 3.1 `VVCore` (`src/core/tts/engines/vv_core.py`)

- VOICEVOX互換HTTPエンジンの共通基盤。
- `async_init()` では `/version`（既定）をポーリングし、`ENGINE_STARTUP_TIMEOUT` 内で接続可能になるまで待機する。
- `_api_request()`:
	- `get` / `post` のみ受理（その他は `ValueError`）。
	- `model` 指定時は `dataclasses_json` で逆シリアライズし、整合しない応答は `AsyncCommError`。
- `speech_synthesis()`:
	- `api_command_procedure()` の戻りが `bytes` かつ非空であることを要求する。
	- 空データは `TTSNotSupportedError`（この例外は `speech_synthesis()` 内で握りつぶさず、上位へ送出される）。
	- `TTSFileError` / `AsyncCommError` / `JSONDecodeError` / `OSError` / `TypeError` / `RuntimeError` はログ化して終了する。
- パラメータ正規化:
	- `int` は百分率（100→1.0）として扱い、`float` はそのまま採用。
	- 範囲外はクランプし、`None` は既定値を採用。
- 話者指定:
	- `cast` は `"数値ID"` / `"話者名|スタイル名"` / `"話者名"`（ノーマル補完）をサポート。
	- 変換結果は `id_cache` にキャッシュされる。

### 3.2 `VoiceVox` (`src/core/tts/engines/voicevox.py`)

- API:
	- `POST /audio_query` -> `POST /synthesis` の2段階で音声合成。
	- 初期化時に `GET /speakers` で話者一覧を取得し、設定上のキャストを `POST /initialize_speaker` で事前ロードする。
- パラメータ:
	- `speedScale` は `EARLY_SPEECH` と本文長に応じて加速補正。
	- `pitchScale`/`intonationScale`/`volumeScale` は `VVCore.PARAMETER_RANGE` で正規化。
	- `pauseLength`/`pauseLengthScale`/`outputSamplingRate`/`outputStereo` は固定既定値を設定。

### 3.3 `CoeiroInk` (`src/core/tts/engines/coeiroink.py`)

- `VoiceVox` を継承したCOEIROINK(v1)向けラッパ。
- 合成フローは VOICEVOX 互換（`audio_query` + `synthesis`）。
- `pauseLength` 系は設定せず、`pre/postPhonemeLength` とサンプリング関連のみ固定値を適用する。

### 3.4 `CoeiroInk2` (`src/core/tts/engines/coeiroink_v2.py`)

- VOICEVOX互換ではなく v2 API専用フローを持つ。
- API:
	- `POST /v1/estimate_prosody` -> `POST /v1/predict_with_duration` -> `POST /v1/process`。
	- 起動判定コマンドは `/v1/engine_info` に切り替える。
- 話者解決:
	- `GET /v1/speakers` から `speaker_uuid` / `style_id` を構築。
	- `style_id` は現状 `0` 固定（外部指定変更を行わない）。
- 重要な互換性注意:
	- 2.12系GPU版で `pitch`/`intonation` を非既定値へ変更すると内部エラーが発生し得るため、`pitch_scale=0.0`・`intonation_scale=1.0` で固定している。

### 3.5 `CevioCore` / `CevioAI` / `CevioCS7`

- `CevioCore` はCOM経由の同期API基盤で、`speech_synthesis()` は `asyncio.to_thread()` で非同期化する。
- `CevioAI` は `cevio_type="AI"`、`CevioCS7` は `cevio_type="CS7"` を指定する薄い派生クラス。
- 接続:
	- Windows専用。非Windowsは初期化失敗（`False`）とする。
	- `linkedstartup` 時は `StartHost(True)` を呼び、終了時に `CloseHost(0)` を実行する。
- パラメータ:
	- castごとのプリセットを取得し、入力値は `preset` を既定として上書き適用。
	- `EARLY_SPEECH` 時は長文で `Speed` を補正（上限 60）。
- 出力:
	- `OutputWaveToFile()` でWAVを直接生成し、成功時のみ `ttsparam.filepath` を設定。

### 3.6 `BouyomiChanSocket` (`src/core/tts/engines/bouyomichan.py`)

- ファイルを生成しないソケット直送型エンジン。
- `BouyomiChanCommand.generation("talk", ttsparam)` でバイナリプロトコルを生成して送信する。
- 値域:
	- `speed: 50-300`, `tone: 50-200`, `volume: 0-100`, `voice_id: 0-65535`。
	- 未指定は `-1`（エンジン既定）を維持。
- `play()` は呼ばない（再生はBouyomiChanアプリ側が担当）。

### 3.7 `GoogleText2Speech` (`src/core/tts/engines/g_tts.py`)

- `gTTS` が返すMP3ストリームを `soundfile` でデコードし、float32 WAVとして保存する。
- `content_lang` が `None` の場合は `ValueError` として処理中断する。
- 音量:
	- `volume` が `None` または `100` の場合は無変換。
	- それ以外は `0-200` にクランプした係数で `numpy` ブロードキャスト乗算。
- `_ensure_float32_array()` / `_AudioData` でデータ型を検証し、異常型は `TypeError`。

## 4. 例外マッピング方針

- 共通（`Interface`）:
	- 不正フォーマット/データ型/ファイル操作失敗を `TTSExceptionError` 系へ正規化する。
- VOICEVOX互換系（`VVCore` 派生）:
	- 通信/レスポンス不整合は `AsyncCommError` に統一し、`speech_synthesis()` 側でログ化する。
	- 空音声データは `TTSNotSupportedError` を送出して異常系を明確化する。
- BouyomiChan:
	- コマンド生成失敗は `BouyomiChanCommandError`。
	- 通信失敗は `AsyncCommError` としてログ化。
- gTTS:
	- `gTTSError` と `soundfile` 例外は個別ログ化し、処理を安全に中断する。

## 5. `TTSManager` 連携時の重要点

- エンジン選択は `Interface.get_registered()` の登録情報を基準に行われる。
- `EngineContext` は `SynthesisManager._create_handler_map()` で生成され、`play_callback` と `audio_save_directory` を各エンジンへ渡す。
- ファイル生成型エンジンは `ttsparam.filepath` を必ず設定してから `play()` を呼ぶ。
- 非ファイル型（BouyomiChan）は `filepath` を使わない設計で、再生経路が別であることを前提にする。

## 6. テスト観点（最小セット）

- `VVCore`:
	- `_convert_parameters()` のクランプ/既定値適用、`_adjust_reading_speed()` の長文加速、`cast` 解決・キャッシュ、`_api_request()` のデシリアライズ失敗時 `AsyncCommError`。
- `GoogleText2Speech`:
	- `float32` 検証、`content_lang=None` の中断、`volume` 補正の有無、WAV保存と `play()` 連携。
- `CevioCore`:
	- OS分岐、COM接続失敗時の後始末、プリセット取得、WAV生成、速度補正上限。
- `BouyomiChanSocket`:
	- バイナリコマンド生成（値域クランプ）、不正コマンド、ソケット成功/失敗時の終了処理。

## 7. 修正時チェックリスト

1. `fetch_engine_name()` の重複・空名が登録競合を起こしていないか。
2. `initialize_engine()` で `super()` 呼び出しを欠落させていないか。
3. ファイル生成型エンジンで `ttsparam.filepath` 設定と `play()` 呼び出し順が崩れていないか。
4. `EARLY_SPEECH` の速度補正ロジック（VV系/CeVIO系）で想定外の上限超過が起きていないか。
5. CoeiroInk2 の `pitch`/`intonation` 固定方針（内部エラー回避）が維持されているか。
6. BouyomiChan の値域クランプとバイナリ構造（`struct.pack` 順序）が維持されているか。
7. gTTS 経路で `float32` 前提と `soundfile` 書き出し仕様（WAV/FLOAT）が壊れていないか。


---
name: interface-spec
description: STT/翻訳/TTS interface の抽象契約、自動登録規約、例外設計の横断仕様
keywords: [interface, abstract-contract, auto-registration, stt, translation, tts, exception-design]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は `src/core/stt/stt_interface.py`、`src/core/trans/trans_interface.py`、`src/core/tts/tts_interface.py` の
interface クラス仕様を横断的に扱う実装ガイドです。

## 1. 対象クラスと責務

- `STTInterface`
  - STT エンジン実装の共通契約（可用性、初期化、単一セグメント文字起こし）を定義する。
  - サブクラス定義時に `fetch_engine_name()` を使って自動登録する。
- `TransInterface`
  - 翻訳エンジン実装の共通契約（検出、翻訳、クォータ取得、後始末）を定義する。
  - エンジン属性（`EngineAttributes`）を保持し、利用側が機能フラグを参照できる。
- `Interface`（TTS）
  - TTS エンジン実装の共通契約（初期化、合成、再生連携、外部プロセス起動/終了）を定義する。
  - 登録済みエンジン管理に加え、`EngineContext` を通じた実行時コンテキスト（保存先ディレクトリ、再生コールバック）を扱う。

## 2. 登録規約（`__init_subclass__`）

- STT/翻訳/TTS はいずれもサブクラス作成時に登録処理が動く。
- `fetch_engine_name()` は **クラス定義時点で必ず利用可能** である必要がある。
- 空文字のエンジン名は登録対象外（STT/翻訳）。
- 既存名と重複した場合は `ValueError` を送出する。
- TTS は `register_engine()` 経由で `_registered_engines` に登録する。

## 3. 抽象メソッドの最小実装要件

### STT (`STTInterface`)

- `is_available`（property）
- `fetch_engine_name`（staticmethod）
- `initialize(config)`
- `transcribe(stt_input)`

### Translation (`TransInterface`)

- `count` / `limit` / `limit_reached` / `is_available`（property）
- `fetch_engine_name`（staticmethod）
- `initialize(config)`
- `detect_language(content, tgt_lang)`
- `translation(content, tgt_lang, src_lang=None)`
- `get_quota_status()`
- `close()`

### TTS (`Interface`)

- `fetch_engine_name`（staticmethod）
- `initialize_engine(tts_engine, context: EngineContext)`
- `speech_synthesis(ttsparam)`

## 4. データモデル仕様

- STT 入出力
  - `STTInput`: `audio_path`（一時PCMファイルパス）, `language`, `sample_rate`, `channels`
  - `STTResult`: `text`, `language`, `confidence`, `metadata`
  - `STTInput` / `STTResult` はどちらも frozen dataclass。
  - `audio_path` は `Path` 型。STTManager が一時ディレクトリに生成するプロセス済みPCMファイルのパス。
- 翻訳入出力
  - `Result`: `text`, `detected_source_lang`, `metadata`
  - `EngineAttributes`: `name`, `supports_dedicated_detection_api`, `supports_quota_api`
  - `TranslationInfo`（`src/models/translation_models.py`）: `content`, `src_lang`, `tgt_lang`, `translated_text`, `is_translate`, `engine`

## 5. 例外設計の方針

- STT は `STTExceptionError` を基底とし、以下を用途別に使い分ける。
  - `STTNotAvailableError`: エンジン不假定/初期化失敗時の可用性問題。
  - `STTNonRetriableError`: 再試行しても回復しないことが明確な錯誤（設定不備、未対応フォーマットなど）。
- 翻訳は `TranslateExceptionError` を基底とし、以下を用途別に使い分ける。
  - `NotSupportedLanguagesError`
  - `TranslationQuotaExceededError`
  - `TranslationRateLimitError`
- TTS は `TTSExceptionError` を基底とし、ファイル操作は `TTSFileError` 系を使う。

## 6. TTS interface 固有の運用注意

- `audio_save_directory` と `play_callback` は `EngineContext` 経由で `initialize_engine()` 時に設定される。
- `initialize_engine()` 実行前に `audio_save_directory` / `play_callback` / `play()` を参照した場合は `RuntimeError` を送出する。
- `create_audio_filename()` は `SUPPORTED_FORMATS` 以外の拡張子を拒否する。
- `save_audio_file()` は `bytes | BytesIO` のみ受け付ける。
- `linkedstartup` 有効時の `_execute()` / `_kill()` は外部プロセス管理を担う。
  - Windows では terminate/kill の挙動差を前提に分岐があるため維持する。

## 7. テスト観点（最小セット）

- サブクラス定義時の自動登録で重複名が `ValueError` になること。
- 空名エンジンが登録対象外として扱われること（STT/翻訳）。
- 抽象メソッド未実装クラスが実体化できないこと。
- TTSでコンテキスト未設定時に `RuntimeError` が送出されること。
- manager 側呼び出し経路で戻り型/例外契約が崩れていないこと。

## 8. 実装時チェックリスト

1. `fetch_engine_name()` が空文字/重複名になっていないか。
2. 抽象メソッドの戻り型・非同期同期の契約を守っているか。
3. 例外を基底例外に正しく寄せているか。
4. 初期化失敗時に部分状態（クラス変数やプロセス参照）が残らないか。
5. TTS で `initialize_engine()` に `EngineContext` を渡し、実行時コンテキスト未設定を残していないか。

## 9. 拡張時の推奨手順

1. 対象 interface の抽象メソッドを最小実装する。
2. `fetch_engine_name()` を実装し、既存名重複がないことを確認する。
3. 初期化・後始末で外部リソース（API クライアント、プロセス、ファイル）を明示的に管理する。
4. 失敗系（未対応言語、レート制限、ファイル作成失敗）を専用例外へ正規化する。
5. manager 側から呼ばれる主要経路（初期化、実行、終了）をテストで確認する。
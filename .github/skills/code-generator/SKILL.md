---
name: code-generator
description: コードを生成するためのガイドラインと規約
keywords: [code generation, coding guidelines, implementation rules]
---

# コード生成ガイドライン

このドキュメントは、コード生成に関するガイドラインと規約をまとめたものです。コード生成を行う際は、以下の規約を遵守してください。

# Python バージョン規約

- プロジェクトの最低対応バージョンは `pyproject.toml` の `requires-python` に従う（現在は Python 3.14 以上、3.16 未満）。
- 新規コードでは最低対応バージョンで利用できる構文・APIを使用し、対応範囲より新しい Python 専用の機能を持ち込まない。
- 最低対応バージョンで非推奨の API は避ける（例: `asyncio.TimeoutError` ではなく組み込みの `TimeoutError`）。
- Python の更新時は、非推奨 API の利用状況と依存ライブラリの対応状況を確認する。バージョン要件の変更は `pyproject.toml` と関連するロックファイル・CI 設定も整合させる。

# モジュール構成規約

モジュール先頭は以下の順序で記述する。

1. モジュール docstring
2. 必要な場合のみ `from __future__ import ...`（Python 3.14 では注釈の遅延評価が標準のため、`from __future__ import annotations` を新たに追加しない。既存の記述は、注釈の実行時表現などへの影響を確認せず一括削除しない）
3. import（標準ライブラリ → サードパーティ → プロジェクト内の順）
4. モジュールレベルの定数（定数には `Final` 型ヒントを付与する。例: `TIMEOUT: Final[int] = 30`）
5. `logger = LoggerUtils.get_logger(__name__)`（1 回のみ。`LoggerUtils` の再初期化は禁止）

# 定数・マジックナンバー規約

- 意味のある設定値・業務上の閾値・再利用される値は定数化し、用途が分かる名前を付ける。
- `0`、`1`、空文字列など、文脈から意味が明らかな値まで機械的に定数化しない。テストコード内の値も、可読性や共通化の理由がなければ定数化しない。
- どちらか判断が難しい場合はユーザーに確認し、必要に応じてルールを更新する。

# Docstring 規約

Google スタイルを使用する。簡潔に記述しつつ、必要な情報は省略しない。互換性情報・バグ回避策に関する記述は削除しない（簡潔化は許可）。

## クラスの docstring

- クラスの目的を簡潔に説明する。
- 外部から参照される属性やプロパティに、型注釈だけでは分からない意味がある場合は `Attributes` / `Properties` に説明を記載する。

## 関数・メソッドの docstring

- 機能の概要を 1〜2 文で説明する。
- 必要に応じて `Args`、`Returns`、`Raises` を記載する。型注釈で明らかな型を docstring に重複して書かず、契約・制約・副作用・例外の発生条件など利用者に必要な情報を説明する。
- `Examples`: 使用例（必要に応じて）
- `Notes`: 特記事項（必要に応じて）
- 内容のないセクションや、自明な処理を言い換えるだけの docstring は追加しない。

# インラインコメント規約

- 非自明なロジックや、バグを生みやすいコードに限定して使用する。
- 自明なコードへのコメントは避ける（例: `i += 1  # increment i` は不要）。
- コードの内容を繰り返すのではなく、その意図・理由・背景を説明する。
- コード変更時にはコメントも見直し、常に最新の状態を保つ。

# コードスタイル規約

## ファイル形式

- Python ファイル（`*.py`）は UTF-8 + LF 改行、最大行長 120 文字（`ruff` で強制）とする。
- `*.py` 以外のテキストファイル（ログファイル等）も UTF-8 + LF 改行で保存する。

## 型ヒント

- 関数・メソッドには引数と戻り値の型を付け、公開 API と複雑なデータ境界は明示的に型付けする。既存コードの規約や型チェッカー設定も尊重する。
- 新しいコードでは `list[str]`、`dict[str, int]`、`str | None` などの組み込みジェネリックと union 構文を優先する。`typing.List`、`typing.Dict`、`typing.Optional`、`typing.Union` は新規コードで使わない。
- コレクションの引数には、必要に応じて `collections.abc.Sequence`、`Mapping`、`Callable` など、必要な操作を表す抽象型を使う。不要に具体的なコンテナ型へ制約しない。
- `Any` は型情報を失わせるため安易に使わず、可能なら `object`、`Protocol`、`TypedDict`、型ガードなどで境界を明確にする。外部ライブラリ等の都合で必要な場合は、狭い範囲に閉じ込める。
- 型エイリアスやジェネリックは、意味を明確にする場合に `type Alias = ...` や型パラメーター構文を利用する。短い式まで過度に抽象化しない。
- Python 3.14 の標準ライブラリで提供される型機能を優先し、互換性要件がない限り `typing_extensions` を新たに導入しない。
- 型表記が極端に複雑な場合やテストコードでは省略を検討してよいが、型チェッカーのエラーを安易な `Any` や `cast` で隠さない。
- 未使用引数は名前を `_` で始める（例: `_unused: int`）。  
  インターフェースの制約等により引数名を変更できない場合は、docstring 直後に `_ = arg1, arg2` を記述して Lint 警告を抑制する。
  ```python
  def on_event(self, sender: object, data: EventData) -> None:
      """Handle event."""
      _ = sender, data  # Suppress unused argument warnings
  ```

## 例外処理

- try ブロック内のコードは、例外が発生する可能性のある最小限の範囲に限定する。処理が複数にまたがる場合は try ブロックを分割して原因特定を容易にすること。
- 想定できる例外を捕捉し、回復・文脈追加・境界での障害分離など、捕捉する理由を明確にする。広い `except Exception` はプロセスやタスク境界で障害を分離する必要がある場合に限る。
- 例外を捕捉する際は、機密情報の漏えいを避けるため `err` を無条件にログへ出さない。一般処理では型と必要最小限に切り詰めたメッセージを記録し、認証・トークン操作などでは型のみを記録する（[セキュリティ規約](#セキュリティ規約)参照）。機密情報を含まないと確認できる境界では、スタックトレースが必要な場合に標準の例外ログ機能を利用してよい。
   ```python
   try:
       result = some_api_call()
   except Exception as err:
       logger.error("API call failed (%s): %s", type(err).__name__, str(err)[:100])
   ```
- 新しい例外へ置き換える場合は、原因を保持するため必要に応じて `raise ... from err` を使う。メッセージを必ず一時変数に代入する必要はなく、再利用や組み立てが必要な場合に変数化する。
  ```python
  raise ValueError("Unexpected value received")
  ```
- 失敗ケースを考慮し、異常時にもエラーを明示して安全に停止または回復できるようにする。例外を握りつぶしたり、成功したように見える値へ置き換えたりしない。

## 非同期処理

- `asyncio.create_task` など `name` 引数を受け付けるメソッドでは、必ず `name` を指定する。生成したタスクは参照を保持し、完了・例外・キャンセルを管理する。所有者のないバックグラウンドタスクを作らない。
- 関連する子タスクのライフサイクルがまとまっている場合は `asyncio.TaskGroup` による構造化並行処理を優先する。既存のキュー・ワーカー設計や個別の障害分離要件がある場合は、それらの契約を維持する。
- タイムアウトには `asyncio.timeout()` など対応バージョンの標準 API を使い、キャンセルを適切に伝播させる。終了処理ではタスクの停止・待機とリソース解放の順序を明確にする。
- イベントループをブロックする同期 I/O や長時間処理を `async` 関数内で直接実行しない。ブロッキング I/O は `asyncio.to_thread()` など適切な仕組みへ隔離する。

## マルチスレッド処理

- CPU バウンド処理の並列化は、通常のスレッドが常に有効とは限らないことを踏まえて設計する。計測に基づいて `ProcessPoolExecutor` 等を検討し、自由スレッド化ビルドを利用する場合も依存ライブラリの対応と実測を確認する。
- I/O 待ちにはスレッドが有効な場合がある。スレッド・プロセス間で共有する状態、キャンセル、終了時の待機を明示し、並列化のためだけに複雑さを増やさない。

## オーバーライド

- `typing.override` の `@override` デコレータを使用して、スーパークラスのメソッドをオーバーライドしていることを明示する。
- オーバーライドするメソッドは、スーパークラスのシグネチャと一致させること。

## Python 標準機能の活用

- ファイルシステムのパス操作には `os.path` より `pathlib.Path` を優先し、ファイル操作では `with` によるリソース管理と適切な文字コード指定を行う。
- データ保持には用途に応じて `dataclasses`、`Enum`、標準コレクションを使う。`dataclass` の可変デフォルト値には `default_factory` を使い、`frozen=True` や `slots=True` は不変性やメモリ特性が要件に合う場合に限って採用する。
- 既存の依存関係やプロジェクト標準で十分な場合を除き、新しい依存を追加せず、標準ライブラリで要件を簡潔に満たせるか確認する。

## リファクタリング

- リファクタリングは、明示された対象・目的・範囲に限り、既存の振る舞いと公開契約を維持する。無関係な変更を混ぜず、最小の差分で行う。
- 抽象化・共通化は重複や変更容易性の具体的な改善につながる場合に行い、将来の可能性だけを理由に汎用化しない。性能改善は計測や具体的な根拠に基づいて行う。
- リファクタリング方針の策定・レビュー・実施手順は [refactoring-policy](../refactoring-policy/SKILL.md) に従う。

# ロギング規約

- `logger` はモジュールごとに 1 回のみ取得する（[モジュール構成規約](#モジュール構成規約) 参照）。
- ログに変数の値を出力する時は '' で囲む（例: `logger.info("Bot ID: '%s'", bot_id)`）。
  - **例外**: 変数がリスト型など複数の値を含む場合は '' で囲まないこと。全体を囲む '' と、個々の値を囲む '' が混在して可読性が低下するため。
  ```python
  # Recommended for single values
  logger.info("Bot ID: '%s'", bot_id)  -> "Bot ID: '123456789'"
  # Recommended for lists (avoid nested quotes)
  logger.info("Connected channels: %s", channel_list)  -> "Connected channels: ['#channel1', '#channel2']"
  # Not recommended (nested quotes reduce readability)
  logger.info("Connected channels: '%s'", channel_list)  -> "Connected channels: '['#channel1', '#channel2']'"
  ```
- 変数の長さが非常に長くなる可能性がある場合は、ログの可読性を保つために、値の一部を切り取るなどして出力することを検討する。
  - 切り取る際の目安としては、通常の文字列の場合は 50 文字、ハッシュ値などのランダムな文字列の場合は 16 文字を推奨するが、状況に応じて適切な長さを選択すること。（固定文字列＋ランダム文字列の場合など）
  - 例外メッセージは、デバッグに必要な情報を保持できる範囲で切り取ること（例: 100 文字）。必要に応じて切り取り前の全文を `logger.debug` で出力することも検討する。例外ログの具体的なパターンは [コードスタイル規約 > 例外処理](#例外処理) を参照。
  ```python
  # Recommended for long strings (log only the first 50 characters)
  logger.info("Received message: '%s'", message[:50])  -> "Received message: 'Lorem ipsum dolor sit amet, consectetur adipiscing'"
  # Recommended for hashes (log only the first 16 characters)
  logger.info("Received hash: '%s'", hash_value[:16])  -> "Received hash: '1a2b3c4d5e6f7g8h'"
  ```

## イベントハンドラーのロギング

`async def event_` プレフィックスで定義されるイベントハンドラーでは、`logger.info` でイベントの発生を記録することを推奨する。

- **記録タイミング**: 原則としてハンドラーの先頭で記録する。処理内容によっては完了後の記録も許可する。
- **ペイロードの扱い**:
  - `logger.info` では payload の内容を出力せず、イベントの発生のみを記録する。
  - payload の詳細が必要な場合は `logger.debug` で出力する。
  - **例外**: イベントを識別するために必要不可欠な情報（ID・種別等）が payload に含まれる場合は、`logger.info` への最小限の出力を許可する。

```python
# Recommended: log event occurrence only
logger.info("Event received: ready")

# Allowed only when payload content is essential for identification
logger.info("Event received: message_delete (id=%s)", message_id)
```

# セキュリティ規約

## 機密情報の取り扱い

- API キー・アクセストークン・認証情報・秘密鍵は、ログや例外のメッセージ文字列に出力しない。
- `except ... as err` で捕捉した例外オブジェクトをそのままログに渡さない。`err` のメッセージに機密情報が含まれる可能性があるため、型とメッセージの先頭 100 文字のみを出力すること。認証・トークン操作など機密情報を扱う処理では、型のみを出力すること。
  ```python
  # Bad: err may contain credentials in the exception message
  logger.error("API error: %s", err)

  # Good (general): log type + truncated message
  logger.error("API call failed (%s): %s", type(err).__name__, str(err)[:100])

  # Good (auth/token operations): log type only to avoid credential leakage
  logger.error("Auth failed (%s)", type(err).__name__)
  ```

## 設定ファイルの取り扱い

- `twitchbot.ini` はリードオンリーとして扱う。設定値の動的変更・ファイルへの書き込みは禁止とする。

# 実行環境規約

- Windows 10/11 + Python 3.14 での実行を前提とするが、可能な限りクロスプラットフォームを意識した実装を行う。
  - プラットフォーム固有の実装は、その旨をコメントで明示する。
- PyInstaller 実行を前提に、ファイルパスと外部依存の扱いを明示する。

---
name: code-generator
description: コードを生成するためのガイドラインと規約
keywords: [code generation, coding guidelines, implementation rules]
---

# コード生成ガイドライン

このドキュメントは、コード生成に関するガイドラインと規約をまとめたものです。コード生成を行う際は、以下の規約を遵守してください。

# Python バージョン規約

- Python 3.14 以降をサポート対象とする。
- Python 3.14 時点で非推奨となっているメソッド・クラス・関数は使用しないこと（例: `asyncio.TimeoutError` → `TimeoutError`）。

# モジュール構成規約

モジュール先頭は以下の順序で記述する。

1. モジュール docstring
2. Python 3.14 以降では `from __future__ import annotations` は不要となるため、記述しないことを推奨する。
   既に `from __future__ import annotations` が含まれている場合は削除してもよいが、削除するだけの変更は避けることを推奨する（他の変更と組み合わせて削除することを推奨）。
3. import（標準ライブラリ → サードパーティ → プロジェクト内の順）
4. モジュールレベルの定数（すべて `Final` 型ヒントを付与する。例: `TIMEOUT: Final[int] = 30`）
5. `logger = LoggerUtils.get_logger(__name__)`（1 回のみ。`LoggerUtils` の再初期化は禁止）

# 定数・マジックナンバー規約

- 数値・文字列リテラルをコードに直接埋め込まず、モジュール先頭に定数として定義する。
- **例外（定数化不要）**: 定義するとかえって可読性を損なう場合、またはテストコード内のリテラルは適用外とする。
- どちらか判断が難しい場合はユーザーに確認し、必要に応じてルールを更新する。

# Docstring 規約

Google スタイルを使用する。簡潔に記述しつつ、必要な情報は省略しない。互換性情報・バグ回避策に関する記述は削除しない（簡潔化は許可）。

## クラスの docstring

- クラスの目的を簡潔に説明する。
- `Attributes`: クラス変数の名前・型・説明を記載する。
- `Properties`: プロパティの名前・型・説明を記載する。

## 関数・メソッドの docstring

- 機能の概要を 1〜2 文で説明する。
- `Args`: 引数名・型・説明
- `Returns`: 戻り値の型と内容
- `Raises`: 送出する例外の型と発生条件
- `Examples`: 使用例（必要に応じて）
- `Notes`: 特記事項（必要に応じて）

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

- すべての関数・メソッドに完全な型ヒントを付与することを推奨する。
  - **例外**: 型表記が非常に複雑になる場合、またはテストコードについては省略してもよい。
- 未使用引数は名前を `_` で始める（例: `_unused: int`）。  
  インターフェースの制約等により引数名を変更できない場合は、docstring 直後に `_ = arg1, arg2` を記述して Lint 警告を抑制する。
  ```python
  def on_event(self, sender: object, data: EventData) -> None:
      """Handle event."""
      _ = sender, data  # Suppress unused argument warnings
  ```

## 例外処理

- 例外を送出する前に、エラーメッセージを `msg` 変数に代入してから渡す。
  ```python
  msg = "Unexpected value received"
  raise ValueError(msg)
  ```
- 失敗ケースを先に考慮し、異常時でも安全に停止できる状態を維持する（例外処理・ログ出力・非同期終了処理のすべてに適用）。

## 非同期処理

- `asyncio.create_task` など `name` 引数を受け付けるメソッドでは、必ず `name` を指定して生成したタスクをログ等で可視化できるようにする。

## マルチスレッド処理

- Python 3.14 でも GIL は存在するため、CPU バウンドな処理はマルチスレッドでの並列化が効果的でないことを考慮する。
  - フラグを設定してビルドすることで、GIL を完全に排除した Python 3.14 をビルドすることは可能である。
  - GIL が有効か無効かを確認する方法は、以下の様に `sys` モジュールの `sys._is_gil_enabled()` 関数で確認できる。

  ```python
  import sys
  if sys._is_gil_enabled():
      logger.info("GIL is enabled. CPU-bound tasks may not benefit from threading.")
  else:
      logger.info("GIL is disabled. Threading may improve performance for CPU-bound tasks.")
  ```

## オーバーライド

- `@override` デコレータを使用して、スーパークラスのメソッドをオーバーライドしていることを明示する。
- オーバーライドするメソッドは、スーパークラスのシグネチャと一致させること。

# ロギング規約

- `logger` はモジュールごとに 1 回のみ取得する（[モジュール構成規約](#モジュール構成規約) 参照）。

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
- `except ... as err` で捕捉した例外オブジェクトをそのままログに渡さない。
  `err` のメッセージに機密情報が含まれる可能性があるため、必要な情報のみを抽出してから出力する。
  ```python
  # Bad: err may contain credentials in the exception message
  logger.error("API error: %s", err)

  # Good: log only safe information like the exception type
  logger.error("API call failed (%s)", type(err).__name__)
  ```

## 設定ファイルの取り扱い

- `twitchbot.ini` はリードオンリーとして扱う。設定値の動的変更・ファイルへの書き込みは禁止とする。

# 実行環境規約

- Windows 10/11 + Python 3.14 での実行を前提とするが、可能な限りクロスプラットフォームを意識した実装を行う。
  - プラットフォーム固有の実装は、その旨をコメントで明示する。
- PyInstaller 実行を前提に、ファイルパスと外部依存の扱いを明示する。

---
name: test-code-generator
description: pytest/pytest-asyncio を前提とした単体テスト設計、実装、運用ルールのガイドラインと規約
keywords: [unit-test, pytest, pytest-asyncio, mocking, fixture, assertion, reproducibility, test-design]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は pytest/pytest-asyncio を前提とした単体テストの設計・実装・運用ルールをまとめたものです。

## 1. 設計原則

- テストは小さく独立させ、1テストで1つの振る舞いを検証する。
- テストは明確な入力と期待される出力を定義し、失敗時に原因が1箇所へ収束するよう設計する。
- 外部依存（API、I/O、バックグラウンド処理）は `AsyncMock` / `MagicMock` / `patch` で置き換える。
- 実行順序に依存させず、グローバル状態は各テストで初期化する。
- 正常系・異常系・境界値をペアで用意し、片側だけの検証を避ける。
- テストコードはドキュメントとしても機能するよう、命名と構造を整える。
- 例外をキャッチして別の例外として再送出している箇所は、例外が正しく再送出されているかを検証する。

## 2. ファイル構造

- テストコードは `tests/` ディレクトリ以下に、本番コードのディレクトリ構造と対応した形で配置する。
- モジュールごとにファイルを分割し、テストの目的に応じて適切な命名規則を使用する。
- 複数ファイルで共有するフィクスチャは `conftest.py` に配置する。
  - `conftest.py` は `tests/` 直下（共通）またはサブディレクトリ直下（局所）に置く。

## 3. 実行環境

- テストは `pytest` を使用して実行する。実行前に `venv` を有効化し、依存関係の差異による誤検知を避ける。
- 非同期処理を含むテストは `pytest-asyncio` を使用する。
  - このリポジトリは `pyproject.toml` で `asyncio_mode = "auto"` を設定しているため、**`@pytest.mark.asyncio` マーカーは不要**（自動適用される）。
  - フィクスチャのループスコープは `asyncio_default_fixture_loop_scope = "function"` のため、非同期フィクスチャは関数スコープで独立したイベントループが使われる。

## 4. テストの粒度と命名

- 1テスト1振る舞いを基本とし、失敗時に原因が1箇所へ収束するようにする。
- テスト名は `test_<対象>_<条件>_<期待結果>` の形式で、仕様を読める文にする。

## 5. pytest 運用ルール

- 再利用するモックは `@pytest.fixture` で提供し、重複セットアップを減らす。
- 非同期メソッドは `assert_awaited_once_with` など await 系のアサーションを優先する。
- フィクスチャスコープの選択基準:
  - `function`（デフォルト）: 状態を持つオブジェクト（マネージャー、モック）は原則このスコープ。
  - `module` / `session`: 読み取り専用の高コスト初期化（設定オブジェクト、静的データ）のみに限定し、状態漏洩を防ぐ。

## 6. 再現性と安定性

- 時刻・乱数・UUID・スレッド依存の挙動は固定化またはモック化して決定的にする。
- ネットワークや実ファイルI/Oに依存する単体テストは作らない。
- 警告を黙殺する前に、型整合（`cast` / プロトコル化）で局所的に解消できるかを優先する。
- 特定の値がセットされないことを検証する場合は、正常に値がセットされるケースも同じテスト内にペアで用意する。
  - セットされないだけの検証を行うと、正しく排除されているのか、そもそも値がセットされていないのかが不明瞭になるため、両方を用意することが望ましい。

## 7. アサーション指針

- 戻り値だけでなく、副作用（呼び出し回数、引数、状態遷移、ログ出力）も検証する。
- 例外検証は `pytest.raises` を使用し、例外型だけでなくメッセージの要点も確認する。
- モックの `assert_called_*` は過剰に広くせず、仕様に必要な最小条件へ絞る。
- 複雑なオブジェクト・コレクションの比較には `testfixtures.compare` を優先する（詳細は「11. testfixtures 活用ガイド」参照）。
- ログ出力の検証には `testfixtures.LogCapture` を使用する（詳細は「11. testfixtures 活用ガイド」参照）。

## 8. カバレッジ運用

- カバレッジ計測対象は `pyproject.toml` の `[tool.coverage.run] source` で定義されており、`core`, `handlers`, `utils`, `config`, `models` が対象。
- ブランチカバレッジ（`branch = true`）を有効にしているため、条件分岐の両辺を網羅するテストが望ましい。
- カバレッジが低い箇所を追加する際は、正常系・異常系の両面から最低限のパスを追加する。
- `pragma: no cover` 抑制は、到達不能コードや `__repr__`/`__str__` など定型コードに限定し、テスト困難を理由に乱用しない。

## 9. 実装・修正時チェックリスト

1. 追加したテストは失敗原因を一意に示せるか。
2. 非同期処理の検証で await 系アサーションを使っているか。
3. 外部依存を適切にモックし、実行環境差を排除できているか。
4. 変更した仕様に対して正常系と異常系の両方を追加・更新したか。
5. テスト名とフィクスチャ名が振る舞いを正確に表しているか。
6. ローカルで対象テストを実行し、再現性があることを確認したか。

## 10. テストのドキュメント

- テストの目的や前提条件が自明でない場合は、英語でコメントを補足する（仕様意図の補足に限定し、自明な処理説明は避ける）。

## 11. testfixtures 活用ガイド

`testfixtures` はインストール済みであり、以下の場面で積極的に活用する。

### 11-1. `compare` — 詳細な比較アサーション

`assert ==` や `assertEqual` の代わりに使用する。差分が明確に表示されるため、失敗時の原因特定が容易になる。

```python
from testfixtures import compare

# dict: どのキーが違うか、値がどう違うかを表示
compare(expected={'a': 1, 'b': 2}, actual={'a': 1, 'b': 3})

# list/tuple: どの位置から差異があるかを表示
compare(expected=[1, 2, 3], actual=[1, 2, 4])

# 複雑なオブジェクトの属性比較（__eq__ 不要）
compare(expected=MyObj(name='foo'), actual=MyObj(name='bar'))

# タイムスタンプなど比較不要な属性を除外する
compare(expected=obj1, actual=obj2, ignore_attributes=['timestamp'])
```

使用場面:
- `dict` / `list` / `set` / `namedtuple` の内容検証
- `__eq__` を持たない独自クラスのインスタンス比較
- ネストした複合データ構造の比較
- 長い文字列・複数行文字列（unified diff で差分を表示）

### 11-2. `LogCapture` — ログ出力の検証

Python の `logging` モジュール経由で出力されたログを捕捉して検証する。

```python
from testfixtures import LogCapture

def test_something_logs_error():
    with LogCapture() as lc:
        call_target_function()
        lc.check(
            ('my_logger', 'ERROR', 'expected error message'),
        )

# 複数ログのうち特定のものだけ確認したい場合
def test_partial_log_check():
    with LogCapture() as lc:
        call_target_function()
        lc.check_present(
            ('my_logger', 'WARNING', 'important warning'),
        )
```

pytest の `conftest.py` にフィクスチャとして定義すると再利用しやすい:

```python
import pytest
from testfixtures import LogCapture

@pytest.fixture()
def log_capture():
    with LogCapture() as lc:
        yield lc
```

使用場面:
- マネージャーやエンジンが正しいログレベル・メッセージを出力するかの検証
- 例外発生時にエラーログが出力されることの確認
- 警告ログが適切な条件下でのみ発生することの確認

### 11-3. `Comparison` (`C`) — 部分一致・型一致による比較

モックの呼び出し引数に特定の型や属性だけを検証したい場合に使用する。

```python
from testfixtures import Comparison as C

# 型だけ確認
assert some_mock.call_args[0][0] == C(MyException)

# 型 + 属性の部分一致
assert result == C(MyObj, name='expected', partial=True)
```

`Comparison` は `==` の左辺に置くこと（右辺に置くと `__eq__` の評価順で誤動作する場合がある）。

### 11-4. `StringComparison` (`S`) — 正規表現による文字列マッチ

```python
from testfixtures import StringComparison as S

# ログメッセージの正規表現チェック
lc.check(('root', 'ERROR', S(r'Connection failed: .+')))

# フラグ指定
lc.check(('root', 'INFO', S(r'started.*thread', re.IGNORECASE)))
```

### 11-5. 型安全な比較ヘルパー

mypy を使用している本プロジェクトでは、型エラーを避けるため以下のヘルパーを活用する。

| ヘルパー | 用途 |
|---|---|
| `like(MyClass, x=1)` | 型を保ちながら部分一致比較 |
| `sequence(partial=True, ordered=False)([...])` | 順序不問・部分一致のシーケンス比較 |
| `contains([item1, item2])` | 指定要素が含まれているか確認 |
| `unordered([item1, item2])` | 全要素一致・順序不問の比較 |

```python
from testfixtures import compare, like

# 部分一致（型安全）
compare(expected=[like(MyObj, name='foo')], actual=result_list)
```

### 11-6. `RoundComparison` / `RangeComparison` — 数値比較

```python
from testfixtures import RoundComparison as R, RangeComparison as Range

# 小数点以下2桁で四捨五入して一致確認
assert score == R(1.234, 2)

# 値が範囲内にあることを確認
assert duration == Range(0.0, 5.0)
```

### 11-7. 使い分けの判断基準

| 状況 | 推奨 |
|---|---|
| シンプルな値の比較 | `assert ==` |
| `dict` / `list` / ネストオブジェクトの比較 | `compare()` |
| ログ出力の検証 | `LogCapture` |
| モック引数の型・属性チェック | `Comparison` (`C`) |
| ログメッセージのパターンチェック | `StringComparison` (`S`) |
| 型チェッカーを通しつつ部分一致 | `like()` / `sequence()` / `contains()` |

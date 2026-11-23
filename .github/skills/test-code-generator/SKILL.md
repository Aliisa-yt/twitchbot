---
name: test-code-generator
description: pytest/pytest-asyncio を前提とした単体テスト設計、実装、運用ルールのガイドラインと規約
keywords: [unit-test, pytest, pytest-asyncio, mocking, fixture, assertion, reproducibility, test-design]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は pytest 9.2.0 / pytest-asyncio 1.5.0 を前提とした単体テストの設計・実装・運用ルールをまとめたものです。

## 1. 運用環境

- Windows で手動実行する場合は、先にリポジトリの仮想環境を有効化する。

```powershell
& .\.venv\Scripts\Activate.ps1
python -m pytest tests/ -q
```

- 非同期テストは pytest-asyncio を使用する。
- このリポジトリでは `pyproject.toml` の `asyncio_mode = "auto"` により、非同期関数が自動検出される。
- `asyncio_default_fixture_loop_scope = "function"` により、非同期フィクスチャは関数ごとのイベントループを使用する。
- pytest 9.2.0 の時点で `@pytest.mark.asyncio` は廃止されていないが、`asyncio_mode = "auto"` が設定された環境では冗長なので新規テストでは付けない。
- `asyncio_default_test_loop_scope` を明示する場合の推奨スコープは `function` とする。

## 2. 設計原則

- テストは小さく独立させ、1テストで1つの振る舞いを検証する。
- テスト名は `test_<対象>_<条件>_<期待結果>` の形式で、仕様が読める名前にする。
- 明確な入力と期待結果を定義し、失敗時に原因が1箇所へ収束するようにする。
- 外部依存（API、I/O、バックグラウンド処理）は `AsyncMock` / `MagicMock` / `patch` または適切なフィクスチャで置き換える。
- 実行順序に依存させず、グローバル状態は各テストで初期化する。
- 正常系・異常系・境界値をペアで用意し、片側だけを検証しない。
- 時刻・乱数・UUID・スレッド・ネットワーク・実ファイルI/Oは固定化またはモック化し、決定的にする。
- テストコードはドキュメントとしても機能するよう、名前と構造を整える。
- 例外を再送出する箇所では、元の例外の型・メッセージ・`from` によるチェーンを検証する。
- テストの目的や前提条件が自明でない場合だけ、英語で仕様意図を補足する。

## 3. ファイル構造と配置

- テストは `tests/` 以下に、本番コードのディレクトリ構造と対応させて配置する。
- モジュールごとにテストファイルを分割し、目的に応じて `test_<module>.py` を使用する。
- 複数ファイルで共有するフィクスチャは `conftest.py` に配置する。
  - 共通フィクスチャは `tests/conftest.py`、局所フィクスチャは対象サブディレクトリ直下の `conftest.py` に置く。
- モックやフィクスチャを無計画に共有せず、状態を持つオブジェクトはテスト単位で生成する。

## 4. フィクスチャとパラメータ化

- 再利用するセットアップは `@pytest.fixture` を使用する。
- 状態を持つオブジェクト（マネージャー、モック）は原則 `function` スコープにする。
- `module` / `session` スコープは読み取り専用の高コスト初期化（設定、静的データ）のみに限定する。
- 後片付けが必要なフィクスチャは、テストが失敗しても確実に実行される `yield` を使用する。
- フィクスチャが複数オブジェクトを返す場合は、意味が明確な tuple または dataclass を使用する。
- 複数入力を検証する場合は `pytest.mark.parametrize` を使用し、引数名と値を tuple 形式で書く。
- ケースに識別子が必要な場合は `pytest.param(..., id="...")` を使用する。

```python
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        pytest.param("", "", id="empty"),
        pytest.param("abc", "ABC", id="normal"),
    ],
)
def test_normalize_input(input_value: str, expected: str) -> None:
    assert normalize(input_value) == expected
```

## 5. 非同期テスト

- 非同期テスト関数には `async def` を使用する。
- `asyncio_mode = "auto"` のため、新規テストに `@pytest.mark.asyncio` を追加しない。
- 非同期フィクスチャは `@pytest.fixture` を付けた `async def` とし、必要なら `yield` で後片付けする。
- 非同期メソッドは `assert_awaited_once_with` / `assert_awaited_once` など await 系のアサーションを優先する。
- テストが生成した `Task`・ストリーム・セッション・バックグラウンドワーカーは、テスト終了前にキャンセルまたはクローズする。
- イベントループスコープをまたぐオブジェクトやモックを共有しない。
- タスクのキャンセルを検証する場合は、キャンセル後のクリーンアップも検証する。

```python
async def test_fetch_success_returns_body() -> None:
    client = AsyncMock()
    client.fetch.return_value = "ok"

    result = await fetch_body(client)

    assert result == "ok"
    client.fetch.assert_awaited_once_with("/path")
```

## 6. モックと I/O

- 同期メソッドには `MagicMock`、非同期メソッドには `AsyncMock` を使用する。
- モック対象はテスト対象の境界に近い依存だけに限定し、内部メソッドまで広く置き換えない。
- モックの引数は仕様上意味があるものだけを厳密に検証し、過剰な呼び出し検証を避ける。
- 状態変更も副作用として検証し、戻り値だけで成功判定しない。
- 単体テストで本物のネットワーク、外部API、固定された絶対パス、実システム時刻に依存しない。
- ファイルI/Oが必要な場合は `tmp_path` を使用する。関数レベルの一時ディレクトリがテストの再現性を高める。
- 時刻・乱数・UUID・環境変数はモックまたはフィクスチャで制御する。

## 7. アサーション

- 戻り値だけでなく、副作用（呼び出し回数、引数、状態遷移、ログ出力）も検証する。
- 例外検証は `pytest.raises` を使用し、例外型に加えてメッセージの要点を確認する。
- 動的に組み立てる正規表現は `re.escape()` を使用する。
- 複雑なオブジェクト・コレクションの比較には `testfixtures.compare` を優先する（詳細は「10. testfixtures 活用ガイド」参照）。
- ログ出力の検証には `testfixtures.LogCapture` を使用する（詳細は「10. testfixtures 活用ガイド」参照）。
- 例外インスタンスの属性まで検証する場合は `exc_info.value` を使用する。

```python
with pytest.raises(ValueError, match=r"count must be >= 0"):
    set_count(-1)

with pytest.raises(KeyError) as exc_info:
    mapping["missing"]
assert exc_info.value.args == ("missing",)
```

## 8. 警告と非推奨 API

- 現在使用している pytest 9.2.0 および pytest-asyncio 1.5.0 では、以下を推奨する。

| 非推奨または旧来の記述 | 推奨 |
|---|---|
| `pytest.warns(None)` | `warnings.catch_warnings()` により、警告の発生なしまたは発生内容を明示的に検証する |
| `tmpdir` / `py.path.local` | `tmp_path` / `pathlib.Path` |
| `pytest.yield_fixture` | `@pytest.fixture` と `yield` |
| `@pytest.mark.asyncio`（auto モード設定時） | マーカーなしで通常の `async def` を使用 |
| 不明瞭な関数名付き fixture | 振る舞いを表す fixture 名と関数スコープを使用 |

- `@pytest.mark.asyncio` は廃止 APIではなく、ただし auto モードでは冗長である。
- テスト実行時の警告を黙殺する前に、型整合（`cast` / プロトコル化）やテスト対象の修正で解消できるか確認する。
- 既存の警告フィルターを無効化せず、意図的に無視する警告は理由と対象メッセージを明示する。
- 未知の警告を広く無視しない。将来の `PytestRemovedIn10Warning` なども含めて、警告名と移行先を確認する。
- pytest 9 系で削除済みまたは非推奨となった APIを検出した場合は、上表または公式の移行先へ更新し、既存テストとの差分を確認する。

```python
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("error")
    call_safe_function()
```

警告が意図的に発生する場合は、使用するライブラリの警告クラスとメッセージを絞って検証する。

```python
with pytest.warns(DeprecationWarning, match=r"old API"):
    call_deprecated_api()
```

## 9. カバレッジと実行

- カバレッジ計測対象は `pyproject.toml` の `[tool.coverage.run] source` で定義された `core`, `handlers`, `utils`, `config`, `models` とする。
- ブランチカバレッジは有効であるため、条件分岐の両辺を網羅する。
- カバレッジ向上だけを目的に意味のないテストを追加せず、正常系・異常系・境界値の仕様をテストする。
- 対象テストを先に実行し、失敗を局所化してから全テストへ進む。
- `pragma: no cover` は到達不能コードや `__repr__` / `__str__` の定型コードに限定し、テスト困難を理由に乱用しない。

```powershell
& .\.venv\Scripts\Activate.ps1
python -m pytest tests/core/cache/test_cache_manager.py -q
python -m pytest tests/ -q
coverage run -m pytest tests/
coverage report
```

## 10. testfixtures 活用ガイド

`testfixtures` はインストール済みであり、以下の場面で使用する。

### 10-1. `compare` — 詳細な比較

`assert ==` と異なり、差分が明確に表示される。

```python
from testfixtures import compare

compare(expected={"a": 1, "b": 2}, actual={"a": 1, "b": 3})
compare(expected=[1, 2, 3], actual=[1, 2, 4])
compare(expected=obj1, actual=obj2, ignore_attributes=["timestamp"])
```

使用場面:
- `dict` / `list` / `set` / `namedtuple` の内容検証
- `__eq__` を持たない独自クラスのインスタンス比較
- ネストした複合データ構造の比較
- 長い文字列・複数行文字列の差分表示

シンプルなスカラー比較は通常の `assert` を使用し、複雑な差分では `compare` を使用する。

### 10-2. `LogCapture` — ログ出力の検証

```python
from testfixtures import LogCapture

def test_something_logs_error() -> None:
    with LogCapture() as capture:
        call_target_function()
        capture.check(
            ("my_logger", "ERROR", "expected error message"),
        )

def test_partial_log_check() -> None:
    with LogCapture() as capture:
        call_target_function()
        capture.check_present(
            ("my_logger", "WARNING", "important warning"),
        )
```

pytest の `conftest.py` にフィクスチャとして定義すると再利用しやすい。

```python
import pytest
from testfixtures import LogCapture

@pytest.fixture()
def log_capture():
    with LogCapture() as capture:
        yield capture
```

使用場面:
- 正しいログレベル・メッセージの検証
- 例外発生時のエラーログ検証
- 警告ログが適切な条件でのみ発生することの検証

### 10-3. `Comparison` (`C`) — 部分一致・型一致

モック引数の型や属性だけを検証する場合に使用する。`Comparison` は `==` の左辺に置く。

```python
from testfixtures import Comparison as C

assert some_mock.call_args.args[0] == C(MyException)
assert result == C(MyObj, name="expected", partial=True)
```

モック引数全体を型変換せず検証できる場合は、標準の `assert_...` を優先する。

### 10-4. `StringComparison` (`S`) — 正規表現による文字列一致

```python
import re

from testfixtures import StringComparison as S

capture.check(("root", "ERROR", S(r"Connection failed: .+")))
capture.check(("root", "INFO", S(r"started.*thread", re.IGNORECASE)))
```

### 10-5. 型安全な比較ヘルパー

型チェッカーを使用する場合は、必要な範囲だけを検証する。

| ヘルパー | 用途 |
|---|---|
| `like(MyClass, x=1)` | 型を保った部分一致 |
| `sequence(partial=True, ordered=False)(...)` | 部分一致・順序不問のシーケンス |
| `contains(...)` | 指定要素の包含 |
| `unordered(...)` | 全要素一致・順序不問 |

```python
from testfixtures import compare, like

compare(expected=[like(MyObj, name="foo")], actual=result_list)
```

### 10-6. 数値の比較

```python
from testfixtures import RangeComparison as Range, RoundComparison as R

assert score == R(1.234, 2)
assert duration == Range(0.0, 5.0)
```

### 10-7. 使い分け

| 状況 | 推奨 |
|---|---|
| シンプルな値の比較 | `assert ==` |
| `dict` / `list` / ネストオブジェクトの比較 | `compare()` |
| ログ出力の検証 | `LogCapture` |
| モック引数の型・属性チェック | `Comparison` (`C`) |
| ログメッセージのパターンチェック | `StringComparison` (`S`) |
| 型チェッカーを通した部分一致 | `like()` / `sequence()` / `contains()` |

## 11. 実装・修正時チェックリスト

1. 追加したテストは失敗原因を一意に示せるか。
2. 非同期処理の検証で await 系アサーションを使っているか。
3. `@pytest.mark.asyncio` を新規テストで冗長に追加していないか。
4. 外部依存を適切にモックし、実行環境差を排除できているか。
5. 正常系・異常系・境界値を仕様に対して網羅したか。
6. テスト名とフィクスチャ名が振る舞いを正確に表しているか。
7. 非推奨 API・旧フィクスチャ・広い警告フィルターを使っていないか。
8. 対象テストをローカルで実行し、再現性があることを確認したか。


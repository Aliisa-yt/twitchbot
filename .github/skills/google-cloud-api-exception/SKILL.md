---
name: google-cloud-api-exception
description: Google Cloud APIを使用している際に発生する例外を処理するスキル
keywords: [google cloud, api, exception, error handling, retry]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は、Google Cloud API 呼び出し時の例外処理を「運用しやすい粒度」で整理したスキルです。
個別例外を網羅的に列挙するより、次の 3 点で方針を決めることを優先してください。

1. そのエラーは再試行で改善するか
2. 呼び出しは冪等か（再実行して安全か）
3. 失敗時にどのログを残すべきか

## 例外の基本分類
代表的な例外は次のグループに整理できます。

### 非リトライ（原則すぐ失敗として扱う）
- `InvalidArgument`
- `FailedPrecondition`
- `OutOfRange`
- `PermissionDenied`
- `Unauthenticated`
- `NotFound`（要件次第で許容するケースあり）
- `AlreadyExists`（作成 API では成功相当として扱える場合あり）
- `Unimplemented`

### リトライ候補（一時障害）
- `TooManyRequests` / `ResourceExhausted`
- `ServiceUnavailable` / `Unavailable`
- `InternalServerError` / `Internal`
- `DeadlineExceeded`
- `Aborted`
- `Unknown`（一時障害の可能性がある場合のみ）

### 要注意
- `RetryError`: ライブラリ側のリトライが最終的に失敗した状態。`cause` を確認して最終原因を記録する。
- `GoogleAPICallError`: API 呼び出し失敗の基底例外。個別分類できない場合のフォールバックに使う。
- `Cancelled`: 呼び出しキャンセル。アプリ終了やユーザー操作由来かを区別して扱う。

## 推奨ハンドリング方針
### 1. リトライ不可を先に分岐
`InvalidArgument` などの恒久的エラーは即時失敗として返し、無駄な再試行を避けます。

### 2. リトライは backoff + jitter
固定間隔ではなく指数バックオフを使い、少量のランダム値（jitter）を加えて同時再試行の集中を避けます。

### 3. 最大試行回数とタイムアウトを明示
無限リトライを避け、`max_retries` と 1 回あたりの timeout（deadline）を明確に設定します。

### 4. 冪等性を必ず確認
作成系・更新系 API は、再送で重複作成や上書きが起きないかを事前に確認します。

### 5. ログは「再現に必要な最小情報」を残す
例: operation 名、resource 識別子、attempt 回数、例外型、メッセージ。
資格情報やトークンはログに出力しません。

## 実装テンプレート（同期）
```python
from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from google.api_core import exceptions

T = TypeVar("T")


def call_with_retry(func: Callable[[], T], *, max_retries: int = 5, base_delay: float = 0.5) -> T:
    """Call Google Cloud API with categorized exception handling."""
    for attempt in range(max_retries + 1):
        try:
            return func()
        except (
            exceptions.InvalidArgument,
            exceptions.PermissionDenied,
            exceptions.Unauthenticated,
            exceptions.FailedPrecondition,
            exceptions.OutOfRange,
            exceptions.Unimplemented,
        ) as err:
            msg = f"Non-retriable Google API error: {type(err).__name__}: {err}"
            raise RuntimeError(msg) from err
        except (
            exceptions.TooManyRequests,
            exceptions.ResourceExhausted,
            exceptions.ServiceUnavailable,
            exceptions.InternalServerError,
            exceptions.DeadlineExceeded,
            exceptions.Aborted,
        ) as err:
            if attempt >= max_retries:
                msg = f"Google API retry exhausted: {type(err).__name__}: {err}"
                raise RuntimeError(msg) from err
            delay = base_delay * (2**attempt)
            jitter = random.uniform(0.0, delay * 0.1)
            time.sleep(delay + jitter)
        except exceptions.GoogleAPICallError as err:
            if attempt >= max_retries:
                msg = f"Google API call failed: {type(err).__name__}: {err}"
                raise RuntimeError(msg) from err
            delay = base_delay * (2**attempt)
            jitter = random.uniform(0.0, delay * 0.1)
            time.sleep(delay + jitter)

    msg = "Unexpected retry loop termination"
    raise RuntimeError(msg)
```

## 実装テンプレート（非同期）
非同期処理では `time.sleep` ではなく `asyncio.sleep` を使用してください。

```python
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google.api_core import exceptions

T = TypeVar("T")


async def call_with_retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    max_retries: int = 5,
    base_delay: float = 0.5,
) -> T:
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except (
            exceptions.InvalidArgument,
            exceptions.PermissionDenied,
            exceptions.Unauthenticated,
            exceptions.FailedPrecondition,
            exceptions.OutOfRange,
            exceptions.Unimplemented,
        ) as err:
            msg = f"Non-retriable Google API error: {type(err).__name__}: {err}"
            raise RuntimeError(msg) from err
        except (exceptions.TooManyRequests, exceptions.ServiceUnavailable, exceptions.DeadlineExceeded) as err:
            if attempt >= max_retries:
                msg = f"Google API retry exhausted: {type(err).__name__}: {err}"
                raise RuntimeError(msg) from err
            delay = base_delay * (2**attempt)
            jitter = random.uniform(0.0, delay * 0.1)
            await asyncio.sleep(delay + jitter)

    msg = "Unexpected retry loop termination"
    raise RuntimeError(msg)
```

## 追加ガイド
- SDK 組み込みリトライがある API と自前リトライが重複しないように設計する。
- ストリーミング API は再接続時の再開位置（offset / cursor）を設計する。
- `NotFound` は「本当に異常」か「存在しないことが正常」かを仕様で明確化する。
- `AlreadyExists` は冪等作成の成功相当として扱える場合がある。
- リトライ対象外の例外は、早期に利用者へ明示的に返す。

## 最低限のチェックリスト
- リトライ不可例外を先に `except` している
- `max_retries` と timeout が固定値で管理されている
- backoff と jitter を実装している
- 例外ログに operation / resource / attempt が含まれている
- 機密情報をログ出力していない

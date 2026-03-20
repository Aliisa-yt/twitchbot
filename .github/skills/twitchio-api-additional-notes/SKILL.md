---
name: twitchio-api-additional-notes
description: TwitchIOの処理において、処理の流れを改善するために使えそうなAPIのリスト。このAPIを活用することで、コードの可読性や保守性を向上させることができる可能性がある。
keywords: [TwitchIO, API, event driven, safe_dispatch, wait_for, wait_until_ready, Component, listener]
---

# TwitchIO API 追加メモ

現在の実装を改善するために活用できる可能性のある TwitchIO API のリファレンスメモ。
実際に採用するかどうかは別途検討が必要であり、このファイルは検討の入り口として参照することを目的としている。

## API 早見表

| メソッド | 概要 |
|---|---|
| `Client.safe_dispatch` | 任意のユーザー定義イベントを安全に発行する |
| `Client.wait_for` | イベントが発生するまで非同期に待機する（`safe_dispatch` イベントも対象） |
| `Client.wait_until_ready` | クライアントが Twitch に接続して準備完了になるまで待機する |
| `Component.listener` | クラスメソッドを TwitchIO のイベントリスナーとして登録するデコレータ |
| `Client.add_listener` | 任意の非同期関数を TwitchIO のイベントリスナーとして動的に登録する |
| `Client.remove_listener` | `add_listener` で登録したイベントリスナーを削除する |


## 1. イベント駆動型の処理 API

TwitchIO はイベント駆動型のフレームワークであり、カスタムイベントを組み合わせることで処理を疎結合に分割できる可能性がある。
例えば、翻訳完了イベントを発行し、TTS 処理をそのリスナーとして実装するような構成が考えられる。

### 1.1 任意のユーザーイベントを発行する API: `safe_dispatch`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.safe_dispatch

**シグネチャ**

```python
def safe_dispatch(name: str, *, payload: Any | None = None) -> None:
```

**動作**

- `name` に指定したイベント名に `event_safe_` を接頭辞として付加したリスナー (`event_safe_<name>`) を呼び出す。
- イベントの発行はどこからでも可能だが、リスナーの定義は `Component` クラス内でのみ有効。
- 複数箇所から同じイベントを発行することは可能だが、順序保証はないため、1 イベントにつき 1 箇所からの発行が望ましい。
- `payload` はリスナーに渡される任意のデータで、リスナー側で適切に型注釈を付けることが推奨される。
- イベントが実際に発行される遅延時間やタイミングは保証されていないため、リアルタイム性が必要な処理には適さない可能性がある。
- **重要**: このメソッドをオーバーライドすることは厳禁。TwitchIO 自体のイベントシステムが正常に動作しなくなる。

**使用例**

```python
class CoolPayload:

    def __init__(self, number: int) -> None:
        self.number = number

class CoolComponent(commands.Component):

    @commands.Component.listener()
    async def event_safe_cool(self, payload: CoolPayload) -> None:
        print(f"Received 'cool' event with number: {payload.number}")

# Somewhere...
payload = CoolPayload(number=9)
client.safe_dispatch("cool", payload=payload)  # payload はキーワード専用引数
```

### 1.2 WebSocket イベントを待機する API: `wait_for`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.wait_for

**シグネチャ**

```python
async def wait_for(
    event: str,
    *,
    timeout: float | None = None,
    predicate: WaitPredicateT | None = None,
) -> Any:
```

**動作**

- TwitchIO のイベントシステムで発生したすべてのイベントを非同期に待機する（`safe_dispatch` で発行したカスタムイベントも含む）。
- `event` には `event_` 接頭辞を除いたイベント名を指定する（例: `"chat_message"`）。
  - `safe_dispatch("cool", ...)` で発行したイベントを待機する場合は `wait_for("safe_cool")` と指定する。  
    これは `safe_dispatch` が内部で `dispatch("safe_cool", ...)` を呼び、リスナー名が `"event_safe_cool"` になるためであり、`wait_for("safe_cool")` も同じキーでウェイターを登録するため一致する。  
    （ソースコード: `safe_dispatch` → `dispatch(f"safe_{name}", ...)` → `_wait_fors["event_safe_cool"]`）
- `timeout` を省略した場合は無期限に待機するため、必要に応じてタイムアウト値を指定すること。  
  タイムアウト時は `TimeoutError` が送出される（TwitchIO ソースコードも `TimeoutError` を使用しており、プロジェクト規約と一致する）。
- `predicate` を指定することで条件フィルタリングが可能。条件を満たすイベントのみを受け取る。

**使用例**

```python
# 通常イベント: chat_message が発生するまで最大 10 秒待機する
try:
    payload = await client.wait_for("chat_message", timeout=10.0)
except TimeoutError:
    print("Timed out waiting for chat_message")

# safe_dispatch イベント: safe_dispatch("cool") を待機する場合は "safe_cool" を指定する
try:
    payload = await client.wait_for("safe_cool", timeout=5.0)
except TimeoutError:
    print("Timed out waiting for safe_cool")
```

### 1.3 接続完了を待機する API: `wait_until_ready`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.wait_until_ready

**シグネチャ**

```python
async def wait_until_ready() -> None:
```

**動作**

- クライアントが Twitch に接続して `event_ready` が発行されるまで待機する。
- 既に接続済みの場合は即座に完了するため、接続状態を気にせずに呼び出せる。
- `safe_dispatch` 等を利用する前に呼び出すことで、クライアントが未接続の状態でイベントが発行される問題を回避できる。
- **注意**: `safe_dispatch` で発行したカスタムイベントを待機する用途には使用できない。(event_ready待機専用のため)

**使用例**

```python
async def start_processing(client: twitchio.Client) -> None:
    await client.wait_until_ready()
    # クライアント接続後に処理を開始する
    client.safe_dispatch("start", payload=None)
```


### 1.4 リスナー定義 API: `Component.listener`

クラス名: `twitchio.commands.Component`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/components.html#twitchio.ext.commands.Component.listener

**シグネチャ**

```python
classmethod listener(name: str | None = None) -> Any:
```

**動作**

- クラスメソッドにデコレータとして適用することで、そのメソッドを TwitchIO のイベントリスナーとして登録する。
- `safe_dispatch` で発行したイベントをリスンする場合は、イベント名に `event_safe_` を接頭したメソッド名を定義する必要がある（例: `event_safe_cool`）。
- TwitchIO のイベントシステムの一部であるイベントをリスンする場合は、イベント名に `event_` を接頭したメソッド名を定義する必要がある（例: `event_message`）。
- リスナーは非同期関数である必要がある。

**使用例**

```python
class MyComponent(commands.Component):

    @commands.Component.listener()
    async def event_message(self, message: twitchio.Message) -> None:
        print(f"Received message: {message.content}")
```


### 1.5 イベントリスナーの追加 API: `Client.add_listener`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.add_listener

**シグネチャ**

```python
def add_listener(listener: Callable[..., Coroutine[Any, Any, None]], *, event: str | None = None) -> None:
```

**動作**

- 任意の非同期関数を TwitchIO のイベントリスナーとして動的に登録する。
- `event` を指定した場合は、イベント名に `event_` を接頭したメソッド名を定義する必要がある（例: `event_custom`）。
- `event` を省略した場合は、関数名に `event_` を接頭したメソッド名を定義する必要がある（例: `event_cool`）。
- TwitchIO のイベントシステムの一部であるイベントをリスンする場合は、イベント名に `event_` を接頭したメソッド名を定義する必要がある（例: `event_message`）。
- リスナーは非同期関数である必要がある。

**使用例**

```python
async def my_listener(event_data: Any) -> None:
    print(f"Received event data: {event_data}")

component = commands.Component()
component.add_listener(my_listener, event="custom")  # イベント名は "custom"
```


### 1.6 イベントリスナーの削除 API: `Client.remove_listener`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.remove_listener

**シグネチャ**

```python
def remove_listener(listener: Callable[..., Coroutine[Any, Any, None]]) -> Callable[..., Coroutine[Any, Any, None]] | None:
```

**動作**

- `add_listener` で登録したイベントリスナーを削除する。
- `listener` と `event` の組み合わせで特定のリスナーを指定する必要がある。
- 登録されていないリスナーを削除しようとした場合はエラーが発生する。
- TwitchIO のイベントシステムの一部であるイベントをリスンする場合は、イベント名に `event_` を接頭したメソッド名を定義する必要がある（例: `event_message`）。
- リスナーは非同期関数である必要がある。

**使用例**

```python
async def my_listener(event_data: Any) -> None:
    print(f"Received event data: {event_data}")
component = commands.Component()
component.add_listener(my_listener, name="custom")  # イベント名は "custom"
# 後でリスナーを削除する
component.remove_listener(my_listener, name="custom")
```


## 2. 検討時の注意点

- これらの API を採用する場合、変更量が多くなることが予想されるため、波及範囲を十分に考慮した上で作業量を見積もり、段階的に進めることが重要。
- イベント駆動に変更する場合は、イベントの発行・リスン箇所の設計と、イベントデータの構造を事前に整理すること。
- 変更する際は、実装・テスト・ドキュメントを同一変更で整合させること。

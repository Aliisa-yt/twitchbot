---
name: future-implementation
description: TwitchBot の将来の実装に関する情報を提供する。イベント駆動型処理の構築やリファクタリング時に参考にするためのドキュメント。
keywords: [TwitchIO, API, future implementation, event driven, refactoring, design decisions, architecture]
---

# TwitchBot 将来の実装に関する情報

TwitchBot のリファクタリングや機能追加を行う際に、適切な API や設計方針を選択できるよう、参考情報を整理したドキュメントです。

## API 早見表

| メソッド | 概要 |
|---|---|
| `Bot.save_tokens` | TwitchIO の内部で管理しているトークンを保存する |
| `Bot.load_tokens` | ファイルからトークンを読み込み TwitchIO の内部で管理する |
| `Bot.start` | Bot を起動するための非同期メソッド |
| `Bot.start_dcf` | Device Code Flow を使用して Bot を起動するための非同期メソッド |
| `Bot.login_dcf` | Device Code Flow を使用して Bot にログインするための非同期メソッド |
| `Client.safe_dispatch` | 任意のユーザー定義イベントを安全に発行する |
| `Client.wait_for` | イベントが発生するまで非同期に待機する（`safe_dispatch` イベントも対象） |
| `Client.wait_until_ready` | クライアントが Twitch に接続して準備完了になるまで待機する |
| `Component.listener` | クラスメソッドを TwitchIO のイベントリスナーとして登録するデコレータ |
| `Client.add_listener` | 任意の非同期関数を TwitchIO のイベントリスナーとして動的に登録する |
| `Client.remove_listener` | `add_listener` で登録したイベントリスナーを削除する |
| `Client.listen` | クラスメソッドを TwitchIO のイベントリスナーとして登録するデコレータ（Component.listener と似ているが Client クラスのメソッド） |

## 1. TwitchIO API 情報

TwitchIO の API に関する情報を整理することで、将来の実装において適切な API を選択しやすくなります。

### 1.1 認証に関する API

TwitchIO には、トークンの保存・読み込みや Bot の起動に関する API が用意されており、これらを活用することで認証関連の処理を効率的に実装できる可能性があります。

#### 1.1.1 トークン保存 API: `Bot.save_tokens`

クラス名: `twitchio.ext.commands.Bot`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/bot.html#twitchio.ext.commands.Bot.save_tokens

**シグネチャ**

```python
async def save_tokens(self, path: str | None = None, /) -> None:
```

**動作**

- 指定されたパスにトークン情報を JSON 形式で保存する。
- パスが `None` の場合はデフォルトの保存先 `.tio.tokens.json` を使用する。
- TwitchIO 内部で終了処理（`close()` が呼び出されたとき）に呼び出される。
- このメソッドをオーバーライドすることで、終了時のトークン保存をカスタマイズすることができる。
- Bot 起動中のトークンリフレッシュでは、このメソッドは呼び出されないため、リフレッシュ後のトークンを保存するには `add_token` 内で行う必要がある。

**使用例**

```python
class MyBot(commands.Bot):
    async def save_tokens(self, path: str | None = None) -> None:
        # トークンを DB に保存するカスタム実装
        token_data = {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": self.token_expires_in,
            "obtained_at": self.token_obtained_at,
            "scope": self.token_scope,
            "token_type": self.token_type,
        }
        # DB に保存する処理をここに実装する
```

#### 1.1.2 トークン読み込み API: `Bot.load_tokens`

クラス名: `twitchio.ext.commands.Bot`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/bot.html#twitchio.ext.commands.Bot.load_tokens

**シグネチャ**

```python
async def load_tokens(self, path: str | None = None, /) -> None:
```

**動作**

- 指定されたパスからトークン情報を JSON 形式で読み込む。
- パスが `None` の場合はデフォルトの保存先 `.tio.tokens.json` を使用する。
- TwitchIO 内部で Bot 起動時にトークンを読み込むため、このメソッドをオーバーライドすることで、起動時のトークン読み込みをカスタマイズすることができる。
- 現在は `setup_tokens.py` 内でトークンを取得して `Bot` のコンストラクタに渡す実装になっているが、`load_tokens` をオーバーライドして DB からトークンを読み込む実装に変更することで、Bot 起動時のトークン読み込みを一元化できる。
- `save_tokens` と `load_tokens` の両方をオーバーライドして DB に保存・読み込みする実装に変更した場合は、`setup_tokens.py` 内で `TokenManager` を使用してトークンを取得し DB に保存する処理のみに限定できる。また `.tio.tokens.json` を使用せず DB のみでトークン管理を行う実装に変更することもできる（現在は二重管理状態）。

**使用例**

```python
class MyBot(commands.Bot):
    async def load_tokens(self, path: str | None = None) -> None:
        # DB からトークンを読み込むカスタム実装
        # DB からトークンを取得する処理をここに実装する
        token_data = {
            "access_token": ...,
            "refresh_token": ...,
            "expires_in": ...,
            "obtained_at": ...,
            "scope": ...,
            "token_type": ...,
        }
        self.access_token = token_data["access_token"]
        self.refresh_token = token_data["refresh_token"]
        self.token_expires_in = token_data["expires_in"]
        self.token_obtained_at = token_data["obtained_at"]
        self.token_scope = token_data["scope"]
        self.token_type = token_data["token_type"]
```

#### 1.1.3 Bot 起動 API: `Bot.start`

クラス名: `twitchio.ext.commands.Bot`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/bot.html#twitchio.ext.commands.Bot.start

**シグネチャ**

```python
async def start(token: str | None = None, *, with_adapter: bool = True, load_tokens: bool = True, save_tokens: bool = True) -> None
```

**パラメータ**

- `token`: 起動時に使用するアクセストークン。`None` の場合は `load_tokens` が `True` のときに `load_tokens()` を呼び出してトークンを読み込む。
- `with_adapter`: 内蔵アダプターを使用して WebSocket 接続を行うかどうか。デフォルトでは`True`。
  本アプリでは、独自の接続管理を行っているため `False` に設定している。
- `load_tokens`: 起動時に `load_tokens()` を呼び出してトークンを読み込むかどうか。デフォルトでは `True`。
- `save_tokens`: 終了時（`close()` が呼び出されたとき）に `save_tokens()` を呼び出してトークンを保存するかどうか。デフォルトでは `True`。

**動作**

- Bot を起動するための非同期メソッド。
- 内部でイベントループを開始し、Bot の接続やイベント処理を行う。
- 起動後、`event_ready` が発行されるため、このイベント内で `add_token` を呼び出してトークンを登録するのが一般的なパターンである。
- `start` メソッドは通常、Bot のエントリーポイントとして使用され、コマンドの登録やイベントリスナーの定義など、Bot の初期化処理を行った後に呼び出される。

**使用例**

```python
if __name__ == "__main__":
    bot = MyBot(...)
    asyncio.run(bot.start())
```

#### 1.1.4 Bot 起動（DCF認証） API: `Bot.start_dcf`

クラス名: `twitchio.ext.commands.Bot`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/bot.html#twitchio.ext.commands.Bot.start_dcf

**シグネチャ**

```python
async def start_dcf(*, device_code: str | None = None, interval: int = 5, timeout: int | None = 90, scopes: twitchio.authentication.scopes.Scopes | None = None, block: bool = True) -> None
```

**パラメータ**

- `device_code`: 事前に取得したデバイスコード。`None` の場合は `start_dcf()` 内でデバイスコードを取得する。
- `interval`: デバイスコードのポーリング間隔（秒）。デフォルトは 5 秒。
- `timeout`: デバイスコードの有効期限（秒）。デフォルトは 90 秒。`None` の場合は無制限。
- `scopes`: 認証に必要なスコープ。`None` の場合は `ACCESS_SCOPES` が使用される。
- `block`: 認証が完了するまで `start_dcf()` をブロックするかどうか。デフォルトは `True`。

**動作**

- Device Code Flow を使用して Bot を起動するための非同期メソッド。
- デバイスコードを取得し、ユーザーに認証を促すための URL を表示する。
- ユーザーが認証を完了するまで、指定された間隔でデバイスコードの状態をポーリングする。
- 認証が完了すると、アクセストークンを取得して Bot を起動する。
- `start_dcf` は通常、ユーザーがブラウザでの認証を行うことができない環境で使用される（例: CLI 環境やリモートサーバーなど）。
- **重要**: `start_dcf` は、`login_dcf` で取得したトークンを使用して Bot を起動するため、先に `login_dcf` メソッドを呼び出す必要がある。
- **重要**: 将来の拡張で DCF 認証をサポートする場合は、`start_dcf` と `login_dcf` を組み合わせて使用する実装を検討する必要がある。

#### 1.1.5 Bot へのログイン（DCF認証） API: `Bot.login_dcf`

クラス名: `twitchio.ext.commands.Bot`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/bot.html#twitchio.ext.commands.Bot.login_dcf

**シグネチャ**

```python
async def login_dcf(*, load_token: bool = True, save_token: bool = True, scopes: Scopes | None = None, force_flow: bool = False) -> DeviceCodeFlowResponse | None
```

**パラメータ**

- `load_token`: ログイン前に `load_tokens()` を呼び出してトークンを読み込むかどうか。デフォルトは `True`。
- `save_token`: ログイン後に `save_tokens()` を呼び出してトークンを保存するかどうか。デフォルトは `True`。
- `scopes`: 認証に必要なスコープ。`None` の場合は `ACCESS_SCOPES` が使用される。
- `force_flow`: 既存のトークンが存在しても Device Code Flow を強制的に実行するかどうか。デフォルトは `False`。

**動作**

- Device Code Flow を使用して Bot にログインするための非同期メソッド。
- `load_token` が `True` の場合は、ログイン前に `load_tokens()` を呼び出してトークンを読み込む。
- 既存のトークンが有効であればそれを使用し、無効であれば Device Code Flow を実行する。
- `force_flow` が `True` の場合は、既存のトークンが有効であっても Device Code Flow を強制的に実行する。
- ログインが成功すると、アクセストークンを取得して Bot に登録する。
- `login_dcf` は通常、ユーザーがブラウザでの認証を行うことができない環境で使用される（例: CLI 環境やリモートサーバーなど）。
- **重要**: 将来の拡張で DCF 認証をサポートする場合は、`start_dcf` と `login_dcf` を組み合わせて使用する実装を検討する必要がある。


### 1.2 イベント駆動型の処理 API

TwitchIO はイベント駆動型のフレームワークであり、カスタムイベントを組み合わせることで処理を疎結合に分割できる可能性がある。
例えば、翻訳完了イベントを発行し、TTS 処理をそのリスナーとして実装するような構成が考えられる。

#### 1.2.1 任意のユーザーイベントを発行する API: `safe_dispatch`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.safe_dispatch

**シグネチャ**

```python
def safe_dispatch(name: str, *, payload: Any | None = None) -> None:
```

**動作**

- `name` に指定したイベント名に対して `event_safe_` 系のカスタムイベントを発行する。
- イベントの発行はどこからでも可能だが、リスナーの定義は `Component` クラス内でのみ有効。
- 複数箇所から同じイベントを発行することは可能だが、順序保証はないため、1 イベントにつき 1 箇所からの発行が望ましい。
- `payload` はリスナーに渡される任意のデータで、リスナー側で適切に型注釈を付けることが推奨される。
- イベントが実際に発行される遅延時間やタイミングは保証されていないため、リアルタイム性が必要な処理には適さない可能性がある。
- **重要**: イベント名の命名・表記（小文字スネークケース、プレフィックス規則）は `event-naming-rules` を参照すること。
- **重要**: このメソッドをオーバーライドすることは厳禁。TwitchIO 自体のイベントシステムが正常に動作しなくなる。
- **重要**: `safe_dispatch` で発行したイベントはリスナーで受信されるが、リスナーの処理結果を `safe_dispatch` の呼び出し元に返すことはできない。処理の流れは一方向であり、イベント駆動型の処理を構築する際は、必要に応じてリスナー側で状態を更新したり、別のイベントを発行するなどして、処理の流れを設計する必要がある。

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

データを渡さない場合は `payload` を省略することも可能。

```python
class CoolComponent(commands.Component):

    @commands.Component.listener()
    async def event_safe_cool(self) -> None:  # payload を受け取らない場合は引数から省略しても良い
        print(f"Received 'cool' event without payload")

# Somewhere...
client.safe_dispatch("cool")  # payload を省略
```

#### 1.2.2 WebSocket イベントを待機する API: `wait_for`

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
- `event` で指定するイベント名の形式（`event_` 省略ルールなど）は `event-naming-rules` を参照する。
- `timeout` を省略した場合は無期限に待機するため、必要に応じてタイムアウト値を指定すること。  
  タイムアウト時は `TimeoutError` が送出される（TwitchIO ソースコードも `TimeoutError` を使用しており、プロジェクト規約と一致する）。
- `predicate` を指定することで条件フィルタリングが可能。条件を満たすイベントのみを受け取る。
- **重要**: `safe_dispatch` の後に `wait_for` を呼び出す場合、イベントを受け取れずタイムアウトしてしまう。
  - `dispatch` は呼び出された瞬間に `_wait_fors` を同期的に参照してウェイターへ通知する。そのため、`safe_dispatch` を呼んだ後から `wait_for` を登録しても、既に `dispatch` がウェイターへの通知を終えているため受け取れない。これは「他に処理しているイベントがある/ない」に関係なく常に起こる。
  - `safe_dispatch` と `wait_for` を組み合わせる場合は、先に `wait_for` を呼び出してウェイターを登録してから `safe_dispatch` を呼び出す必要がある。

**使用例**

```python
# 通常イベント: chat_message が発生するまで最大 10 秒待機する
try:
    payload = await client.wait_for("chat_message", timeout=10.0)
except TimeoutError:
    print("Timed out waiting for chat_message")

# safe_dispatch イベント: wait_for を先に登録してから safe_dispatch を呼び出す必要がある

# NG: safe_dispatch の後に wait_for を呼ぶとイベントを受け取れずタイムアウトする
# client.safe_dispatch("cool", payload=some_payload)
# payload = await client.wait_for("safe_cool", timeout=5.0)  # タイムアウトする

# OK: wait_for をタスクとして先に登録し、イベントループに yield してウェイター登録を完了させてから safe_dispatch を呼び出す
waiter_task = asyncio.create_task(client.wait_for("safe_cool", timeout=5.0))
await asyncio.sleep(0)  # タスクを実行してウェイターを _wait_fors に登録させる
client.safe_dispatch("cool", payload=some_payload)
try:
    payload = await waiter_task
except TimeoutError:
    print("Timed out waiting for safe_cool")
```

#### 1.2.3 接続完了を待機する API: `wait_until_ready`

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
- **注意**: `safe_dispatch` で発行したカスタムイベントを待機する用途には使用できない（`event_ready` 待機専用）。

**使用例**

```python
async def start_processing(client: twitchio.Client) -> None:
    await client.wait_until_ready()
    # クライアント接続後に処理を開始する
    client.safe_dispatch("start", payload=None)
```


#### 1.2.4 リスナー定義 API: `Component.listener`

クラス名: `twitchio.commands.Component`
公式ドキュメント: https://twitchio.dev/en/latest/exts/commands/components.html#twitchio.ext.commands.Component.listener

**シグネチャ**

```python
def listener(name: str | None = None) -> Any: ...
```

**動作**

- クラスメソッドにデコレータとして適用することで、そのメソッドを TwitchIO のイベントリスナーとして登録する。
- イベント名の指定方法（メソッド名一致 / 引数指定時の命名）は `event-naming-rules` を参照する。
- リスナーは非同期関数である必要がある。
- **重要**: パラメーターを受け取るときは、payload をキーワード専用引数として定義することが推奨される。  
  例: `async def event_safe_cool(self, payload: CoolPayload) -> None` のように定義する。  
  これは、`safe_dispatch` が `payload` をキーワード専用引数として渡すためであり、位置引数として定義した場合はエラーが発生する可能性があるためである。
  パラメータが不要なイベントの場合は、self のみで、payload の記述は不要である。
- **重要**: リスナーは戻り値を返すことができない。そのため None を返すように定義することが推奨される（例: `async def event_safe_cool(...) -> None`）。
  これは、TwitchIO のイベントシステムがリスナーの戻り値を処理しないためであり、戻り値を返すように定義した場合は、意図しない動作やエラーが発生する可能性があるためである。

**使用例**

```python
class MyComponent(commands.Component):

    @commands.Component.listener()  # 引数を省略した場合は、メソッド名を正式なイベント名にする
    async def event_message(self, payload: twitchio.Message) -> None:
        print(f"Received message: {payload.content}")
```

```python
class MyComponent(commands.Component):

    @commands.Component.listener("message")  # 引数でイベント名を指定した場合は、メソッド名は任意でよい
    async def some_method(self, payload: twitchio.Message) -> None:
        print(f"Received message: {payload.content}")
```

パラメータが不要なイベントの場合は、payload を定義せずに self のみでリスナーを定義することも可能。

```python
class MyComponent(commands.Component):

    @commands.Component.listener()
    async def event_ready(self) -> None:
        print("Client is ready!")
```


#### 1.2.5 イベントリスナーの追加 API: `Client.add_listener`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.add_listener

**シグネチャ**

```python
def add_listener(listener: Callable[..., Coroutine[Any, Any, None]], *, event: str | None = None) -> None:
```

**動作**

- 任意の非同期関数を TwitchIO のイベントリスナーとして動的に登録する。
- イベント名指定の詳細ルール（プレフィックスの扱い）は `event-naming-rules` を参照する。
- リスナーは非同期関数である必要がある。

**使用例**

```python
async def my_listener(event_data: Any) -> None:
    print(f"Received event data: {event_data}")

component = commands.Component()
component.add_listener(my_listener, event="custom")  # イベント名は "custom"
```


#### 1.2.6 イベントリスナーの削除 API: `Client.remove_listener`

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
- イベント名指定の詳細ルール（プレフィックスの扱い）は `event-naming-rules` を参照する。
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


#### 1.2.7 リスナー定義 API: `Client.listen`

クラス名: `twitchio.Client`
公式ドキュメント: https://twitchio.dev/en/latest/references/client.html#twitchio.Client.listen

**シグネチャ**

```python
def listen(self, event: str) -> Callable[..., Coroutine[Any, Any, None]]:
```

**動作**

- クラスメソッドにデコレータとして適用することで、そのメソッドを TwitchIO のイベントリスナーとして登録する。
- `event` の指定形式（`event_` の扱いを含む）は `event-naming-rules` を参照する。
- リスナーは非同期関数である必要がある。

**Client.listen() と Component.listener() の違い**
- 両者ともにイベントリスナーを定義するためのデコレータであるが、`Client.listen()` は `twitchio.Client` クラスのメソッドであるのに対し、`Component.listener()` は `twitchio.commands.Component` クラスのクラスメソッドである点が異なる。
- `Client.listen()` はインスタンスメソッドとして使用されることが一般的であるのに対し、`Component.listener()` はクラスメソッドとして使用されることが一般的である。
- どちらもイベント名の指定方法は同じであるが、`Client.listen()` はクライアント全体のイベントをリスンするため、よりグローバルなイベントリスナーを定義するのに適しているのに対し、`Component.listener()` は特定のコンポーネントに関連するイベントをリスンするのに適している。

**使用例**

```python
class MyClient(twitchio.Client):

    @MyClient.listen("chat_message")
    async def handle_chat_message(self, payload: twitchio.Message) -> None:
        print(f"Received message: {payload.content}")
```

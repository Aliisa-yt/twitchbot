---
name: twitch-auth-flow
description: Twitch OAuth2 認証フローの全体設計、TokenManager/TokenStorage の責務、キャッシュ検証、トークンリフレッシュ、トラブルシューティングの実装指針
keywords: [twitch, oauth2, token, auth, token_manager, token_storage, refresh, bot, setup_tokens, authorization_code_flow]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は、Twitch 認証（OAuth2 Authorization Code Flow）の全体設計と、各ステージの実装詳細を定義します。
`src/setup_tokens.py` によるトークン取得から、`Bot` 起動後のトークンリフレッシュまでをカバーします。

---

## 1. 概要

Twitchbot は **Bot ユーザー専用の OAuth2 トークン** でチャットおよびイベント購読を行います。
トークン管理は以下の 3 層に分かれています。

| 層 | クラス | ファイル | 責務 |
|---|---|---|---|
| 永続化 | `TokenStorage` | `src/core/token_storage.py` | SQLite3 によるトークンの読み書き・削除 |
| フロー制御 | `TokenManager` | `src/core/token_manager.py` | OAuth フロー実行・トークン検証・キャッシュ確認・トークン形式変抛 |
| Bot 統合 | `Bot.event_token_refreshed` / `Bot.load_tokens` | `src/core/bot.py` | TwitchIO へのトークン登録・起動時読み込み・リフレッシュ時 DB 更新 |

---

## 2. 関連ファイルと役割

### 2.1 `src/setup_tokens.py`
- **用途**: 初回セットアップまたはトークンリセット時にユーザーが手動実行するコンソールスクリプト。
- ログファイルは作成しない。すべての出力を stdout/stderr へ送る。
- 成功時に `tokens.db` へトークンを保存して終了する。

### 2.2 `src/core/token_manager.py`
- `TokenManager`: OAuth Authorization Code Flow の実行、キャッシュ確認、Bot ID 検証、トークン形式変換を担う。
- `UserIDs`: owner_id と bot_id を保持する frozen dataclass。
- モジュール定数 `REDIRECT_URI` / `ACCESS_SCOPES` は認証フローに使う定数。
- `converted_load_tokens()`: DB から読み込んだトークンを Bot クラス（TwitchIO 内部）で使用する形式へ変換して返す。
- `converted_save_tokens()`: Bot クラスのトークン形式（`self.tokens`）を DB 保存形式へ変換して保存する。`event_token_refreshed` 内から呼ばれる。

### 2.3 `src/core/token_storage.py`
- `TokenStorage`: SQLite3 context manager。`with` ブロック内で接続を開き、抜けると自動クローズ。
- テーブル: `tokens (key TEXT PRIMARY KEY, access_token, refresh_token, expires_in, obtained_at, scope, token_type)`
- デフォルトキー `"twitch_bot"` で読み書きする。

### 2.4 `src/core/bot.py`
- `Bot.__init__`: `config` と `token_manager` のみを受け取る。`client_id`/`client_secret`/`bot_id`/`owner_id`/`access_token`/`refresh_token`/`last_validated` はすべて `_token_manager` のプロパティへ委譲する。
- `Bot.load_tokens`: `TokenManager.converted_load_tokens()` 経由で DB からトークンを読み込み、`add_token()` を呼んで TwitchIO 内部の `self.tokens` へ反映する。`bot_id` 不一致または取得失敗の場合は `RuntimeError` を送出する。`.tio.tokens.json` は使用しない。
- `Bot.save_tokens`: 何もしない（終了時の `.tio.tokens.json` 書き込みを抑止するため空実装でオーバーライド）。
- `Bot.event_token_refreshed`: `add_token()` を呼んだ後、`validation_payload.user_id == self.bot_id` の場合のみ `TokenManager.converted_save_tokens()` を呼んで DB を更新する（owner トークンで上書きしない）。最新トークンは `self.tokens.get(self.bot_id)` から取得する。

---

## 3. 認証フロー全体

```
[起動前] setup_tokens.py
    └─ TokenManager.start_authorization_flow
          ├─ _get_id_by_name (App Token で owner/bot の ID を取得)
          ├─ TokenStorage.load_tokens (キャッシュ確認)
          │     ├─ キャッシュあり → _validate_access_token_user_id (所有者確認)
          │     │     ├─ bot_id と一致 → キャッシュ使用
          │     │     ├─ bot_id と不一致 → キャッシュ破棄 → _run_oauth_for_bot
          │     │     └─ 検証失敗 (期限切れ等) → _refresh_access_token (リフレッシュ試行)
          │     │           ├─ 成功 + bot_id 一致 → リフレッシュ済みトークンを保存して使用
          │     │           └─ 失敗 or bot_id 不一致 → キャッシュ破棄 → _run_oauth_for_bot
          │     └─ キャッシュなし → _run_oauth_for_bot
          │           ├─ _get_authorization_code_via_local_server (優先)
          │           │     └─ 失敗時フォールバック: _get_authorization_code_via_browser
          │           ├─ _exchange_code_for_tokens
          │           ├─ _validate_access_token_user_id (Bot ID 一致確認)
          │           └─ TokenStorage.save_tokens
          └─ TokenManager インスタンス変数 (user_access_token / refresh_token 等) を更新して完了
             ※ 戻り値なし

[Bot 起動中] Bot.start(with_adapter=False) → load_tokens → setup_hook → event_ready
    ├─ Bot.load_tokens (TokenManager.converted_load_tokens() 経由で DB 読み込み)
    │     └─ add_token(access_token, refresh_token) で TwitchIO 内部に登録
    └─ event_ready → _subscribe_to_chat_events
          └─ add_token(access_token, refresh_token) で WebSocket 購読に使用

[実行中] TwitchIO 自動リフレッシュ
    └─ event_token_refreshed(payload: TokenRefreshedPayload)
          └─ add_token(payload.token, payload.refresh_token) → ValidateTokenPayload
                ├─ validation_payload.user_id != bot_id? → スキップ
                └─ bot_id 一致 → self.tokens[bot_id] から最新トークン取得
                      └─ TokenManager.converted_save_tokens() → DB 更新
```

---

## 4. 各ステージの詳細

### 4.1 App Token によるユーザー ID 取得 (`_get_id_by_name`)
- `twitchio.Client` を App Token で初期化して `client.login()` → `fetch_users()` を呼ぶ。
- `fetch_users` の返り値の順序は保証されないため、`name.lower()` で照合する。
- owner と bot のどちらかが見つからない場合は `RuntimeError` を送出する。
- **注意**: `twitchio.Client` はここでのみ App Token として使用する。Bot 起動とは別インスタンス。

### 4.2 ローカルサーバーによる認可コード取得 (`_get_authorization_code_via_local_server`)
- `REDIRECT_URI` のホスト・ポート・パスを解析して `aiohttp` で一時 HTTP サーバーを起動。
- ブラウザで認可 URL を開き、リダイレクトを待つ（デフォルト 60 秒）。
- コールバックで `?code=` を受け取ったら `code_future` に結果をセットしてサーバーを停止。
- `TimeoutError` または `OSError`（ポート競合など）が発生した場合は手入力フォールバックへ移行。
> **参考**:
Twitch には内蔵アダプターとして `StarletteAdapter` や `AiohttpAdapter` が用意されており、これらを使用して認証することが可能である。
但し、内蔵アダプターでの認証タイミングは Botクラスの `__init__()` の呼び出し時に限られる。
URL: https://twitchio.dev/en/latest/references/web.html#
本アプリでは、Bot 起動前の `setup_tokens.py` で認証を完結させるために独自実装する。

### 4.3 ブラウザ手入力フォールバック (`_get_authorization_code_via_browser`)
- `webbrowser.open()` で認可 URL を開き、ユーザーにリダイレクト URL の貼り付けを求める。
- `input()` が `EOFError` を送出した場合（非インタラクティブ端末）は `RuntimeError` を送出する。

### 4.4 認可コードとトークンの交換 (`_exchange_code_for_tokens`)
- `POST https://id.twitch.tv/oauth2/token` に form data として送信。
- `raise_for_status=True` の `aiohttp.ClientSession` を使用し、HTTP エラーは例外になる。
- レスポンスに `access_token` が含まれない場合は `RuntimeError` を送出する。
- `obtained_at = time.time()` をレスポンスに追加して保存する（有効期限計算用）。

### 4.5 アクセストークンのリフレッシュ (`_refresh_access_token`)
- `POST https://id.twitch.tv/oauth2/token` に `grant_type=refresh_token` で form data として送信。
- `raise_for_status=True` の `aiohttp.ClientSession` を使用し、HTTP エラーは例外になる。
- レスポンスに `access_token` が含まれない場合は `RuntimeError` を送出する。
- `obtained_at = time.time()` をレスポンスに追加して保存する。
- **呼び出し側の責務**: リフレッシュ後に `_validate_access_token_user_id` で bot_id が一致することを確認してから永続化する。

### 4.6 トークン所有者確認 (`_validate_access_token_user_id`)
- `GET https://id.twitch.tv/oauth2/validate` に `Authorization: OAuth <token>` ヘッダーで問い合わせ。
- HTTP 200 以外は `RuntimeError`。
- レスポンスに `user_id` がない場合は App Token として扱われている可能性があるため `RuntimeError`。

### 4.7 キャッシュ検証とリフレッシュロジック
- キャッシュが存在し `access_token` がある場合 → `_validate_access_token_user_id` で所有者を確認。
- `token_user_id != self.bot_id` の場合（例：owner アカウントで誤認証）→ キャッシュを破棄して再認証。リフレッシュは試みない（refresh_token も同じユーザーのものであるため）。
- バリデーション自体が失敗した場合（トークン期限切れ等）→ `cached_refresh_token` があれば `_refresh_access_token` を試みる。
  - リフレッシュ成功 + `bot_id` 一致 → リフレッシュ済みトークンを DB へ保存して使用。OAuth フローは不要。
  - リフレッシュ失敗 or `bot_id` 不一致 → キャッシュを破棄して `_run_oauth_for_bot` を実行。
- **これにより、トークン期限切れ時に毎回ブラウザ認証が要求される問題を回避できる。**

---

## 5. 環境変数

| 変数名 | 必須 | 説明 |
|---|---|---|
| `TWITCH_API_CLIENT_ID` | ○ | Twitch Developer Console のクライアント ID |
| `TWITCH_API_CLIENT_SECRET` | ○ | Twitch Developer Console のクライアントシークレット |

- `TokenManager.__init__` の `_require_env_var` で両方の存在を確認する。未設定時は即座に `RuntimeError`。
- 値はログや例外メッセージに **絶対に出力しない**。

---

## 6. `REDIRECT_URI` の設定

```python
# core/token_manager.py
REDIRECT_URI: Final[str] = "http://localhost"
```

- `http://localhost` は Twitch Developer Console の「OAuth Redirect URLs」に登録が必要。
- ポート指定あり（例: `http://localhost:4343/oauth/callback`）に変更した場合はコンソール側も更新する。
- `REDIRECT_URI` のポートが 80 以外のとき → ローカルサーバーはそのポートを使う。
- `REDIRECT_URI` のパスが `/` 以外のとき → そのパスにルーティングされる。

---

## 7. `ACCESS_SCOPES` の設定

```python
ACCESS_SCOPES: Scopes = Scopes(
    chat_read=True,
    chat_edit=True,
    user_read_chat=True,
    user_write_chat=True,
    user_bot=True,
    user_manage_chat_color=True,
    channel_bot=True,
)
```

- スコープを変更する場合は `tokens.db` を削除して再認証が必要（既存トークンのスコープは変わらない）。

---

## 8. トークンリフレッシュ（Bot 実行中）

```
TwitchIO 内部 (自動)
    └─ Bot.event_token_refreshed(payload: TokenRefreshedPayload)
          └─ add_token(payload.token, payload.refresh_token) → ValidateTokenPayload
                ├─ validation_payload.user_id != bot_id? → スキップ
                └─ bot_id 一致 → self.tokens[bot_id] から最新トークン取得
                      └─ TokenManager.converted_save_tokens() → DB 更新
```

- TwitchIO はトークンの有効期限切れを検知すると自動でリフレッシュし `event_token_refreshed` を発火する。
- `event_token_refreshed` はその更新を DB に永続化する責務を持つ。`add_token` はオーバーライドしていない。
- DB 保存には `TokenManager.converted_save_tokens()` を使用し、TwitchIO 内部形式 (`self.tokens`) から DB 形式へ変換して保存する。
- **owner_id と bot_id の両方のトークンが TwitchIO 内部で管理されるため**、`user_id` の照合なしに全トークンを DB 保存すると bot トークンが owner トークンで上書きされる。必ず `bot_id` 一致確認を行うこと。

---

## 9. トークン受け渡し設計

```python
# twitchbot.py / setup_tokens.py
token_manager = TokenManager(token_db_path)
await token_manager.start_authorization_flow(owner_name, bot_name)
# start_authorization_flow は戻り値を返さない。
# 認証結果は TokenManager のインスタンス変数 (bot_id, owner_id, user_access_token 等) に格納される。

# Bot コンストラクタ
bot = Bot(config, token_manager)
```

- `TwitchBotToken` dataclass は廃止。`start_authorization_flow` は `None` を返す。
- `Bot.__init__` は `config` と `token_manager` のみを受け取る。
- `Bot.client_id`/`client_secret`/`bot_id`/`owner_id`/`access_token`/`refresh_token`/`last_validated` は `_token_manager` の属性へ委譲するプロパティとして実装されている。
- `Bot.load_tokens` をオーバーライドし、TwitchIO の起動シーケンス内で `TokenManager.converted_load_tokens()` 経由で DB からトークンを読み込む。`.tio.tokens.json` は使用しない。
- `Bot.save_tokens` をオーバーライドして空実装とし、終了時に `.tio.tokens.json` が生成されるのを防ぐ（ファイルは空の `{}` として生成されることがあるが、DB への保存処理とは無関係）。
- `Bot.start(with_adapter=False)` で内蔵の OAuth アダプターを無効化して起動する。

### トークン形式の変換

TwitchIO 内部、TokenManager（DB 保存形式）、`self.tokens` の形式はそれぞれ異なる。変換は以下のメソッドが担う。

| メソッド | 変換方向 | 呼び出し元 |
|---|---|---|
| `TokenManager.converted_load_tokens()` | DB 形式 → `self.tokens` 形式 (`{bot_id: {"token": ..., "refresh": ...}}`) | `Bot.load_tokens` |
| `TokenManager.converted_save_tokens()` | `self.tokens` 形式 → DB 形式 | `Bot.event_token_refreshed` |

> **注意**: `converted_save_tokens()` には `converted_load_tokens()` の戻り値をそのまま渡してはならない。`event_token_refreshed` 内で `ValidationPayload` から `expires_in`・`scopes` 等を補完してから渡すこと。

---

## 10. エラーハンドリング方針

| 状況 | 例外 | 対応 |
|---|---|---|
| 環境変数未設定 | `RuntimeError` | 即座に中断・ユーザーへ通知 |
| ユーザーが見つからない | `RuntimeError` | 中断・ユーザー名や権限を確認 |
| ポート競合 / サーバー起動失敗 | `OSError` | 手入力フォールバックへ移行 |
| タイムアウト（60 秒） | `TimeoutError` | 手入力フォールバックへ移行 |
| ユーザーが認可を拒否 | `RuntimeError` | 中断・再実行を促す |
| トークン交換失敗 | `RuntimeError` | 中断・クレデンシャルを確認 |
| Bot ID 不一致 | `RuntimeError` | 中断・Bot アカウントで再ログインを促す |
| キャッシュトークン検証失敗 | ログ warning + リフレッシュ試行 | リフレッシュ成功時は自動復旧、失敗時は再認証（例外は伝播しない） |
| リフレッシュ失敗 | ログ warning + 再認証 | 自動復旧（例外は伝播しない） |

---

## 11. よくある問題とトラブルシューティング

### 11.1 「Bot ID 不一致」エラー
**症状**: `RuntimeError: Authorization error: expected bot account '...' but the authorised account has ID '...'`

**原因**: ブラウザの Twitch ログイン済みセッションが Owner アカウントになっている。

**解決策**:
1. ブラウザで Twitch からログアウトする（またはシークレットウィンドウを使う）。
2. `setup_tokens.exe` または `python setup_tokens.py` を再実行し、Bot アカウントでログインする。

### 11.2 トークンが期限切れでも再認証が求められる
**症状**: 起動時にブラウザが開いて再認証が要求される。

**原因**:
- `refresh_token` が DB に存在しない（古いバージョンで取得したトークン）。
- `refresh_token` 自体も無効化された（60 日以上未使用、または Twitch アプリ設定変更）。
- `tokens.db` が削除されているか空。

**解決策**:
1. 通常は自動リフレッシュが機能するため、`refresh_token` が有効であれば再認証不要。
2. リフレッシュが連続して失敗する場合は `tokens.db` を削除して `setup_tokens.py` を再実行する。
3. Bot アカウントでログインする。

### 11.3 起動のたびにブラウザが開く（Owner アカウントで誤認証した場合）
**症状**: 起動するたびにブラウザが開き、毎回 Bot アカウントでログインし直す必要がある。

**原因**: DB に Owner アカウントのトークンが保存されている（`bot_id` と不一致）。

**解決策**:
1. `tokens.db` を削除して `setup_tokens.py` を再実行する。
2. Bot アカウントでログインする。

### 11.4 ローカルサーバー起動失敗（ポート 80 が使用中）
**症状**: ログに `Local server callback unavailable (OSError)` と表示された後、手入力プロンプトが表示される。

**原因**: ポート 80 を他プロセスが使用中。

**解決策**:
- `REDIRECT_URI` を未使用ポートに変更する（例 `http://localhost:4343/oauth/callback`）。
- Twitch Developer Console の Redirect URL も同じ値に更新する。

### 11.5 実行中にトークンが失効しチャットが止まる
**症状**: しばらく動作した後に送受信が停止する。

**原因**: TwitchIO のリフレッシュに失敗し `event_token_refreshed` が呼ばれなかった、または DB への保存に失敗した。

**確認方法**:
- `debug.log` で `event_token_refreshed` が呼ばれているか確認する。
- `event_token_refreshed` 内で `bot_id` 一致チェックが通り `converted_save_tokens` が呼ばれているかを確認する。

---

## 12. テスト観点（最小セット）

- 環境変数未設定時に `TokenManager.__init__` が `RuntimeError` を送出すること。
- `TokenManager.load_tokens` が DB 未生成時に空 dict を返すこと。
- `save_tokens` → `load_tokens` でデータが正しくラウンドトリップすること。
- `start_authorization_flow`:
  - キャッシュトークンが Bot ID と一致する場合は OAuth フローを実行しないこと。
  - キャッシュトークンが Bot ID と不一致の場合はキャッシュを破棄して再認証すること（リフレッシュは試みない）。
  - キャッシュトークン検証が失敗した場合は `_refresh_access_token` でリフレッシュを試みること（例外は伝播しないこと）。
  - リフレッシュ成功 + Bot ID 一致の場合はトークンを保存して OAuth フローを実行しないこと。
  - リフレッシュ失敗または Bot ID 不一致の場合は再認証すること。
  - 新規取得トークンが Bot ID と不一致の場合は `RuntimeError` を送出すること。
  - 完了後に `TokenManager.user_access_token` / `refresh_token` / `last_validated` がセットされること（戻り値なし）。
- `_refresh_access_token`:
  - 正常レスポンスに `access_token` が含まれる場合は `obtained_at` を付加して返すこと。
  - `access_token` がない場合は `RuntimeError` を送出すること。
- `TokenManager.converted_load_tokens`:
  - `load_tokens()` の戻り値を `{bot_id: {"user_id": ..., "token": ..., "refresh": ...}}` 形式に変換して返すこと。
  - キーが欠落している場合は空 dict を返すこと（例外を伝播しない）。
- `TokenManager.converted_save_tokens`:
  - `{bot_id: {"token": ..., "refresh": ..., "expires_in": ..., "scopes": ...}}` 形式を DB 形式に変換して保存すること。
  - `bot_id` が tokens に含まれない場合は warning をログに出力してスキップすること。
- `Bot.load_tokens`:
  - `TokenManager.converted_load_tokens()` からトークンを読み込み `add_token()` を呼ぶこと。
  - トークンが見つからない場合は `RuntimeError` を送出すること。
  - `bot_id` 不一致の場合は `RuntimeError` を送出すること。
- `Bot.event_token_refreshed`:
  - `validation_payload.user_id == bot_id` の場合のみ `converted_save_tokens` を呼んで DB を更新すること。
  - owner トークンで DB が上書きされないこと。

---

## 13. 実装変更時のチェックリスト

- [ ] `REDIRECT_URI` を変更した場合は Twitch Developer Console も更新する。
- [ ] `ACCESS_SCOPES` を変更した場合は既存 `tokens.db` を削除して再認証する。
- [ ] `TokenStorage` のスキーマを変更した場合は既存 DB との互換性を確認する。
- [ ] `start_authorization_flow` のシグネチャを変更した場合は `twitchbot.py` と `setup_tokens.py` の両方を更新する。
- [ ] `Bot.add_token` に変更を加える場合は owner/bot 両方のトークンリフレッシュシナリオでテストする。
- [ ] キャッシュ検証ロジックを変更した場合は「誤認証トークンの自動破棄」が機能することを確認する。
- [ ] `_refresh_access_token` を変更した場合は、リフレッシュ後の `bot_id` 一致確認を省略しないこと。
- [ ] トークン検証・リフレッシュ失敗時に例外が `start_authorization_flow` 外へ伝播しないことを確認する。

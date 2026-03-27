---
name: twitch-auth-flow
description: Twitch OAuth2 認証フローの全体設計、TokenManager/TokenStorage の責務、キャッシュ検証、トークンリフレッシュ、トラブルシューティングの実装指針
keywords: [twitch, oauth2, token, auth, token_manager, token_storage, refresh, bot, setup_tokens, authorization_code_flow]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は、Twitch 認証（OAuth2 Authorization Code Flow）の全体設計と、各ステージの実装詳細を定義します。
`setup_tokens.py` によるトークン取得から、`Bot` 起動後のトークンリフレッシュまでをカバーします。

---

## 1. 概要

Twitchbot は **Bot ユーザー専用の OAuth2 トークン** でチャットおよびイベント購読を行います。
トークン管理は以下の 3 層に分かれています。

| 層 | クラス | ファイル | 責務 |
|---|---|---|---|
| 永続化 | `TokenStorage` | `core/token_storage.py` | SQLite3 によるトークンの読み書き・削除 |
| フロー制御 | `TokenManager` | `core/token_manager.py` | OAuth フロー実行・トークン検証・キャッシュ確認 |
| Bot 統合 | `Bot.add_token` | `core/bot.py` | TwitchIO へのトークン登録・DB 更新 |

---

## 2. 関連ファイルと役割

### 2.1 `setup_tokens.py`
- **用途**: 初回セットアップまたはトークンリセット時にユーザーが手動実行するコンソールスクリプト。
- ログファイルは作成しない。すべての出力を stdout/stderr へ送る。
- 成功時に `tokens.db` へトークンを保存して終了する。

### 2.2 `core/token_manager.py`
- `TokenManager`: OAuth Authorization Code Flow の実行、キャッシュ確認、Bot ID 検証を担う。
- `TwitchBotToken`: Bot 起動に必要なすべての認証情報を保持する frozen dataclass。
- `UserIDs`: owner_id と bot_id を保持する frozen dataclass。
- モジュール定数 `REDIRECT_URI` / `ACCESS_SCOPES` は認証フローに使う定数。

### 2.3 `core/token_storage.py`
- `TokenStorage`: SQLite3 context manager。`with` ブロック内で接続を開き、抜けると自動クローズ。
- テーブル: `tokens (key TEXT PRIMARY KEY, access_token, refresh_token, expires_in, obtained_at, scope, token_type)`
- デフォルトキー `"twitch_bot"` で読み書きする。

### 2.4 `core/bot.py` (`Bot.add_token`)
- TwitchIO が内部でトークンリフレッシュを行った後に呼ばれる。
- `validation_payload.user_id == self.bot_id` の場合のみ DB を更新する（owner トークンで上書きしない）。
- `self.tokens.get(self.bot_id)` から最新のトークンを取得して保存する。

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
          └─ TwitchBotToken を返す

[Bot 起動中] Bot.start() → event_ready
    └─ _subscribe_to_chat_events
          └─ Bot.add_token (access_token, refresh_token)
                └─ super().add_token (TwitchIO 内部登録)

[実行中] TwitchIO 自動リフレッシュ
    └─ event_token_refreshed
          └─ Bot.add_token (新トークン)
                └─ Bot ID 一致時のみ DB 更新
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
          └─ Bot.add_token(payload.token, payload.refresh_token)
                └─ super().add_token() → ValidateTokenPayload
                      └─ validation_payload.user_id == bot_id? → DB 更新
```

- TwitchIO はトークンの有効期限切れを検知すると自動でリフレッシュし `event_token_refreshed` を発火する。
- `add_token` はその更新を DB に永続化する責務を持つ。
- **owner_id と bot_id の両方のトークンが TwitchIO 内部で管理されるため**、`user_id` の照合なしに全トークンを DB 保存すると bot トークンが owner トークンで上書きされる。必ず `bot_id` 一致確認を行うこと。

---

## 9. `TwitchBotToken` の受け渡し

```python
# twitchbot.py / setup_tokens.py
token_data = await token_manager.start_authorization_flow(owner_name, bot_name)

# Bot コンストラクタ
bot = Bot(config=config, token_data=token_data, token_manager=token_manager)
```

- `TwitchBotToken` は frozen dataclass。Bot 起動時の初期値として使用し、以降のリフレッシュは TwitchIO が管理する。
- `Bot` は `token_data` と `token_manager` の両方を受け取る（`token_data` は起動時の初期値、`token_manager` はリフレッシュ後の DB 更新に使用）。

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
- `bot.add_token` で `bot_id` 一致チェックが通っているかを確認する。

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
- `_refresh_access_token`:
  - 正常レスポンスに `access_token` が含まれる場合は `obtained_at` を付加して返すこと。
  - `access_token` がない場合は `RuntimeError` を送出すること。
- `Bot.add_token`:
  - `validation_payload.user_id == bot_id` の場合のみ DB を更新すること。
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

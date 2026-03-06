name: google-cloud-api-auth
description: Google Cloud API 利用時の認証方式、初期化、検証、運用ガイドを定義するスキル
keywords: google cloud, auth, authentication, adc, service account, api key, credentials

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。
関連する例外処理は [.github/skills/google-cloud-api-exception/SKILL.md](../google-cloud-api-exception/SKILL.md) を参照してください。

この文書は、Google Cloud API を利用する機能に認証を実装する際の共通方針を定義します。
例外処理と認証を分離し、認証の責務に集中できるようにします。

## 0. 方針変更（重要）
- `GOOGLE_CLOUD_API_OAUTH` は常に API キー文字列として扱う。
- `GOOGLE_CLOUD_API_OAUTH` を Service Account JSON path として解釈しない。
- Service Account のみ対応している API では、`GOOGLE_APPLICATION_CREDENTIALS` 未設定時に
  `GOOGLE_CLOUD_API_OAUTH` へフォールバックしない。
- Google Cloud 側の移行方針に合わせ、`GOOGLE_CLOUD_API_OAUTH` は将来バージョンで廃止予定とする。

## 1. 認証設計の原則
1. 認証方式は API ごとの要件に合わせて選ぶ（API key / Service Account / ADC）。
2. 本番運用では Service Account か ADC を優先し、API key は必要最小限にする。
3. 秘密情報は環境変数で受け取り、ログへ出力しない。
4. 認証失敗は初期化段階で検出し、利用時に曖昧な失敗を持ち込まない。
5. 例外分類とリトライ戦略は例外スキルへ委譲する。
6. Service Account 専用 API では API キーへ自動フォールバックしない。

## 2. 認証方式の選択指針
### 2.1 API key
- 向いているケース:
  - API key 認証が公式にサポートされる API。
  - サーバー間通信で、キーの管理範囲が限定できる場合。
- 注意点:
  - 権限が広くなりやすい。
  - ローテーションと流出対策が必須。
  - URL 付与型ではログ漏えいリスクが高い。

### 2.2 Service Account JSON
- 向いているケース:
  - サーバーサイド処理。
  - IAM で最小権限を厳密に管理したい場合。
- 注意点:
  - 鍵ファイルの保管・配布が運用負荷になる。
  - パス不備・JSON 破損・権限不足を初期化時に明示する。

### 2.3 ADC (Application Default Credentials)
- 向いているケース:
  - GCP 実行環境（Cloud Run, GCE, GKE など）。
  - ローカル開発と本番で資格情報供給方法を分けたい場合。
- 注意点:
  - 実行環境依存が強い。
  - ローカルでは `gcloud auth application-default login` 等の準備が必要。

## 3. 環境変数の標準ルール
- 認証情報は次の順序で解決する。
  1. `GOOGLE_APPLICATION_CREDENTIALS`（Service Account JSON）
  2. ADC（API/client が対応している場合）
  3. `GOOGLE_CLOUD_API_OAUTH`（API key が正式サポートされる API のみ）

- `GOOGLE_CLOUD_API_OAUTH` の値は常に API キー文字列として扱う。
- `GOOGLE_CLOUD_API_OAUTH` は Service Account の代替として使わない。
- Service Account 専用 API の認証解決ルール。
  - `GOOGLE_APPLICATION_CREDENTIALS` または ADC が利用可能なら採用する。
  - どちらも利用不可なら初期化失敗にする。
  - `GOOGLE_CLOUD_API_OAUTH` が設定されていても無視する。

- 認証方式は `metadata` や初期化ログで識別可能にする。
  - 例: `auth_source=GOOGLE_APPLICATION_CREDENTIALS`

## 4. 初期化時チェック項目
1. 認証入力の存在確認（env var が空でないこと）。
2. ファイル型認証の妥当性確認（存在、読取可、JSON 形式）。
3. 必須フィールド確認（例: `project_id`）。
4. 最小 API 呼び出しによる接続確認（例: list/get 系）。
5. 失敗時は利用不可状態へ遷移し、原因を warning/error に記録する。

## 5. 実装テンプレート（同期初期化）
```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def resolve_google_auth_source() -> tuple[str, str | None]:
    """Resolve auth source and value.

    Returns:
        tuple[str, str | None]: (auth_source, auth_value)
        auth_source values: "service_account", "api_key", "adc", "none"
    """
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    api_key_value = os.getenv("GOOGLE_CLOUD_API_OAUTH", "").strip()

    if credentials_path:
        return "service_account", credentials_path

    # Use ADC if available in runtime environment.
    # (Actual ADC availability check depends on the client library.)
    # This template returns "adc" when explicit service account is not set.
    if os.getenv("GOOGLE_USE_ADC", "1") == "1":
      return "adc", None

    if api_key_value:
      return "api_key", api_key_value

    return "none", None


def validate_service_account_file(path_value: str) -> dict[str, Any]:
    path_obj = Path(path_value)
    if not path_obj.is_file():
        msg = f"Credential file not found: {path_value}"
        raise RuntimeError(msg)

    try:
        raw = path_obj.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as err:
        msg = f"Invalid credential file: {path_value}"
        raise RuntimeError(msg) from err

    if not isinstance(data, dict) or not str(data.get("project_id", "")).strip():
        msg = "Credential JSON does not contain project_id"
        raise RuntimeError(msg)

    return data
```

## 6. ログとエラーメッセージ方針
- 認証失敗ログには次を含める。
  - `auth_source`
  - 失敗種別（file missing, invalid json, permission denied など）
  - 影響範囲（engine unavailable / fallback したか）
- 含めない情報:
  - API key 本文
  - トークン
  - 秘密鍵

## 7. 例外ハンドリング連携
- 認証で発生する代表的失敗:
  - `Unauthenticated`
  - `PermissionDenied`
  - `Unauthorized`
- これらはリトライでは回復しないことが多いため、原則として初期化失敗扱いにする。
- API 呼び出し時のリトライ可否は例外スキルに従い、認証スキル側では分類ルールのみ定義する。

### 7.1 Service Account 専用 API の扱い
- `GOOGLE_APPLICATION_CREDENTIALS` も ADC も使えない場合は初期化失敗にする。
- `GOOGLE_CLOUD_API_OAUTH` へのフォールバックを行わない。

## 8. テスト観点（最小セット）
1. `GOOGLE_APPLICATION_CREDENTIALS` が有効ファイルの場合に初期化成功する。
2. 認証ファイルが存在しない場合に明示的な失敗になる。
3. JSON 破損時に失敗理由が識別できる。
4. API key 経路が必要 API のみで有効化される。
5. 認証エラー時に機密情報がログへ出ない。

## 9. 運用チェックリスト
- IAM は最小権限になっている。
- 鍵ローテーション手順が定義されている。
- 開発環境と本番環境で認証供給方法が明確。
- 認証失敗時の復旧手順（どの env を確認するか）が文書化されている。

## 10. このスキルを更新すべきタイミング
- 新しい Google Cloud API を追加したとき。
- 認証方式（API key / Service Account / ADC）の優先順位を変更したとき。
- 既存環境変数の互換ルールを変更したとき。
- セキュリティ要件（鍵管理、監査ログ方針）が変更されたとき。

## 11. 廃止予定（Deprecation）
- `GOOGLE_CLOUD_API_OAUTH` は将来バージョンで廃止予定。
- 新規実装は Service Account または ADC を前提に設計する。
- 既存機能で API キー運用が残る場合は、移行計画（期限、影響範囲、代替手段）を明記する。

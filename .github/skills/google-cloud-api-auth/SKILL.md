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
- `GOOGLE_CLOUD_API_OAUTH` はこのプロジェクトで互換運用する既存環境変数とする。
  Google Cloud 全体の非推奨化とは扱わない。
- ADC 対応 API では、`google.auth.default()` を使用して資格情報の検索をクライアントライブラリへ委ねる。

## 1. 認証設計の原則
1. 認証方式は API ごとの要件に合わせて選ぶ（API key / Service Account / ADC）。
2. 本番運用では、アタッチされた Service Account を含む ADC を優先する。
   Service Account key は、より安全な方法が利用できない場合の例外とする。
   API key は公式にサポートされる API に限り必要最小限で使用する。
3. 秘密情報は環境変数で受け取り、ログへ出力しない。
4. 認証失敗は初期化段階で検出し、利用時に曖昧な失敗を持ち込まない。
5. 例外分類とリトライ戦略は例外スキルへ委譲する。
6. Service Account 専用 API では API キーへ自動フォールバックしない。
7. ローカル開発では、可能な限りユーザー資格情報または Service Account impersonation を使用し、
   Service Account key の作成を避ける。

## 2. 認証方式の選択指針
### 2.1 API key
- 向いているケース:
  - API key 認証が公式にサポートされる API。
  - サーバー間通信で、キーの管理範囲が限定できる場合。
- 注意点:
  - 権限が広くなりやすい。
  - ローテーションと流出対策が必須。
  - URL 付与型ではログ漏えいリスクが高い。

### 2.2 Service Account
- 向いているケース:
  - サーバーサイド処理。
  - IAM で最小権限を厳密に管理したい場合。
- 注意点:
  - GCP 実行環境では、最も安全で運用しやすい方法はアタッチされた Service Account を使用する ADC である。
  - ローカル開発では、ユーザー資格情報または Service Account impersonation を優先する。
  - Service Account key は管理・配布・ローテーション・流出対策が必要な例外的な方法である。
  - key、Workload Identity Federation、Workforce Identity Federation などの資格情報ファイルを
    `GOOGLE_APPLICATION_CREDENTIALS` で指定できる。

### 2.3 ADC (Application Default Credentials)
- 向いているケース:
  - GCP 実行環境（Cloud Run, GCE, GKE など）。
  - ローカル開発と本番で資格情報供給方法を分けたい場合。
- 注意点:
  - 実行環境依存が強い。
  - ローカルでは `gcloud auth application-default login` 等の準備が必要。
  - ADC は次の順序で資格情報を検索する。
    1. `GOOGLE_APPLICATION_CREDENTIALS` が示す資格情報ファイル。
    2. ローカル ADC ファイル（`gcloud auth application-default login` で作成）。
    3. メタデータサーバーのアタッチされた Service Account。
  - 上記の検索順序は実装上の優先順位であり、各環境で推奨される資格情報の種類とは別である。

## 3. 環境変数の標準ルール
- ADC 対応 API の認証情報は、`google.auth.default()` または各クライアントライブラリの ADC 機能で解決する。
  カスタム環境変数で ADC を有効化する独自フラグを設けない。
- `GOOGLE_APPLICATION_CREDENTIALS` が設定された場合、ADC はその値を指す資格情報ファイルとして解決する。
  そのファイルは Service Account key とは限らず、Workload Identity Federation、
  Workforce Identity Federation などにも対応する。
- ADC 対応 API の資格情報の検索順序は、ADC の規定に従う。
  1. `GOOGLE_APPLICATION_CREDENTIALS`
  2. ローカル ADC ファイル
  3. メタデータサーバーのアタッチされた Service Account
- ADC 対応 API で API key を併用する場合も、API ごとの公式サポートと認証要件に従う。
  認証方式の自動切り替えは仕様化しない。
- API key 専用または API key を明示的にサポートする経路では、
  `GOOGLE_CLOUD_API_OAUTH` のみを API key として使用する。

- `GOOGLE_CLOUD_API_OAUTH` の値は常に API キー文字列として扱う。
- `GOOGLE_CLOUD_API_OAUTH` は Service Account の代替として使わない。
- Service Account 専用 API の認証解決ルール。
  - `google.auth.default()` で ADC が利用可能なら採用する。
  - ADC が利用不可なら初期化失敗にする。
  - `GOOGLE_CLOUD_API_OAUTH` が設定されていても無視する。

- 認証方式は `metadata` や初期化ログで識別可能にする。
  - 例: `auth_source=GOOGLE_APPLICATION_CREDENTIALS`

## 4. 初期化時チェック項目
1. 認証入力の存在確認（env var が空でないこと）。
2. ADC 対応 API では `google.auth.default()` に資格情報解決を委ね、例外を初期化時に処理する。
3. ファイル型認証を直接検証する場合は、ファイルの存在、読取可、JSON 形式、
   または資格情報種別ごとの必須フィールドを確認する。
   `project_id` を全資格情報で共通に必須としない。
4. 最小 API 呼び出しによる接続確認（例: list/get 系）。
5. 失敗時は利用不可状態へ遷移し、原因を warning/error に記録する。

## 5. 実装テンプレート（同期初期化）
```python
import json
import os
from pathlib import Path

import google.auth
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError


def resolve_adc() -> tuple[Credentials, str | None, str]:
    """Resolve ADC and return credentials, project ID, and source label."""
    try:
        credentials, project_id = google.auth.default()
    except DefaultCredentialsError as err:
        raise RuntimeError("ADC credentials are unavailable") from err

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    source = "GOOGLE_APPLICATION_CREDENTIALS" if credentials_path else "ADC"
    return credentials, project_id, source


def resolve_api_key() -> str:
    """Resolve an API key for an API that officially supports API-key auth."""
    api_key = os.getenv("GOOGLE_CLOUD_API_OAUTH", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_CLOUD_API_OAUTH is not set")
    return api_key


def validate_external_credential_config(path_value: str) -> dict[str, object]:
    """Validate a JSON credential configuration before passing it to ADC."""
    path_obj = Path(path_value)
    if not path_obj.is_file():
        raise RuntimeError("Credential file not found")

    try:
        raw = path_obj.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as err:
        raise RuntimeError("Invalid credential file") from err

    if not isinstance(data, dict):
        raise RuntimeError("Credential JSON must contain an object")
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
1. `GOOGLE_APPLICATION_CREDENTIALS` が有効な資格情報ファイルの場合に ADC 初期化が成功する。
2. ADC 対応 API がローカル ADC またはメタデータサーバーの資格情報を解決できる。
3. ADC 対応 API が資格情報不足の場合に明示的な初期化失敗になる。
4. 認証ファイルが存在しない場合に明示的な失敗になる。
5. JSON 破損時に失敗理由が識別できる。
6. API key 経路が公式にサポートされる API のみで有効化される。
7. Service Account 専用 API が API key にフォールバックしない。
8. 認証エラー時に機密情報がログへ出ない。

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
- Google Cloud API が ADC または IAM ベースの認証を公式に推奨する場合、
  新規実装は ADC または安全な Service Account 運用を優先する。
- API key は、その API が公式に API key 認証をサポートし、制限・ローテーション・運用要件を満たせる場合のみ使用する。
- `GOOGLE_CLOUD_API_OAUTH` は、このプロジェクトの既存互換環境変数である。
  将来的に廃止する場合は、廃止予定の根拠、移行先、期限、影響範囲を別途決定してこの SKILL に記録する。

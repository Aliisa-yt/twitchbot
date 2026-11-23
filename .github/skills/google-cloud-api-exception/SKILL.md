---
name: google-cloud-api-exception
description: Google Cloud APIを使用している際に発生する例外を処理するスキル
keywords: [google cloud, api, exception, error handling, retry]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は、Google Cloud Translation / Speech-to-Text (STT) API のエラーをアプリ内のドメイン例外へ変換し、上位処理へ伝える方針を定めます。Google API Core の例外クラスは HTTP / gRPC status と対応する場合がありますが、クラス名だけでアプリ内の扱いや再試行可否を一律に決めてはいけません。API ごとの仕様、構造化された error detail、SDK 内部再試行、アプリの処理フローを合わせて判断してください。

## 1. 基本方針

1. API 固有の status と error detail に基づいて分類する。
2. 作成・更新など副作用を持つ API は、再実行時の冪等性を確認する。
3. アプリ側で同じ STT セグメントを自動再送しない。
4. リクエスト本文、翻訳対象文、音声、資格情報、トークンをログへ出さず、原因調査に必要な最小情報を記録する。
5. 共通 API エラー分類と Translation / STT のドメイン例外変換を分離する。共通分類だけでエンジンの可用性やアプリ側の再送を決めない。

## 2. Google API Core 例外の見方

以下は初期判断の手掛かりです。一覧だけで最終的なドメイン分類や再試行動作を決めるものではありません。

### 恒久的な失敗になりやすい status

- `InvalidArgument`
- `FailedPrecondition`
- `OutOfRange`
- `PermissionDenied`
- `Unauthenticated`
- `Unimplemented`
- `NotFound`（存在しないことが正常な処理か、API / 操作ごとに判断）
- `AlreadyExists`（既存リソースの状態が要求と一致すると確認できる場合に限り、作成成功相当として扱える）

### 一時的な障害の可能性がある status

- `TooManyRequests`（HTTP 429）
- `ResourceExhausted`（gRPC）。一時的なレート制限か、待機しても解消しないクォータ超過かを error detail で判断する。
- `ServiceUnavailable`（HTTP 503 / gRPC `UNAVAILABLE`）
- `InternalServerError`（HTTP 500 / gRPC `INTERNAL`）
- `DeadlineExceeded`
- `Aborted`
- `Unknown`（API の詳細から一時障害と判断できる場合に限る）

HTTP / gRPC の status は SDK の例外クラスへ写像される場合があります。`ResourceExhausted` は `TooManyRequests` の派生型でもあるため、クラス名や `except` の順序だけに頼らず、transport、status、構造化された error detail を確認してください。瞬間的な過負荷と日次クォータ到達は同じ扱いにしません。API が `Retry-After` を返す場合は、その値を尊重します。

### 個別に注意する例外

- `RetryError`: API Core の再試行が尽きた状態です。`.cause` が最終原因です。API Core では `GoogleAPIError` の派生であり、`GoogleAPICallError` の派生ではないため、個別に扱って原因を記録します。
- `GoogleAPICallError`: API 呼び出しエラーの基底例外です。未分類の例外を一律に再試行する根拠にはせず、status と API 固有の詳細を確認します。
- `Cancelled`: アプリ終了・ユーザー操作など、キャンセル元と操作の意味に応じて扱います。

## 3. 共通分類とドメイン例外

共通分類は API status / detail を正規化するための中間情報です。Translation / STT のドメイン例外へ変換した後、上位層がドメイン契約に従って処理します。`transient` や「再試行可能」という分類は、同じ要求をアプリ側で直ちに再送する指示ではありません。

### Translation のドメイン例外

```text
TranslateExceptionError
├── TranslateNonRetriableError
│   ├── TranslationQuotaExceededError
│   └── NotSupportedLanguagesError
└── TranslateRetriableError
    └── TranslationRateLimitError
```

- `TranslateNonRetriableError`: 恒久的な失敗。該当エンジンを利用不可として、以降そのエンジンへリクエストしません。
- `TranslateRetriableError`: 一時的な障害の可能性がある分類です。同一要求を即時再送せず、エンジンを利用可能なままにして次の独立したリクエストを許可します。
- `TranslateExceptionError`: 未分類またはその他の翻訳エラーです。恒久 / 一時の分類やエンジン可用性を暗黙に決めず、上位側の扱いを別途定義します。
- `NotSupportedLanguagesError`: 未対応言語が確定したときに使用し、利用者へ明示します。

### STT のドメイン例外

```text
STTExceptionError
├── STTNonRetriableError
│   └── STTQuotaExceededError
└── STTRetriableError
    └── STTRateLimitError
```

- `STTNonRetriableError`: 恒久的な失敗。該当エンジンを利用不可として、以降そのエンジンへリクエストしません。
- `STTRetriableError`: 一時的な障害の可能性がある分類です。同一セグメントは自動再送せず、エンジンを利用可能なままにして次の独立したリクエストを許可します。
- `STTExceptionError`: 未分類またはその他の STT エラーです。エラーを握りつぶしたり、根拠なく恒久 / 一時に分類したりしません。
- `STTNotAvailableError`: 初期化・利用可能状態を表す既存エラーです。API の一時障害を表す `STTRetriableError` とは区別します。

`STTQuotaExceededError` は恒久的なクォータ超過として扱います。`NotSupportedLanguagesError` は Translation の分類です。STT は未対応言語を判定できる API 詳細が確認できない限り、同名の分類を導入しません。

## 4. API status / detail の分類方法

例外を受け取ったら、次の順で API エラー情報を確認し、共通分類を経てドメイン例外へ変換します。

1. `RetryError` は通常の `GoogleAPICallError` と分けて扱い、`.cause` の型・status・API detail を確認する。
2. transport と API 仕様から HTTP status / gRPC status、および構造化された error detail / reason を取得する。
3. API が定義する reason を優先して、レート制限、クォータ超過、不正リクエスト、認証・権限、一時障害などへ分類する。
4. status は分かるが詳細が不足する場合は、下記の標準的な初期分類を適用する。response body の解析自体に失敗した場合や status も不明な場合は、基底ドメイン例外として上位へ返す。
5. Translation / STT ごとの契約に従ってドメイン例外へ変換する。変換後も原因例外を chain して保持する。

共通分類情報を持つ場合は、たとえば次のような `APIErrorType` と `APIErrorInfo` を用意できます。実際の status / detail の取得方法は API と transport ごとに異なるため、共通クラス内で固定の属性や文章形式を仮定しないでください。

```python
from dataclasses import dataclass
from enum import Enum, auto


class APIErrorType(Enum):
    RATE_LIMIT = auto()
    DAILY_QUOTA = auto()
    QUOTA_UNKNOWN = auto()
    INVALID_REQUEST = auto()
    AUTHENTICATION = auto()
    PERMISSION_DENIED = auto()
    SERVICE_UNAVAILABLE = auto()
    TIMEOUT = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class APIErrorInfo:
    error_type: APIErrorType
    http_status: int | None
    grpc_status: str | None
    reason: str | None
    transient: bool
```

`transient` は次の独立した要求を受け付けられる一時障害かを表す情報であり、自動再試行の指示ではありません。ログに出すためだけの生の例外メッセージや request body はこの情報へ含めず、原因例外自体は例外 chain で保持します。

### status / detail ごとの初期分類

| API status / detail | 共通分類 | ドメイン側の扱い |
|---|---|---|
| HTTP 429 / `TooManyRequests` | `RATE_LIMIT` | `*RateLimitError` / `*RetriableError`。次の独立要求を許可し、取得可能な `Retry-After` を cooldown に反映 |
| `ResourceExhausted` と一時的レート制限を示す detail | `RATE_LIMIT` | `*RateLimitError` / `*RetriableError` |
| `ResourceExhausted` と確定可能なクォータ超過 detail | `DAILY_QUOTA` または API 固有の quota 分類 | `*QuotaExceededError` / `*NonRetriableError` |
| `ResourceExhausted` だが detail から原因を特定できない | `QUOTA_UNKNOWN` | 保守的に `*NonRetriableError`。日次超過と断定せず、短い rate-limit cooldown で解消したものとも扱わない |
| HTTP 4xx（429 を除く） | API 仕様に従う。該当仕様がなければ恒久的エラー | `*NonRetriableError`。解析不能または Translation の未対応言語を確定できない場合は基底例外 |
| HTTP 5xx、`ServiceUnavailable`、`InternalServerError` | `SERVICE_UNAVAILABLE` など一時障害 | `*RetriableError`。エンジンを利用可能なままにし、同一要求は即時再送しない |
| `DeadlineExceeded` | `TIMEOUT` | API の意味と操作の冪等性に従い一時障害として扱う。副作用のある操作は結果不明の可能性も考慮 |
| `BadRequest` | `INVALID_REQUEST` 等 | Translation は次項に従って未対応言語かを別途判定 |
| HTTP 401 / 403 | `AUTHENTICATION` / `PERMISSION_DENIED`。明示的な quota reason があれば quota 分類 | API 固有仕様に従い恒久エラーとして扱う |
| status / detail を特定できない | `UNKNOWN` | `TranslateExceptionError` / `STTExceptionError`。恒久 / 一時や可用性を推測しない |

HTTP / gRPC の表現は SDK により同じ例外クラスへ写像される場合があります。特に `ResourceExhausted` と `TooManyRequests` を分ける際は transport と status を確認してください。API 仕様により上の初期分類と異なる根拠が得られた場合は、その根拠を優先します。

### Translation `BadRequest` と未対応言語

- `BadRequest` の status だけで `NotSupportedLanguagesError` に変換しません。API の構造化 detail から未対応言語が確定した場合に限り、その例外を使用します。
- 未対応言語か判断できない場合は `TranslateExceptionError` とし、誤った利用者向けメッセージを返しません。
- detail が別の恒久的失敗を示す場合は `TranslateNonRetriableError` として分類できます。

### STT REST response body

- response body の解析に失敗した場合は、API 仕様変更または実装不整合の可能性があるエラーとして記録し、`STTExceptionError` で上位へ返します。
- HTTP error body を解析できる場合は Google API の status / error detail を使って上記の分類を適用します。本文全体をログに出力しません。

## 5. STT の処理フロー

STT は配信時のリアルタイム処理です。同一音声セグメントの処理待ちが後続セグメントを詰まらせないよう、`STTProcessor` は `transcribe()` を 1 セグメントにつき 1 回だけ呼び、アプリ側で同一セグメントを自動再試行しません。

- 失敗した要求は `STTNonRetriableError`、`STTRetriableError` または未分類の `STTExceptionError` として速やかに上位へ返し、そのセグメントの処理を終了します。
- プロセッサは失敗したセグメントを再送せず、次のセグメント処理へ進みます。一時音声ファイルの cleanup は成功・失敗に関わらず行います。
- `STTRetriableError` は同一要求の再送を意味しません。エンジンを利用可能なままにし、次の独立した要求を受け付ける分類です。
- 失敗した音声を再送するかどうかはユーザーに委ねます。再認識が必要な場合は、ユーザーが発話をやり直します。

## 6. Translation の rate limit

- `TranslationRateLimitError` は `TransManager` の rate-limit 制御へ渡します。
- cooldown 中は翻訳要求を短絡して過負荷を回避します。上限到達と一時的なレート制限を区別し、クォータ超過を短い rate-limit cooldown だけで解消したものとして扱いません。
- API の `Retry-After` が取得できる場合は、次の独立した要求を許可するタイミングの制御に使います。
- `TranslateNonRetriableError` は該当エンジンを利用不可にし、`TranslateRetriableError` はエンジンを利用可能なままにします。複数エンジン間の fallback は TransManager の既存方針に従います。

## 7. SDK 内部再試行と timeout

- API / メソッドごとに SDK の retry policy、RPC timeout、再試行全体の時間上限を確認します。これらは別の設定です。
- SDK が内部再試行を行う場合、その回数と待機時間をアプリ側の試行回数と合算して把握します。同じ操作に無制限または意図しない多重再試行を設けません。
- STT のアプリ側セグメント再試行は行いません。SDK 内部再試行を許可するか、許可する場合の上限・timeout をどう設定するかは対象 API のリアルタイム要件と SDK 仕様に基づいて明示します。SDK 内部で必ず再試行されるとは仮定しません。
- `RetryError` を受けた場合は `.cause` を記録します。アプリ側で同じ要求を再送して回復させることを前提にしません。
- 作成・更新 API は、応答 timeout 後に処理がサーバー側で完了している可能性を考慮し、冪等性を確認せず再実行しません。

## 8. 実装・確認チェックリスト

例外処理を変更するときは、次を確認します。

- Google Cloud SDK / REST の例外を API status と error detail に基づいて分類し、適切な Translation / STT ドメイン例外へ変換する。
- Translation の `BadRequest` を一律未対応言語とせず、detail に基づいて判定する。
- `ResourceExhausted` と HTTP 429 / `Retry-After` を区別し、次の独立要求の cooldown / 可用性を分類どおりに扱う。
- `STTProcessor` に同一セグメントの retry loop を設けず、失敗後も次のキュー項目を処理し、一時音声ファイルを cleanup する。
- SDK 内部 retry / timeout の値が、API の仕様とリアルタイム要件に矛盾しないことを確認する。
- 未分類エラーを握りつぶさず、根拠のない恒久 / 一時分類や再試行を行わない。
- `RetriableError` を同一要求の即時再送と誤解せず、次の独立要求を許可する分類として扱う。

## 9. API ごとに確認する事項

汎用方針だけでは値や実装詳細を確定できないため、対象 API / メソッドの仕様を確認します。これらは `STTProcessor` に同一セグメント再試行を戻す理由にはなりません。

1. **API error detail の対応表:** Translation と STT の HTTP / gRPC response で、クォータ超過・一時的なレート制限・未対応言語を判別する具体的な reason / detail。
2. **SDK policy / timeout 値:** Speech の `recognize` と recognizer 管理 API ごとの SDK 既定値、およびリアルタイム要件を満たす明示値。
3. **`ExceptionError` の可用性:** detail が不足し恒久 / 一時を確定できない `TranslateExceptionError` / `STTExceptionError` を、該当エンジンの可用性へどう反映するか。
4. **操作固有の `NotFound` / `AlreadyExists` / `Cancelled`:** Speech recognizer の取得・作成・認識それぞれで、正常系、設定エラー、キャンセルのどれに該当するか。
5. **`Retry-After` の伝達:** 使用する SDK / REST transport から値を安全に取得できるか、次の独立リクエストをどの層で待機・抑制するか。
6. **Translation `BadRequest`:** API が返す具体的な詳細から未対応言語を確実に特定できる条件。

## 10. ログとプライバシー

- operation 名、必要最小限の resource 識別子、例外型、取得できた HTTP / gRPC status、API reason を記録する。
- `RetryError` は `.cause` を記録する。SDK / REST transport が取得可能な場合のみ attempt 数や待機情報を記録する。
- リクエスト本文、翻訳対象文、音声、資格情報、トークン、またはそれらを含む可能性のある生の例外メッセージや response body をログに出さない。
- 未分類の `GoogleAPICallError` を一律に再試行しない。原因の例外 chain は保持し、ログには許可された安全な項目だけを出す。

## 11. 共通分類器の参考設計

共通分類器を実装する場合は、API エラー情報の抽出と domain exception への変換を分離します。これは設計例であり、ここに示す型名は既存実装の必須名称ではありません。

次は処理の骨格を示す擬似コードです。status / detail の取得と `APIErrorInfo` の構築は対象 API・transport に合わせて実装します。

```text
class GoogleAPIErrorHandler:
    classify(exc, operation):
        status = cls.get_transport_status(exc)
        details = cls.get_structured_details(exc, operation=operation)
        return cls.classify_status_and_details(status, details)
```

- `get_transport_status` / `get_structured_details` は対象 API と transport の仕様に合わせて実装します。全 API に共通する `.errors`、`.details`、`.error_info` 属性があると仮定しません。
- まず構造化された reason / detail を確認します。例外メッセージの部分文字列検索は不安定なため、API が安定した形式を保証し、その対応表を検証できる場合に限り補助として使います。汎用的な単語一致だけで日次クォータとレート制限を断定しません。
- `ResourceExhausted` の原因が不明なら `QUOTA_UNKNOWN` とし、恒久的なクォータ超過と断定しません。ただし Translation / STT の運用契約では保守的に `*NonRetriableError` とし、短い cooldown で回復した扱いにしません。
- `HTTP 429` は `RATE_LIMIT` とします。`HTTP 403` は明示的な quota detail がなければ `PERMISSION_DENIED` とします。
- `BadRequest` の共通分類は不正リクエストまでです。Translation の未対応言語判定は Translation 固有の変換処理で行います。
- 分類結果の `transient` は一時障害の情報です。アプリ側の同一要求 retry や SDK の retry policy を有効化するフラグとして使いません。
- `APIErrorInfo` に request body、音声、認証情報、生の例外メッセージを格納・出力しません。原因例外は `raise ... from exc` などで保持し、必要な安全な属性だけを記録します。

### 分類例

| 発生したエラー | 共通分類 | `transient` |
|---|---|---|
| Translation: API detail が一時 rate limit を示す | `RATE_LIMIT` | True |
| Translation: API detail が日次 quota 超過を示す | `DAILY_QUOTA` | False |
| Speech: `RESOURCE_EXHAUSTED` だが quota の詳細不明 | `QUOTA_UNKNOWN` | False |
| HTTP 400 `BadRequest` | `INVALID_REQUEST` | False |
| HTTP 403 Permission Denied（quota detail なし） | `PERMISSION_DENIED` | False |
| HTTP 429 `TooManyRequests` | `RATE_LIMIT` | True |
| HTTP 503 `ServiceUnavailable` | `SERVICE_UNAVAILABLE` | True |
| `DeadlineExceeded` | `TIMEOUT` | True |

この表の `transient=True` は、同一要求を自動再送する意味ではありません。次の独立した要求に対してエンジンを利用可能なままにできるかを示す分類情報です。

## 12. 参考資料

- [google-api-core Exceptions](https://googleapis.dev/python/google-api-core/latest/exceptions.html)
- [Cloud Speech-to-Text エラーメッセージ](https://docs.cloud.google.com/speech-to-text/docs/v1/error-messages)
- [Cloud Translation クォータ](https://docs.cloud.google.com/translate/quotas)

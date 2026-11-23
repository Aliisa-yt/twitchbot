---
name: google-cloud-api-exception
description: Google Cloud APIを使用している際に発生する例外を処理するスキル
keywords: [google cloud, api, exception, error handling, retry]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は、Google Cloud API の例外をアプリ内のドメイン例外へ変換し、上位処理へ伝える方針を定めます。Google API Core の例外クラスは HTTP / gRPC status を表しますが、クラス名だけで再試行可否を一律に決めてはいけません。API ごとの仕様、エラー詳細、SDK の内部再試行、アプリの処理フローを合わせて判断してください。

## 1. 基本方針

1. API 固有の status と error detail に基づいて例外を分類する。
2. 作成・更新など副作用を持つ API は、再実行時の冪等性を確認する。
3. アプリ側で同じ STT セグメントを自動再送しない。
4. リクエスト本文、音声、資格情報、トークンをログへ出さず、原因調査に必要な最小情報を記録する。

## 2. Google API Core 例外の一般分類

以下は判断の手掛かりであり、この一覧だけでアプリ内分類や再試行動作を決めるものではありません。

### 恒久的な失敗になりやすい例

- `InvalidArgument`
- `FailedPrecondition`
- `OutOfRange`
- `PermissionDenied`
- `Unauthenticated`
- `Unimplemented`
- `NotFound`（存在しないことが正常な処理か、API / 操作ごとに判断）
- `AlreadyExists`（既存リソースの状態が要求と一致すると確認できる場合に限り、作成成功相当として扱える）

### 一時的な障害の可能性がある例

- `TooManyRequests`（HTTP 429）
- `ResourceExhausted`（gRPC）。一時的なレート制限か、待機しても解消しないクォータ超過かを error detail で判断する。
- `ServiceUnavailable`（HTTP 503 / gRPC `UNAVAILABLE`）
- `InternalServerError`（HTTP 500 / gRPC `INTERNAL`）
- `DeadlineExceeded`
- `Aborted`
- `Unknown`（API の詳細から一時障害と判断できる場合に限る）

HTTP / gRPC の status は SDK の例外クラスへ写像される場合があります。`ResourceExhausted` は `TooManyRequests` の派生型でもあるため、クラス名だけでは判別できません。両者の扱いを分けるときは transport、HTTP / gRPC status、構造化された error detail を確認し、`except` の順序だけに頼らないでください。瞬間的な過負荷と日次クォータ到達は同じ扱いにしません。API が `Retry-After` を返す場合は、その値を尊重します。

### 個別に注意する例外

- `RetryError`: API Core の再試行が尽きた状態です。`.cause` が最終原因です。API Core では `GoogleAPIError` の派生であり、`GoogleAPICallError` の派生ではないため、個別に扱って原因を記録します。
- `GoogleAPICallError`: API 呼び出しエラーの基底例外です。未分類の例外を一律に再試行する根拠にはせず、status と API 固有の詳細を確認します。
- `Cancelled`: アプリ終了・ユーザー操作など、キャンセル元と操作の意味に応じて扱います。

## 3. アプリ内の例外分類と上位側の扱い

Google Cloud Translation / Speech-to-Text の例外は各エンジンでドメイン例外に変換します。次の分類例外は新設または継承関係を整える対象を含む、目標とする契約です。

### Translation

```text
TranslateExceptionError
├── TranslateNonRetriableError
│   ├── TranslationQuotaExceededError
│   └── NotSupportedLanguagesError
└── TranslateRetriableError
    └── TranslationRateLimitError
```

- `TranslateNonRetriableError`: 恒久的な失敗。該当エンジンを利用不可として、以降そのエンジンへリクエストしません。
- `TranslateRetriableError`: 一時的な障害の可能性があるが、同一要求の即時再送はしません。エンジンは利用可能なままにし、次の独立したリクエストを許可します。
- `TranslateExceptionError`: 未分類またはその他の翻訳エラーです。恒久 / 一時の分類やエンジン可用性を暗黙に決めず、上位側の扱いを別途定義します。
- `NotSupportedLanguagesError`: 未対応言語が確定したときに使用し、利用者へ明示します。

### Speech-to-Text (STT)

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

`STTQuotaExceededError` は恒久的なクォータ超過として扱います。`NotSupportedLanguagesError` は Translation の分類であり、STT は未対応言語を判定できる API 詳細が確認できない限り、同名の分類を導入しません。

## 4. API status と error detail の変換方針

### 共通

- API のエラー詳細を解析できない場合も、エラーを記録してドメインの基底例外（`TranslateExceptionError` / `STTExceptionError`）として上位へ返します。詳細不明を恒久・一時のいずれかと推測しません。
- status / error detail と操作名を記録します。認証情報、トークン、リクエスト本文、音声などはログに出しません。
- HTTP status と gRPC status は、API の仕様を確認して同じドメイン分類へ写像します。

### `ResourceExhausted` / HTTP 429

- `ResourceExhausted` は error detail から原因を判断します。
  - クォータ超過: `TranslationQuotaExceededError` / `STTQuotaExceededError` とし、対応する `*NonRetriableError` に分類します。
  - 一時的なレート制限: `TranslationRateLimitError` / `STTRateLimitError` とし、対応する `*RetriableError` に分類します。
  - 原因を判定できない場合: 対応する `*NonRetriableError` に分類します。
- HTTP 429 / `TooManyRequests`: `TranslationRateLimitError` / `STTRateLimitError` とします。エンジンを利用不可にせず、次の独立したリクエストを許可します。`Retry-After` があれば次回リクエスト可能時刻の制御に使います。
- いずれも、アプリ側で同一要求を直ちに再送する意味ではありません。

### その他の HTTP status

- HTTP 4xx（429 を除く）は、API 固有の仕様が別の扱いを定めていない限り、恒久的エラーとして `TranslateNonRetriableError` / `STTNonRetriableError` に分類します。
- HTTP 5xx は一時的な障害として `TranslateRetriableError` / `STTRetriableError` に分類し、エンジンを利用不可にせず次の独立したリクエストを許可します。同一要求のアプリ側即時再送はしません。
- これらは標準的な初期分類です。API の個別仕様や構造化された error detail が異なる分類を裏付ける場合は、その根拠を優先します。

### `BadRequest` と未対応言語

- Translation の `BadRequest` は error detail から未対応言語とその他の不正リクエストを区別します。
- 未対応言語が確定した場合は既存の `NotSupportedLanguagesError` を維持します。
- 未対応言語か判断できない場合は `TranslateExceptionError` とし、誤った利用者向けメッセージを返しません。API 詳細が恒久的失敗を示す場合は `TranslateNonRetriableError` としても分類します。

### STT REST response body

- response body の解析に失敗した場合は、API 仕様変更または実装不整合の可能性があるエラーとして記録し、`STTExceptionError` で上位へ返します。
- HTTP error body を解析できる場合は Google API の status / error detail を使って上記の分類を適用します。本文全体をログに出力しません。

## 5. STT の処理フローと再試行

STT は配信時のリアルタイム処理です。同一音声セグメントの処理待ちが後続セグメントを詰まらせないよう、`STTProcessor` は `transcribe()` を 1 セグメントにつき 1 回だけ呼び、アプリ側で同一セグメントを自動再試行しません。

- 失敗した要求は `STTNonRetriableError`、`STTRetriableError` または未分類の `STTExceptionError` として速やかに上位へ返し、そのセグメントの処理を終了します。
- プロセッサは失敗したセグメントを再送せず、次のセグメント処理へ進みます。一時音声ファイルの cleanup は成功・失敗に関わらず行います。
- `STTRetriableError` は「同一要求を再送する」意味ではありません。エンジンを利用可能なままにし、次の独立した要求を受け付ける分類です。
- 失敗した音声を再送するかどうかはユーザーに委ねます。再認識が必要な場合は、ユーザーが発話をやり直します。
- Google SDK 内部の再試行は `STTProcessor` のアプリ側再試行とは別です。API / メソッドごとに SDK の既定 policy と timeout を確認し、リアルタイム処理を過度にブロックしないよう明示的に設定します。SDK 内部で必ず再試行されるとは仮定しません。

## 6. Translation の rate limit

- `TranslationRateLimitError` は `TransManager` の rate-limit 制御へ渡します。
- クールダウン中は翻訳要求を短絡して過負荷を回避します。上限到達と一時的なレート制限を区別し、クォータ超過を短い rate-limit cooldown だけで解消したものとして扱いません。
- API の `Retry-After` が取得できる場合は、次の独立した要求を許可するタイミングの制御に使います。
- `TranslateNonRetriableError` は該当エンジンを利用不可にし、`TranslateRetriableError` はエンジンを利用可能なままにします。複数エンジン間の fallback は TransManager の既存方針に従います。

## 7. SDK 内部再試行と timeout

- API / メソッドごとに SDK の retry policy、RPC timeout、再試行全体の時間上限を確認します。これらは別の設定です。
- SDK が内部再試行を行う場合、その回数と待機時間をアプリ側の試行回数と合算して把握します。同じ操作に無制限または意図しない多重再試行を設けません。
- STT のアプリ側セグメント再試行は行いません。SDK 内部再試行を許可するか、許可する場合の上限・timeout をどう設定するかは対象 API のリアルタイム要件と SDK 仕様に基づいて明示します。
- `RetryError` を受けた場合は `.cause` を記録します。アプリ側で同じ要求を再送して回復させることを前提にしません。

## 8. 現行実装からの変更要件

コード変更時は、この文書を仕様として次の差分を反映します。

1. `STTProcessor` の同一セグメントに対する retry loop と、それだけに使う retry 設定・待機を廃止する。失敗後も次のキュー項目を処理し、一時音声ファイルを cleanup する。
2. Google Cloud STT SDK / REST の例外を API status と error detail に基づいて `STTNonRetriableError`、`STTRetriableError`、クォータ例外または基底 `STTExceptionError` へ変換する。
3. Translation の例外変換で `BadRequest` を一律未対応言語とせず、error detail に基づいて判定する。必要な分類例外と継承関係を整える。
4. `ResourceExhausted` と 429 / `Retry-After` を区別し、TransManager と STT の次回独立要求に対する cooldown / 可用性を分類どおりに扱う。
5. 各 SDK 呼び出しの retry / timeout 設定がリアルタイム処理要件と矛盾しないことを確認する。

## 9. 個別確認が必要な事項

次は汎用方針だけでは値や実装詳細を確定できないため、対象 API / メソッドの仕様を確認して決定します。これらは STTProcessor に同一セグメント再試行を戻す理由にはなりません。

1. **API error detail の対応表:** Translation と STT の HTTP / gRPC response で、クォータ超過・一時的なレート制限・未対応言語を判別する具体的な reason / detail。
2. **SDK policy / timeout 値:** Speech の `recognize` と recognizer 管理 API ごとの SDK 既定値、およびリアルタイム要件を満たす明示値。
3. **`ExceptionError` の可用性:** detail が不足し恒久 / 一時を確定できない `TranslateExceptionError` / `STTExceptionError` を、該当エンジンの可用性へどう反映するか。
4. **操作固有の `NotFound` / `AlreadyExists` / `Cancelled`:** Speech recognizer の取得・作成・認識それぞれで、正常系、設定エラー、キャンセルのどれに該当するか。
5. **`Retry-After` の伝達:** 使用する SDK / REST transport から値を安全に取得できるか、次の独立リクエストをどの層で待機・抑制するか。
6. **Translation `BadRequest`:** API が返す具体的な詳細から未対応言語を確実に特定できる条件。

## 10. ログと確認チェックリスト

- operation 名、必要最小限の resource 識別子、例外型、HTTP / gRPC status、API reason を記録する。
- `RetryError` は `.cause` を記録する。SDK / REST transport が取得可能な場合のみ attempt 数や待機情報を記録する。
- リクエスト本文、翻訳対象文、音声、資格情報、トークンを記録しない。
- 未分類の `GoogleAPICallError` を一律に再試行しない。
- STT の同一セグメントを `STTProcessor` が再試行せず、失敗後に次のセグメントへ進む。
- `RetriableError` を同一要求の即時再送と誤解せず、次の独立要求を許可する分類として扱う。
- SDK 内部再試行、RPC timeout、API / アプリの可用性制御を分けて確認する。

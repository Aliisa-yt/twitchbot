# `twitchbot` 向け Copilot 指示

## 基本方針
- このファイルは **プロジェクト全体で共通のルールのみ** を記載する。
- コンポーネント別・ドメイン別の詳細仕様は、各 `.github/skills/*/SKILL.md` を一次情報とする。
- 共通ルールと SKILL が競合する場合、**SKILL を優先** する。
- SKILL 同士が競合する場合は、次の優先順位を上から順に適用する。
  1. 変更対象に最も近いドメイン SKILL（例: `tts-engine-spec`）
  2. 横断 SKILL（例: `manager-common`, `interface-spec`）
  3. 本ファイル（`copilot-instructions.md`）

## このファイルの適用範囲
- ここには「全体で常に守るべき事項」だけを置く。
- 実装フロー、例外分類、テスト観点などの詳細は SKILL に置く。
- 本ファイルに詳細仕様を追加しない。必要な詳細は該当 SKILL に追記する。
- 既存の SKILL 内容と重複する記述は、原則として本ファイルから削除し参照リンクに置き換える。

## SKILL 参照先
- チャットイベントフロー: [.github/skills/chat-events-flow/SKILL.md](skills/chat-events-flow/SKILL.md)
- Twitch 認証フロー: [.github/skills/twitch-auth-flow/SKILL.md](skills/twitch-auth-flow/SKILL.md)
- 翻訳マネージャー: [.github/skills/translation-manager/SKILL.md](skills/translation-manager/SKILL.md)
- 翻訳エンジン仕様: [.github/skills/translation-engine-spec/SKILL.md](skills/translation-engine-spec/SKILL.md)
- TTS マネージャー: [.github/skills/tts-manager/SKILL.md](skills/tts-manager/SKILL.md)
- TTS エンジン仕様: [.github/skills/tts-engine-spec/SKILL.md](skills/tts-engine-spec/SKILL.md)
- STT サービス: [.github/skills/stt-service/SKILL.md](skills/stt-service/SKILL.md)
- ONNX Runtime 設定: [.github/skills/onnx-runtime-setting/SKILL.md](skills/onnx-runtime-setting/SKILL.md)
- 設定ローダー仕様: [.github/skills/config-loader-spec/SKILL.md](skills/config-loader-spec/SKILL.md)
- キャッシュ / in-flight: [.github/skills/cache-inflight/SKILL.md](skills/cache-inflight/SKILL.md)
- コンポーネント仕様: [.github/skills/component-spec/SKILL.md](skills/component-spec/SKILL.md)
- インターフェース仕様: [.github/skills/interface-spec/SKILL.md](skills/interface-spec/SKILL.md)
- マネージャー共通: [.github/skills/manager-common/SKILL.md](skills/manager-common/SKILL.md)
- Google Cloud 認証: [.github/skills/google-cloud-api-auth/SKILL.md](skills/google-cloud-api-auth/SKILL.md)
- Google Cloud 例外処理: [.github/skills/google-cloud-api-exception/SKILL.md](skills/google-cloud-api-exception/SKILL.md)
- GUI デザイン: [.github/skills/gui-design/SKILL.md](skills/gui-design/SKILL.md)
- コード生成ガイドライン: [.github/skills/code-generator/SKILL.md](skills/code-generator/SKILL.md)
- 命名規則: [.github/skills/naming-rules/SKILL.md](skills/naming-rules/SKILL.md)
- 単体テスト規約: [.github/skills/unit-test/SKILL.md](skills/unit-test/SKILL.md)
- Windows 実行フロー: [.github/skills/windows-workflow/SKILL.md](skills/windows-workflow/SKILL.md)
- レビュー: [.github/skills/code-review/SKILL.md](skills/code-review/SKILL.md)
- リファクタリング方針: [.github/skills/refactoring-policy/SKILL.md](skills/refactoring-policy/SKILL.md)
- 将来の実装: [.github/skills/future-implementation/SKILL.md](skills/future-implementation/SKILL.md)

## 作業開始時の必須手順
- 変更対象に対応する SKILL を最初に読む。
- 複数ドメインへ跨る変更では、関連 SKILL をすべて確認してから実装する。
- Windows でコマンドを手動実行する場合は、最初に `& .\.venv\Scripts\Activate.ps1` を実行する。
- Windows の詳細なコマンド手順は `windows-workflow` SKILL を参照する。

## プロジェクト規約
コードの記述規約（Python バージョン、ファイル形式、Docstring、型ヒント、ロギング、例外処理、実行環境等）の詳細は [code-generator SKILL](skills/code-generator/SKILL.md) を参照すること。

## 使用言語ルール
- コメント（docstring・インラインコメント含む）は英語のみで記述する。
  - 機能要件上必要な場合（辞書エントリ、かな変換表、ユーザー向け日本語文言、I/O サンプルなど）を除き、日本語コメントは禁止。
- `NOTE:` や `TODO:` で始まるコメントは使用言語を問わない。（他の言語に翻訳しない。簡潔化は可）
- ドキュメント（`./docs/` 配下に生成するもの）は原則として日本語で記載し、必要に応じて英語での記述も許可する（例: ユーザーによる指示、外部仕様の引用、コードサンプルなど）。
- チャットは原則として日本語で行い、必要に応じて英語での記述も許可する（例: ユーザー向け文言、外部仕様の引用、コードサンプルなど）。
- コミットメッセージは英語で、且つ簡潔に記述する。
- 言語指定の優先順位は、チャットによる指定 → 個別 SKILL による指定 → 本ファイルの指定の順とする。

## 変更時の共通ルール
- 変更は最小差分で行い、無関係なリファクタや整形を混在させない。
- **例外**: 以下の場合は同一変更内でリファクタや整形を許可する。
  - ユーザーによる事前確認と許可がある場合。
  - 機能に影響の無い整形のみの場合。(例: 文字列の結合方法の統一、インポート順の整理、空行の追加/削除など)
  - 詳細は `refactoring-policy` SKILL を参照する。
- 変更前に、変更対象の SKILL を確認し、必要に応じて関連 SKILL も確認する。
- 互換性情報・バグ回避策に関する既存記述は削除しない（簡潔化は可）。
- 仕様変更時は、まず該当 SKILL を更新し、その後コードへ反映する。
- 振る舞い変更時は、実装・テスト・ドキュメント（SKILL/`docs/`）を同一変更で整合させる。
- 既存 SKILL と実装の不整合を見つけた場合は、推測で実装を寄せず、先に不整合を解消してから修正する。
- 命名規約、マネージャー実装、インターフェース契約、各ドメイン仕様は該当 SKILL を参照する。

## 変更完了時チェック（共通）
- 変更したファイルに対して `ruff check .` / `mypy .` の影響範囲を確認する。
- 影響範囲に応じて `pytest tests/` もしくは対象テストを実行する。
- ドキュメント変更を伴う場合は、関連する SKILL / `docs/` の記述整合を確認する。
- Windows 実行手順に関わる変更では、`windows-workflow` SKILL との矛盾がないことを確認する。
- テスト方針・作法の詳細確認が必要な場合は `unit-test` SKILL を参照する。

## ドキュメント配置
- ドキュメントは、プロジェクト全体で共通のルールや方針を記載する `copilot-instructions.md` と、ドメイン別の詳細仕様を記載する SKILL に分けて管理する。
- ドキュメントは原則として日本語で記載し、必要に応じて英語での記述も許可する（例: ユーザー向け文言、外部仕様の引用、コードサンプルなど）。
- ドキュメントは Markdown 形式で作成し、必要に応じて画像やコードサンプルを含める。
- 分析・設計ドキュメントは [docs/](../docs/) に配置するが、必要に応じてサブディレクトリを作成して整理する。ルート直下の例外は `README.md` と `LICENSE`。
  - レビュー用ドキュメントは `docs/_review/` に配置し、レビュー完了後はユーザーが手動で削除する。
  - 新機能や大規模変更の設計ドキュメントは、実装前に `docs/_planning/` に配置してレビューを受けることが推奨される。
- SKILL は `.github/skills/` に配置する。SKILL はドキュメントと同様に、必要に応じてサブディレクトリを作成して整理する。

## 更新ルール（本ファイル）
- 本ファイルを更新するのは、プロジェクト全体に適用される新しい横断ルールを追加・変更する場合のみとする。
- 特定ドメインに閉じるルールを追加する場合は、本ファイルではなく該当 SKILL を更新する。
- 参照先 SKILL の追加・改名・削除時は、この `SKILL 参照先` セクションを同時に更新する。

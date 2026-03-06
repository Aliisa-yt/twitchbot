# `twitchbot` 向け Copilot 指示

## 基本方針
- このファイルは **プロジェクト全体で共通のルールのみ** を記載する。
- コンポーネント別・ドメイン別の詳細仕様は、各 `.github/skills/*/SKILL.md` を正とする。
- 共通ルールと SKILL が競合する場合、**SKILL を優先** する。

## SKILL 参照先
- チャットイベントフロー: [.github/skills/chat-events-flow/SKILL.md](skills/chat-events-flow/SKILL.md)
- 翻訳マネージャー: [.github/skills/translation-manager/SKILL.md](skills/translation-manager/SKILL.md)
- 翻訳エンジン仕様: [.github/skills/translation-engine-spec/SKILL.md](skills/translation-engine-spec/SKILL.md)
- TTS マネージャー: [.github/skills/tts-manager/SKILL.md](skills/tts-manager/SKILL.md)
- TTS エンジン仕様: [.github/skills/tts-engine-spec/SKILL.md](skills/tts-engine-spec/SKILL.md)
- STT サービス: [.github/skills/stt-service/SKILL.md](skills/stt-service/SKILL.md)
- キャッシュ / in-flight: [.github/skills/cache-inflight/SKILL.md](skills/cache-inflight/SKILL.md)
- コンポーネント仕様: [.github/skills/component-spec/SKILL.md](skills/component-spec/SKILL.md)
- interface 仕様: [.github/skills/interface-spec/SKILL.md](skills/interface-spec/SKILL.md)
- マネージャー共通: [.github/skills/manager-common/SKILL.md](skills/manager-common/SKILL.md)
- 命名規則: [.github/skills/naming-rules/SKILL.md](skills/naming-rules/SKILL.md)
- 単体テスト規約: [.github/skills/unit-test/SKILL.md](skills/unit-test/SKILL.md)
- Google Cloud 認証: [.github/skills/google-cloud-api-auth/SKILL.md](skills/google-cloud-api-auth/SKILL.md)
- Google Cloud 例外処理: [.github/skills/google-cloud-api-exception/SKILL.md](skills/google-cloud-api-exception/SKILL.md)
- GUI デザイン: [.github/skills/gui-design/SKILL.md](skills/gui-design/SKILL.md)
- Windows実行フロー: [.github/skills/windows-workflow/SKILL.md](skills/windows-workflow/SKILL.md)

## 重要ワークフロー（Windows）
- **最初に venv を有効化**: すべてのコマンド実行前に `& .\.venv\Scripts\Activate.ps1` を実行する。
- **ローカル実行**: `set TWITCH_API_CLIENT_ID=<id> && set TWITCH_API_CLIENT_SECRET=<secret> && python .\twitchbot.py [--owner NAME --bot NAME --debug]`（OAuth トークンは [tokens.json](../tokens.json) に保存される）。
- **EXE ビルド**: `pyinstaller twitchbot.spec --clean`（または「Build EXE with PyInstaller」タスクを使用）。
- **テスト**（pytest-asyncio）: `pytest tests/`（単体）または `coverage run -m pytest tests/ -v && coverage report`（全体）。
- **Lint**: `ruff check . && ruff format . && mypy .`（ルールは [pyproject.toml](../pyproject.toml) を参照）。
- **デバッグログ**: `--debug` フラグを付与するか、INI で `DEBUG = True` を設定する。twitchio ロガーの既定は WARNING。

## プロジェクト規約
- **Python 3.13 のみ**: 各モジュールの先頭に常に `from __future__ import annotations` を配置する。
- **ファイル形式**: UTF-8 + LF 改行、行長は 120（ruff で強制）。
  - ログファイル等のテキストファイルも UTF-8 + LF 改行で保存する。
- **ロギング**: モジュールごとに `logger = LoggerUtils.get_logger(__name__)` を 1 回だけ使用し、`LoggerUtils` を再初期化しない。
- **例外**: 送出前にエラーメッセージを `msg` 変数へ代入する（例: `msg = "error"; raise ValueError(msg)`）。
- **未使用引数**: Lint 抑制のため、docstring 直後に `_ = arg1, arg2` を置く。
- **Docstring**: Google スタイルを使用し、モジュール docstring → `from __future__ import annotations` → import の順序を守る。
  - モジュール docstring: モジュールの目的を簡潔に記述する。
  - クラス docstring: 挙動と主要属性を簡潔に記述する。
  - メソッド docstring: 挙動、引数、戻り値、送出例外を簡潔に記述する。
  - **例外**: 挙動が自明な単純メソッドは docstring を省略してよい。
  - **重要**: 互換性情報やバグ回避策に関する記述は削除しない。簡潔化は許可されるが保持が必須。この規則は他の文書規約より優先する。
- **コメント**: コメント（docstring・インラインコメント含む）は英語のみで記述する。機能要件上必要な場合（辞書エントリ、かな変換表、ユーザー向け日本語文言、I/O サンプルなど）を除き、日本語コメントは禁止。
  - **重要**: 互換性情報やバグ回避策に関する記述は削除しない。簡潔化は許可されるが保持が必須。この規則は他のコメント規約より優先する。
- **インラインコメント**: 非自明またはバグを生みやすいロジックに限定し、自明なコードへのコメントは避ける。
- **型ヒント**: すべての関数・メソッドには可能な限り完全な型ヒントを付与する。未使用引数は `_` で始める。
  - **例外**: 非常に複雑な表記になる場合や、テストコードについては省略してもよい。
- **タスク生成**: `asyncio.create_task` でタスクを作成する際は、`name` 引数でわかりやすい名前を付ける（例: `name=f"STT-{service_name}-Task"`）。名前はタスクの目的と関連コンポーネントを反映させ、ログやデバッグで識別しやすいものにする。
  - **例外**: 一時的なタスクや、ループ内で大量に作成されるタスクなど、識別が困難な場合は省略してもよい。
  - **重要**: タスクの例外は必ずログに記録する。タスク完了後に `task.exception()` を呼び出し、例外が発生している場合は適切なログレベルで記録する（例: `logger.warning("STT background task failed (name=%s): %s", task.get_name(), err)`）。これにより、タスク内で発生したエラーが見逃されることを防止する。
- **非同期コード**: すべての非同期関数は `async def` で定義し、適切な場所で `await` を使用する。非同期コード内での例外処理は、異常系を考慮して安全に停止できる状態を維持する。
- **実行環境**: コードは Windows 10/11 上の Python 3.13 で動作することを前提とする。クロスプラットフォーム対応も可能な限り行うが、Windows以外の環境でのテストができないため動作は保証しない。
  - **例外**: Windows固有の機能やAPIを使用する場合は、コード内で明確にコメントし、非Windows環境での動作は保証しない旨を記載する。
  - **重要**: Pyinstaller でのビルドを前提とするため、外部依存はできるだけ少なくし、必要な場合は明確にドキュメント化する。ビルド後の実行環境で必要なランタイムやライブラリが適切に含まれていることを確認する。特にファイルパスは Pyinstaller での実行時には参照先が合わなくなっていることがあるため注意する。


## 変更時の共通ルール
- 変更は最小差分で行い、無関係なリファクタや整形を混在させない。
- 互換性情報・バグ回避策に関する既存記述は削除しない（簡潔化は可）。
- 例外・ログ・非同期終了処理は失敗系を先に考慮し、異常時でも安全停止できる状態を維持する。
- 新規仕様追加時は、まず該当 SKILL を更新し、その後コードへ反映する。

## テストパターン
- `@pytest.fixture` を使用して再利用可能なモックを作成する（[tests/test_bot.py](../tests/test_bot.py) を参照）。
- 非同期テストには `@pytest.mark.asyncio` を付与する（pytest-asyncio）。
- 外部依存は `unittest.mock.AsyncMock`、`MagicMock`、`patch` でモックする。
- 複数テストファイルで共有する fixture は conftest.py に配置する。

## 変更完了時チェック（共通）
- 変更したファイルに対して `ruff check .` / `mypy .` の影響を確認する。
- 影響範囲に応じて `pytest tests/` もしくは対象テストを実行する。
- ドキュメント変更を伴う場合は、関連する SKILL / `docs/` の記述整合を確認する。

## ドキュメント配置
- 分析・設計ドキュメントは [docs/](../docs/) に配置するが、必要に応じてサブディレクトリを作成して整理する。ルート直下の例外は `README.md` と `LICENSE`。
- SKILL は `.github/skills/` に配置する。SKILL はドキュメントと同様に、必要に応じてサブディレクトリを作成して整理する。

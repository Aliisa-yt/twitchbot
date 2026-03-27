---
name: windows-workflow
description: Windows 環境での開発用ツール実行手順と、venv 有効化忘れを防ぐ運用ルール
keywords: [windows, powershell, venv, activate, pytest, coverage, pyinstaller, ruff, mypy]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

この文書は Windows 環境での実行フローを統一し、仮想環境の有効化漏れによる無駄な試行を防ぐための運用ガイドです。

## 1. 最重要ルール（毎回共通）
- すべてのコマンド実行前に、必ず venv を有効化する。
- 実行シェルは PowerShell を前提とする。
- venv 未有効化が疑われる場合は、まず有効化を再実行してから再試行する。

```powershell
& .\.venv\Scripts\Activate.ps1
```

## 2. 実行順序テンプレート
1. リポジトリルートへ移動する。
2. venv を有効化する。
3. 必要なツール（lint / test / build / run）を実行する。

```powershell
Set-Location D:\workspace\twitchbot
& .\.venv\Scripts\Activate.ps1
```

## 3. ローカル実行（Bot 起動）
- Twitch API の環境変数を設定してから `twitchbot.py` を実行する。
- トラブルシュート時は `--debug` を付ける。

```powershell
& .\.venv\Scripts\Activate.ps1
$env:TWITCH_API_CLIENT_ID = "<id>"
$env:TWITCH_API_CLIENT_SECRET = "<secret>"
python .\twitchbot.py --owner <owner_name> --bot <bot_name> --debug
```

## 4. テスト実行（pytest / coverage）
- 単体確認は `pytest`、全体確認は `coverage` を使う。
- どちらも venv 有効化後に実行する。

```powershell
& .\.venv\Scripts\Activate.ps1
pytest tests/
```

```powershell
& .\.venv\Scripts\Activate.ps1
coverage run -m pytest tests/ -v
coverage report
```

## 5. Lint / Format / Type Check
- 実装変更後は `ruff check`、`ruff format`、`mypy` を順に実行する。

```powershell
& .\.venv\Scripts\Activate.ps1
ruff check .
ruff format .
mypy --explicit-package-bases .
```

## 6. EXE ビルド（PyInstaller）
- 配布用ビルドは `pyinstaller twitchbot.spec --clean` を使う。

```powershell
& .\.venv\Scripts\Activate.ps1
pyinstaller twitchbot.spec --clean
```

## 7. VS Code タスク利用時の扱い
- 既存タスク（Coverage / PyInstaller）は `.venv/Scripts` を PATH に含めているため、タスク実行時は venv 有効化漏れの影響を受けにくい。
- ただし、手動コマンド実行時は必ず `Activate.ps1` を先に実行する。

## 8. 失敗時の一次切り分け
1. 先頭で `& .\.venv\Scripts\Activate.ps1` を実行したか確認する。
2. `Get-Command python` の参照先が `.venv\Scripts\python.exe` になっているか確認する。
3. 依存パッケージ未検出エラーは、まず venv 有効化漏れを疑う。

```powershell
& .\.venv\Scripts\Activate.ps1
Get-Command python
```

## 9. 修正時チェックリスト
1. すべての実行例が venv 有効化付きになっているか。
2. Windows PowerShell 構文（`$env:` など）で統一されているか。
3. `copilot-instructions.md` と本 SKILL の手順に矛盾がないか。
4. 新しい実行コマンドを追加した場合、ここにも追記したか。

## 10. ツールの使用可否リスト
- ツールを使用する際は、Windows 環境での動作確認がされているかを基準にする。
- 新しいツールを使う前に、まずこのリストを確認する。
- 使用可にあるツールは、用途が適切であれば優先して使用する。
- リストにないツールを試す場合は、Windows で 1 回は動作確認し、結果に応じてこのリストを更新する。
- 使用できなかったツールは、以下のフォーマットでこのファイルの末尾に追加すること。使用可能なツールは、Windows での実行手順に含めること。

    ```
    使用したツール: <ツール名>
    ツールの実行時のコマンドライン: <コマンドライン>  非常に長い場合は省略して要点だけ記載する
    エラー内容: エラーログ、またはエラーの概要説明
    ```

- ツール実行に失敗した場合は、原因を簡単に切り分けたうえで代替手段へ切り替え、再発防止のために使用可否をこのリストへ反映する。
- 使用不可にリストされているツールは、ツールの動作内容により追加インストールし、使用可能にする可能性があります。

- **使用可**: PowerShell、venv、pytest、coverage、PyInstaller、ruff、mypy
- **使用不可**: WSL、Conda、Docker

## 11. 使用不可ツールの例

使用したツール: runTests
ツールの実行時のコマンドライン: files=["d:\\workspace\\twitchbot\\tests\\core\\tts\\engines\\test_voicevox.py"], mode="run"
エラー内容: `No tests found in the files. Ensure the correct absolute paths are passed to the tool.` が返り、対象ファイルのテスト検出に失敗。
切り分け結果: 同一ファイルを `python -m pytest tests/core/tts/engines/test_voicevox.py -q` で実行すると 9 件検出・実行できたため、テスト実体ではなくツール側の検出条件差異と判断。
代替手段: Windows では venv 有効化後に `python -m pytest <対象ファイル>` を優先し、runTests で同症状が出た場合は速やかに切り替える。

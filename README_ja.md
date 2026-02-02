# Twitchbot

Twitch チャット用の翻訳 + TTS ボット。チャットイベントを購読し、メッセージを翻訳して、設定された TTS エンジンを使用して読み上げます。エントリーポイントは `twitchbot.py` で、設定、OAuth、翻訳、TTS、ボットコンポーネントを統合します。

## セットアップ
- Python 3.13 以上
- 実行前に [Twitch Developers](https://dev.twitch.tv/) でアプリケーションを登録し、`CLIENT ID` と `CLIENT SECRET` を取得してください。登録手順はここでは説明しませんので、Twitch のドキュメントやセットアップガイドに従ってください。アプリ作成時には **OAuth Redirect URLs** に `http://localhost` を追加してください。
- Twitch API 認証情報を環境変数として設定：
  - `TWITCH_API_CLIENT_ID`
  - `TWITCH_API_CLIENT_SECRET`
- 依存関係をインストール: `pip install -r requirements.txt`
- テンプレートから `twitchbot.ini` を準備：
  1. `twitchbot.ini.example` を `twitchbot.ini` にコピー
  2. `twitchbot.ini` を編集して、Twitch チャンネルオーナー名とボットアカウント名を設定
  3. 必要に応じて他の設定をカスタマイズ（翻訳エンジン、TTS パラメータなど）

## 実行

### ローカル実行
1) 上記の環境変数を設定します。
2) リポジトリのルートから実行: `python twitchbot.py [--owner OWNER_NAME] [--bot BOT_NAME] [--debug]`
   - `--owner OWNER_NAME`（オプション）: Twitch チャンネルオーナー名。`twitchbot.ini` の設定を上書きします
   - `--bot BOT_NAME`（オプション）: ボットアカウント名。`twitchbot.ini` の設定を上書きします
   - `-d`, `--debug`（オプション）: 詳細なログ出力を行うデバッグモードを有効にします
3) 初回起動時はブラウザで OAuth 認証が開きます。トークンは `tokens.db` にキャッシュされます。
4) ボットを停止するには `Ctrl+C` を押してください。

### PyInstaller で実行ファイルをビルド
`.spec` ファイルが提供されています。リポジトリのルートから EXE をビルドします：
```powershell
pyinstaller twitchbot.spec --clean
```
出力される実行ファイルは `dist/twitchbot/` ディレクトリに生成されます。

## 設定

詳細な設定項目については [CONFIGURATION_ja.md](docs/CONFIGURATION_ja.md) を参照してください。

主な設定項目：
- **翻訳エンジン**: Google、DeepL、Google Cloud
- **TTS パラメータ**: 音声選択、速度、トーン、音量
- **チャットフォーマット**: 表示名、言語コード、エモート
- **時報**: スケジュール済みアナウンスメント

## 開発

### テストの実行
```powershell
pytest -q
```

カバレッジレポートを生成する場合：
```powershell
coverage run -m pytest tests/ -v
coverage report
coverage html  # htmlcov/ に HTML レポートを生成
```

### リントと型チェック
```powershell
ruff check .
ruff format .
mypy .
```

すべての設定は [pyproject.toml](pyproject.toml) に記述されています。

## ライセンス
- コアプロジェクト: MIT License（[LICENSE](LICENSE) を参照）
- バンドルされているアルファベットからカタカナへの変換辞書 [dic/bep-eng.dic](dic/bep-eng.dic) は [Bilingual Emacspeak Project](http://www.argv.org/bep/) 由来で、GPL v2 でライセンスされています（[LICENSE-GPL-v2](LICENSE-GPL-v2) を参照）

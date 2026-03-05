name: component-spec
description: コンポーネント登録、依存解決、ロード/ティアダウン、SharedData連携の実装仕様
keywords: component, registry, dependency-resolution, topological-sort, lifecycle, load, teardown, shared-data

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。

このプロジェクトでは、Bot本体以外の機能（翻訳・TTS・STT・キャッシュなど）はすべてコンポーネントとして実装し、
Bot起動時にロード、Bot終了時にティアダウンします。

## 1. 全体フロー（実装準拠）

### 起動時
1. `Bot.setup_hook()` が呼ばれる。
2. `SharedData.async_init()` で共有マネージャー（Trans/TTS/STT など）を初期化する。
3. `ComponentBase.component_registry` の依存関係を検証する。
   - 未知の依存先がある場合は `RuntimeError`。
   - 循環依存がある場合も `RuntimeError`。
4. 依存関係をトポロジカルソートしてアタッチ順を決める。
5. 順番に `add_component()` し、各コンポーネントの `component_load()` が実行される。

### 終了時
1. `Bot.close()` が呼ばれる。
2. アタッチ済みコンポーネントを **逆順** で `remove_component()` する。
3. 各コンポーネントの `component_teardown()` が実行される。
4. `Bot.close()` は複数回呼ばれる可能性があるため、`_closed` フラグで二重実行を防ぐ。

## 2. 登録の仕組み

- コンポーネントは `ComponentBase` を継承する。
- サブクラス定義時に `__init_subclass__()` で `component_registry` に自動登録される。
- 依存関係は `depends: ClassVar[list[str]]` で宣言する。
- `depends` には **クラス名文字列**（例: `"TranslationServiceComponent"`）を指定する。

例:

```python
from __future__ import annotations

from typing import ClassVar

from core.components.base import ComponentBase
from utils.logger_utils import LoggerUtils

logger = LoggerUtils.get_logger(__name__)


class MyComponent(ComponentBase):
    depends: ClassVar[list[str]] = ["OtherComponent"]

    async def component_load(self) -> None:
        logger.debug("'%s' component loaded", self.__class__.__name__)

    async def component_teardown(self) -> None:
        logger.debug("'%s' component unloaded", self.__class__.__name__)
```

## 3. 依存順序とティアダウン順序

- ロード順序は `depends` に従って自動解決される。
- ティアダウンはロード順の逆順で実行されるため、依存先より先に依存元が解放される。
- 明示的な順序制御が必要な場合も、まずは `depends` で表現する。

## 4. 実装時の推奨パターン

### 4.1 設定アクセスと初期化エラー

`self.config` は多段プロパティアクセスになるため、設定欠落時は `AttributeError` をまとめて捕捉する。
`getattr()` を段階的に使うより、`try-except` で囲うほうが実装と整合しやすい。

```python
async def component_load(self) -> None:
    try:
        stt_enabled: bool = self.config.STT.ENABLED
        if isinstance(stt_enabled, bool) and stt_enabled:
            await self.stt_manager.async_init(on_result=self._on_stt_result)
            logger.debug("'%s' component loaded", self.__class__.__name__)
            return
        logger.info(
            "STT service is disabled by configuration; '%s' component loaded without initializing STT",
            self.__class__.__name__,
        )
    except AttributeError as err:
        logger.warning("STT service initialization skipped due to missing configuration: %s", err)
```

### 4.2 ティアダウン時の存在しないリソース

クリーンアップ対象が存在しないケースは `AttributeError` を許容する。

```python
from contextlib import suppress


async def component_teardown(self) -> None:
    with suppress(AttributeError):
        await self.stt_manager.close()
    logger.debug("'%s' component unloaded", self.__class__.__name__)
```

## 5. ログ方針

- このリポジトリでは `LoggerUtils.get_logger(__name__)` を使用する。
- `component_load()` / `component_teardown()` の成功ログは `debug` で残す。
- 無効設定でのスキップは `info`、設定欠落などの異常系は `warning` 以上を使う。

## 6. SharedData 利用方針

- コンポーネント間で共有するマネージャーは `self.shared` 経由で参照する。
- `self.config` / `self.trans_manager` / `self.tts_manager` / `self.stt_manager` などのプロパティを優先して使う。
- 共有リソースの初期化は `Bot.setup_hook()` 側で行われる前提のため、コンポーネント側では利用時の例外処理を行う。

## 7. テスト観点（最小セット）

- 依存解決がトポロジカル順で行われ、循環/未知依存で起動失敗すること。
- `component_load()` 失敗時に他コンポーネントへ不要な波及がないこと。
- `component_teardown()` が逆順で実行され、二重終了でも破綻しないこと。
- 設定欠落時の `AttributeError` ハンドリングで安全にスキップできること。
- ロード/アンロード時のログが運用確認に必要な粒度を満たすこと。

## 8. チェックリスト（追加・変更時）

1. `ComponentBase` 継承になっているか。
2. `depends` が正しいクラス名で定義されているか。
3. `component_load()` と `component_teardown()` の双方が実装されているか。
4. 設定欠落・初期化失敗・後始末失敗を想定した例外処理があるか。
5. ロード/アンロードのログが出るか。
6. 依存順序（ロード）と逆順解放（ティアダウン）で整合が取れているか。

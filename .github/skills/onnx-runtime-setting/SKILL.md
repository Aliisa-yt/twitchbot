---
name: onnx-runtime-setting
description: ONNX Runtime のインストールと設定に関するガイドライン
keywords: [onnx, onnxruntime, installation, setup, python, uv]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。
この文書は ONNX Runtime の基本利用と、当リポジトリでの Silero ONNX VAD 利用方針をまとめます。

## 1. インストール（Python）

**本リポジトリで使用しているバージョン: `onnxruntime==1.32.0`**

依存関係は `pyproject.toml` で管理し、正確な解決結果は `uv.lock` に記録します。バージョンを変更する場合は `uv add` を使用し、環境の同期には `uv sync` を使用してください。

用途に応じてパッケージを使い分けます。

- CPU: `onnxruntime`
- CUDA/TensorRT: `onnxruntime-gpu`
- DirectML (Windows, Sustained Engineering): `onnxruntime-directml`

```powershell
uv sync
```

この依存関係は `pyproject.toml` で固定されています。固定バージョンを変更する場合は、次のコマンドを使用してください。

```powershell
uv add "onnxruntime==<version>"
```

補足:

- 本リポジトリは CPU 版 `onnxruntime` を依存関係に指定しています。
- CPU/GPU/DirectML の各パッケージは同じ `onnxruntime` Python モジュールを提供します。同一環境に複数の実装を混在させず、利用する実行プロバイダーに対応したパッケージを選んでください。
- CUDA 利用時は、使用する ONNX Runtime のバージョンに対応した CUDA/cuDNN の組み合わせを公式互換性表で確認してください。PyTorch との連携も同表の案内に従ってください。
- DirectML は Sustained Engineering モードです。新しい Windows アプリケーションでは WinML が推奨されています。
- このリポジトリのバージョンを変更する場合は `pyproject.toml` と `uv.lock` の両方を更新してください（通常は `uv add "onnxruntime==<version>"` が lockfile も更新します）。

## 2. 推論の基本

```python
import numpy as np
import onnxruntime as ort

session = ort.InferenceSession(
	"model.onnx",
	providers=["CPUExecutionProvider"],
)

input_name = session.get_inputs()[0].name
output_name = session.get_outputs()[0].name
input_data = np.zeros((1, 16000), dtype=np.float32)

result = session.run([output_name], {input_name: input_data})
```

## 3. SessionOptions の実用項目
よく使うのは以下です。

- `intra_op_num_threads`
- `inter_op_num_threads`
- `execution_mode` (`ORT_SEQUENTIAL` / `ORT_PARALLEL`)
- `graph_optimization_level`
- `log_severity_level` (0: Verbose, 1: Info, 2: Warning, 3: Error, 4: Fatal)

```python
import onnxruntime as ort

so = ort.SessionOptions()
so.intra_op_num_threads = 2
so.inter_op_num_threads = 1
so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
so.log_severity_level = 2
```

## 4. Execution Provider 設定
GPU メモリ上限など EP 固有設定は provider options で渡します。

```python
import onnxruntime as ort

providers = [
	("CUDAExecutionProvider", {
		"device_id": 0,
		"gpu_mem_limit": 2 * 1024 * 1024 * 1024,
	}),
	"CPUExecutionProvider",
]

session = ort.InferenceSession("model.onnx", providers=providers)
```

## 5. 量子化の正しい扱い
量子化は `SessionOptions` のフラグで有効化する方式ではありません。

- 事前に量子化済み ONNX モデルを作成して実行する。
- Python API は `onnxruntime.quantization`（`quantize_dynamic`, `quantize_static` など）を使う。

```python
from onnxruntime.quantization import quantize_dynamic

quantize_dynamic("model_fp32.onnx", "model_int8.onnx")
```

## 6. 本リポジトリでの使い方（silero_onnx.py）
対象: `src/core/stt/vad/silero_onnx.py`

本実装は、Silero VAD ONNX モデルを CPU で安定動作させるため、次の設計を採用しています。

- Provider を `CPUExecutionProvider` 固定にする。
- `onnx_threads` から `intra_op_num_threads` を設定する。
- `inter_op_num_threads = 1` と `ORT_SEQUENTIAL` で並列過多を避ける。
- `session.intra_op.allow_spinning = 0` と `session.inter_op.allow_spinning = 0` を設定し、待機時 CPU 負荷を抑制する。
- Silero 特有の前置コンテキスト（16 kHz で 64 サンプル、8 kHz で 32 サンプル）を各ウィンドウに連結する。
- state 入出力をキャッシュして、次回推論に引き継ぐ。

現行実装の SessionOptions 設定:

```python
providers = ["CPUExecutionProvider"]
session_options = ort.SessionOptions()
session_options.intra_op_num_threads = max(1, int(onnx_threads))
session_options.inter_op_num_threads = 1
session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
session_options.add_session_config_entry("session.intra_op.allow_spinning", "0")
session_options.add_session_config_entry("session.inter_op.allow_spinning", "0")

session = ort.InferenceSession(
    str(model_path),
    sess_options=session_options,
    providers=providers,
)
```

現行の公式 Python API でも、上記の `InferenceSession`、`SessionOptions`、provider 選択、および `session.run()` の基本的な使い方が案内されています。このため、これらの例を ONNX Runtime 1.32.0 向けに変更する必要はありません。将来バージョン固有の変更を行う場合は、実装前にリリースノートと provider の互換性資料を確認してください。

## 7. トラブルシューティング

- `ImportError` / DLL エラー: インストールしたパッケージ種別（CPU/GPU/DirectML）と環境が一致しているか確認。
- CUDA 利用時に provider が出ない: `ort.get_available_providers()` と `session.get_providers()` で利用可能/有効な provider を確認。
- Windows + CUDA で DLL 解決失敗: PATH、または `onnxruntime.preload_dlls()` の利用を検討。
- 想定より CPU 使用率が高い: `intra_op_num_threads` と `allow_spinning` の設定を見直す。
- 依存関係が反映されない: 仮想環境を有効化して `uv sync` を実行し、使用中の interpreter がプロジェクトの `.venv` であることを確認。

## 8. 参照先

- Install: <https://onnxruntime.ai/docs/install/>
- Python API Summary: <https://onnxruntime.ai/docs/api/python/api_summary.html>
- Execution Providers: <https://onnxruntime.ai/docs/execution-providers/>
- CUDA EP: <https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html>
- Compatibility: <https://onnxruntime.ai/docs/reference/compatibility.html>
- Quantization: <https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>
- Release notes: <https://github.com/microsoft/onnxruntime/releases>

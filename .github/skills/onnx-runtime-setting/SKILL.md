---
name: onnx-runtime-setting
description: ONNX Runtime のインストールと設定に関するガイドライン
keywords: [onnx, onnxruntime, installation, setup, python, pip]
---

共通規約は [.github/copilot-instructions.md](../../copilot-instructions.md) を参照してください。
この文書は ONNX Runtime の基本利用と、当リポジトリでの Silero ONNX VAD 利用方針をまとめます。

## 1. インストール（Python）

**本リポジトリで使用しているバージョン: `onnxruntime==1.24.4`**

> **注意**: メジャーバージョンアップ時は API 互換性を必ず公式ドキュメントで確認してください。

用途に応じてパッケージを使い分けます。

- CPU: `onnxruntime`
- CUDA/TensorRT: `onnxruntime-gpu`
- DirectML (Windows, Sustained Engineering): `onnxruntime-directml`

```powershell
pip install onnxruntime==1.24.4
```

補足:

- 本リポジトリの `requirements.txt` は CPU 版 `onnxruntime` を採用しています。
- CUDA 利用時は CUDA/cuDNN の互換性を公式表で必ず確認してください。
- `onnxruntime-gpu` は、PyTorch と CUDA/cuDNN のメジャーバージョンが一致していることが重要です。

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
- Silero 特有の前置コンテキスト（16kHz で 64 サンプル、8kHz で 32 サンプル）を毎ウィンドウに連結する。
- state 入出力をキャッシュして、次回推論に引き継ぐ。

実装イメージ:

```python
providers = ["CPUExecutionProvider"]
so = ort.SessionOptions()
so.intra_op_num_threads = min(max(0, onnx_threads), 8)  # 0 は自動設定（OS に依存）、1-8 は指定スレッド数、8 を超える値は 8 として扱う
so.inter_op_num_threads = 1
so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
so.add_session_config_entry("session.intra_op.allow_spinning", "0")
so.add_session_config_entry("session.inter_op.allow_spinning", "0")

session = ort.InferenceSession(model_path, sess_options=so, providers=providers)
```

## 7. トラブルシューティング

- `ImportError` / DLL エラー: インストールしたパッケージ種別（CPU/GPU/DirectML）と環境が一致しているか確認。
- CUDA 利用時に provider が出ない: `ort.get_available_providers()` で有効 provider を確認。
- Windows + CUDA で DLL 解決失敗: PATH、または `onnxruntime.preload_dlls()` の利用を検討。
- 想定より CPU 使用率が高い: `intra_op_num_threads` と `allow_spinning` の設定を見直す。

## 8. 参照先

- Install: <https://onnxruntime.ai/docs/install/>
- Python API Summary: <https://onnxruntime.ai/docs/api/python/api_summary.html>
- Execution Providers: <https://onnxruntime.ai/docs/execution-providers/>
- CUDA EP: <https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html>
- Quantization: <https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html>

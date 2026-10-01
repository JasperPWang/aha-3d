<a id="install-kimodo-for-native-g1-robotics-motion"></a>

# 安装原生 G1 机器人运动的 Kimodo

[English](kimodo.md)

Level 3 Robotics 扩展 [Level 1 Static](../INSTALLATION_zh-CN.md#installation-levels)。Kimodo 用 G1 检查点和刚性连杆网格生成原生 G1 运动，也可用独立 SMPL-X 检查点生成近似人体动作。GVHMR/PMPose 属于 Level 2 人体重建。模型文件放在源码包之外。

<a id="shared-environment-and-pinned-code"></a>

## 共享环境与固定源码

从检出根目录选择 Level 3。选择器准备 [Static](../PI3X_GEOMETRY_REFERENCE_zh-CN.md#runtime)，并将[共享核心](core.md)加入 Pi3X 推理环境，命令见下方。

使用 Python 3.11 / Torch 2.7.1 cu128，Kimodo 固定 `1aece8c124d73d255ceff5086d983b844c9f4e94`。前提为兼容 NVIDIA 驱动、C++ 编译器（Ubuntu 用 `build-essential` 或 `gcc-12 g++-12`）。通用安装器处理 CMake 原生可执行文件并保护 Torch/Transformers 版本。Robotics 核心装 `trimesh`、`fast-simplification` 处理 G1 刚性连杆网格。批处理不需交互 Viser/SOMA extra。见[固定上游说明](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_virtual_env.md)。

```bash
bash tools/setup.sh --level robotics --plan
bash tools/setup.sh --level robotics
export KIMODO_ENV="$PWD/.runtime/pi3x-inference/venv"
source kimodo_blender/env.sh
```


<a id="authorized-g1-and-text-weights"></a>

## 获授权的 G1 和文本权重

用自己的账号获取 [Kimodo G1](https://huggingface.co/nvidia/Kimodo-G1-RP-v1) 和 [Llama 3 8B Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) 权限。通过 `hf auth login` 交互认证，token 放在检出目录和日志外，遵守各上游条款。在上方环境执行下方下载命令。

工具使用 `kimodo_blender/env.sh` 的 `KIMODO_ROOT`、`HF_HUB_CACHE`，把 G1 快照放到 `kimodo_blender/checkpoints/Kimodo-G1-RP-v1`，文本资产下载到配置的 Hugging Face 缓存。

| 模型 | 源部署快照版本 |
| --- | --- |
| `meta-llama/Meta-Llama-3-8B-Instruct` | `8afb486c1db24fe5011ec46dfbe5b5dccdb575c2` |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp` | `31474e395ada192e8ed1586db6be79fb3b70c9c0` |
| `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised` | `baa8ebf04a1c2500e61288e7dad65e8ae42601a7` |

下载器取当前版本，不强制上述历史固定值；声称复现前，在安装报告记录实际快照和检查点路径。成功导入 Python 不能解决模型访问/下载失败。

增加生成人体运动需下载 [Kimodo SMPL-X](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1)：`python kimodo_blender/download_models.py --model smplx`，或 `--model both` 下载两种。人体网格导出还需要单独授权的 Blender locked-head 人体资产，见 [Blender](blender.md)。原始 NPZ 导出器和上游可视化需要自己的 [SMPL-X 账号](https://smpl-x.is.tue.mpg.de/)获取 `SMPLX_NEUTRAL.npz`。上游可视化按[上游设置](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/docs/source/getting_started/installation_smpl.md)将移除发髻的 NPZ 放到 `$KIMODO_UPSTREAM/kimodo/assets/skeletons/smplx22/SMPLX_NEUTRAL.npz`。它不能替代 Blender 扩展人体数据。原生 G1 不使用这些 SMPL-X 资产。

```bash
python kimodo_blender/download_models.py --model g1
test -f "$CHECKPOINT_DIR/Kimodo-G1-RP-v1/config.yaml"
```


<a id="smoke-check-and-register"></a>

## 冒烟检查与注册

在本地 GPU 检查导入和实际 CUDA 执行，再运行原生 G1 选定模型检查，命令见下方。后者检查 CUDA、导入和 G1/Llama 配置访问，不加载权重或生成运动。人体用 `python kimodo_blender/check_runtime.py --model smplx`；两种都需用 `--model both`。

安装路线所需 Blender 后写入机器本地配置。G1 场景渲染和 skinning 字段可指向同一 Blender；生成 SMPL-X 人体需上文 Blender 4.5 蒙皮和扩展。

配置命令生成 `configs/runtimes/local.json`，配方选 `"runtime": "local"`。可选 `--threads N`、`--gpu N` 设置线程/GPU（默认全部核心、GPU 0）。每个 shell 保持相同 `KIMODO_ENV` 并 source env.sh。工具验证路径，不验证模型推理/蒙皮。Llama 3 8B 是最大显存消耗，在 96 GB 验证过，24 GB 未测试。按[场景示例](../../examples/README_zh-CN.md)使用新输出并验证完整结果。生成 SMPL-X 的 5 秒/24 fps 为 120 帧，蒙皮前重采样旋转。区分历史部署与新机器冒烟/全流水线结果。

```bash
python - <<'PY'
import torch, kimodo, motion_correction, transformers, peft
assert torch.cuda.is_available()
x = torch.randn(128, 128, device='cuda')
assert torch.isfinite(x @ x.T).all().item()
torch.cuda.synchronize()
print(torch.__version__, torch.cuda.get_device_name(0), 'KIMODO_IMPORT_CUDA_OK')
PY
```


```bash
python kimodo_blender/check_runtime.py --model g1
```


```bash
python tools/configure_runtime.py --python "$KIMODO_ENV/bin/python" \
  --blender "$RENDER_BLENDER" --skin-blender "$SKIN_BLENDER" \
  --kimodo "$KIMODO_UPSTREAM" --checkpoint "$CHECKPOINT_DIR/Kimodo-G1-RP-v1"
```

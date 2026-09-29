# aha-3d 设置

[English](SETUP.md)

在一台运行 Linux（Ubuntu 22.04/24.04 或 Windows WSL2）、配有 NVIDIA GPU 的工作站上安装和运行；请先阅读[运行时策略](../MACHINE.md)。开发和任务结束时的同步请使用[固定 Git 检出工作流](GIT_WORKFLOW.md)。

请保持完整的源代码检出目录，并以 editable 模式安装。Python wheel 本身不包含 Blender 库、技能或配置文件。[安装级别](INSTALLATION.md#installation-levels)定义所选运行时集合；只下载当前阶段所需的模型。

运行 `bash tools/setup.sh`，在安装前选择 Level 1、2 或 3。Level 1 Static 会在独立环境中安装 Pi3X、SAM3 和 Open3D 代码；请按[几何指南](PI3X_GEOMETRY_REFERENCE.md#runtime)安装 [Blender](install/blender.md)并获取 Pi3X/SAM3 检查点。Level 2 Human 还需要独立的 [PMPose 和 GVHMR 环境](install/human-motion.md)以及 [Blender SMPL-X 蒙皮](install/blender.md)。Level 3 Robotics 在 Static 上扩展 [Kimodo 及其原生 G1/文本依赖](install/kimodo.md)。SAM 3D Body 仍然只是可选的稀疏姿态指导。

## 1. 前置条件

- 支持 CUDA 12.8 的 NVIDIA 驱动（`nvidia-smi` 可以正常工作）。在 WSL2 中只安装 Windows NVIDIA 驱动，不要在 WSL 内安装 Linux 显示驱动。
- Python 3.11、git、FFmpeg、unzip、C++ 编译器（GCC 12）；GVHMR/PMPose 的原生扩展还需要 CUDA 12.8 toolkit。
- 为环境、检查点（几十 GB）、缓存和渲染结果预留足够磁盘空间。

## 2. 克隆并创建环境

```bash
git clone https://github.com/KevinXu02/aha-3d.git && cd aha-3d
```

交互式选择安装级别：

```bash
bash tools/setup.sh
```

非交互式安装时必须显式选择级别。下面的命令先查看 Robotics 方案，再执行安装：

```bash
bash tools/setup.sh --level robotics --plan
bash tools/setup.sh --level robotics
export KIMODO_ENV="$PWD/.runtime/pi3x-inference/venv"
source kimodo_blender/env.sh
```

[共享核心安装器](install/core.md)由级别选择器调用，并将 Kimodo 加入 Static 的 Pi3X Python 3.11 环境。设置 `PI3X_REFERENCE_ENV` 可使用其他独立环境。只有在需要可选稀疏姿态指导时才使用 `--with-sam3d`。GVHMR 和 PMPose 使用独立环境，详见 [GVHMR](install/gvhmr.md)和[人体运动](install/human-motion.md)。

共享核心安装器不会准备 SAM3 分割或 Open3D。级别选择器会为首次 `build_reference --video` 运行准备它们。同一个 Pi3X 代码包后续重建可以复用完整且与源匹配的语义掩码缓存。SAM3 分割不同于可选的 SAM 3D Body。

仅使用源工具（资产搜索、配方检查、单元测试）时，独立环境只需 Python 3.11+、NumPy、SciPy、Pillow 和 imageio-ffmpeg：在独立环境中执行 `python -m pip install -e '.[test]'`。`python tools/asset_index.py tree` 只需要 Python 标准库。

## 3. 每个 shell 的环境

每个 shell 在使用 `bash tools/indoor` 前都要 source `kimodo_blender/env.sh`。它会将检出目录的 `src/` 加入 `PYTHONPATH`，将 `KIMODO_ENV/bin` 加入 `PATH`（默认是检出根目录的 `.venv`），并将模型缓存放在 `.runtime/` 下。它会遵守已提供的路径。请将机器默认值（例如 `KIMODO_ENV`、`BLENDER_BIN` 和缓存位置）写入被忽略的 `kimodo_blender/env.local.sh`，`env.sh` 会优先加载该文件。

## 4. Blender 和模型文件

Blender 资产库使用 Blender 5.2.1 保存，请使用兼容版本。SMPL-X 蒙皮使用单独安装的 Blender 4.5 扩展及其获授权的 locked-head 人体资产。Blender 可执行文件不会随项目提供，详见 [Blender/SMPL-X](install/blender.md)。

Static 检查点请遵循 [Pi3X 指南](install/pi3x.md)。Level 3 还需要 [Kimodo G1 和文本模型](install/kimodo.md)。可选的稀疏姿态指导请遵循 [SAM 3D Body](install/sam3d-body.md)。[THIRD_PARTY.md](../THIRD_PARTY.md)列出了上游来源。Kimodo 上游固定在 `1aece8c124d73d255ceff5086d983b844c9f4e94`。Level 3 需要其 G1 模型及 Llama/LLM2Vec 依赖；生成的人体运动还需要 Kimodo SMPL-X 模型和 Blender SMPL-X 资产。请通过自己获授权的渠道获取这些内容。身份验证信息必须在源文件之外完成，不要复制其他用户的 token、凭据缓存或受限的人体/模型资产。

Pi3X 需要显式传入 `--upstream` 和 `--checkpoint` 路径。SAM 3D Body 需要 upstream、checkpoint 和 MHR 资产。可选的 SAM 3D Body 适配器在安装该功能时使用 Robotics 核心环境。可选的 SAM3 物体分割运行器见[物体分割](OBJECT_GENERATION.md)。

## 5. 配置运行时

对于运动配方，请用实际安装路径填写机器本地配置。原生 G1 需要将检查点指向 G1 目录；`--skin-blender` 可以与 `--blender` 指向同一个 Blender 可执行文件：

```bash
python tools/configure_runtime.py \
  --blender /path/to/blender-5.2/blender \
  --skin-blender /path/to/blender-5.2/blender \
  --kimodo /path/to/kimodo \
  --checkpoint /path/to/Kimodo-G1-RP-v1 \
  --threads 16 --gpu 0      # 可选；默认使用全部核心、GPU 0
```

辅助工具会验证可执行文件和源代码路径，并写入被忽略的 `configs/runtimes/local.json`（schema version 2：`python`、`blender`、`skin_blender`、`env_script`、`upstream`、`checkpoint`、`threads`、`gpu`）。配方选择 `"runtime": "local"`。[模板](../configs/runtimes/local.example.json)展示了这些字段；包含 `${...}` 的模板还不能直接运行。`NAME.local.json` 可以覆盖版本库中的 `NAME.json`，无需修改原文件。

`INDOOR_THREADS` 会覆盖配置中的线程数；已有的 `CUDA_VISIBLE_DEVICES` 会选择 GPU。每次调用都会记录 `INDOOR_RUN_ID`（未设置时生成 `local-<host>-<pid>-<timestamp>`，并由子进程继承），用于溯源。

## 6. 检查、测试并运行首个场景

Robotics：

```bash
python kimodo_blender/check_runtime.py --model g1
python -m unittest discover -s tests -v
```

`check_runtime.py --model g1` 会检查 CUDA 执行、Kimodo 导入和原生 G1 模型访问，但不会打印 token。Kimodo 生成人体运动时使用 `--model smplx`。人物重建使用自己的[验证命令](install/human-motion.md#verify-before-a-new-run)。Static 参考验证见[几何指南](PI3X_GEOMETRY_REFERENCE.md#runtime)。然后继续阅读[相关示例](../examples/README.md)和[项目技能](../TOOLS_AND_SKILLS.md)。更深层技术经验中的历史场景 ID 和输出路径只是示例，不是此代码包附带的文件。

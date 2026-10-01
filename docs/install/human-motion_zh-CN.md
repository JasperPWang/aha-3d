<a id="install-the-complete-source-motion-stack"></a>

# 安装完整源运动栈

[English](human-motion.md)

新安装 Level 2 时，先运行 `bash tools/setup.sh` 选择 Human（脚本使用 `--level human`）。选择器准备 Static 和 SAM3 视频解码；下面的 GVHMR、PMPose、Blender 与模型步骤完成 Human 安装。

结合 [GVHMR 安装](gvhmr.md)和[世界流水线命令](../WORLD_POSTOPT.md)使用。`tools/gvhmr/world_backend/` 含作者的跟踪、密集相机、适配、v2 优化和评估辅助工具。不需要 PromptHMR 检出、权重或环境。部分官方 PyTorch3D v0.4.0 旋转工具附 BSD 许可证提供，以保留历史数值行为；这不改变 GVHMR 所需的已安装 PyTorch3D 版本。可选 `--prompt-hmr` 仅为旧实验覆盖后端。

<a id="evidence-and-installation-boundary"></a>

## 证据与安装边界

此指南转录作者 2026-09-17 的 `world-postopt/INSTALL.md` 并检查已安装运行时。基线是 Python 3.11.14、Torch 2.7.1+cu128、torchvision 0.22.1+cu128、96 GB RTX PRO 6000 Blackwell、驱动 580.159、CUDA toolkit 12.8 和 GCC 12。编译扩展使用硬件对应架构：下方 12.0 是 Blackwell，Ada（RTX 4090 / RTX 6000 Ada）用 8.9。24 GB 是目标但未测试；打包期间未重跑干净安装。

Human 另有 GVHMR/密集 Pi3X/v2 和 PMPose 两个环境。Static SAM3 环境加 PyAV 后提供默认跟踪器。Robotics 核心独立，仅生成新动作需要，不能降低其 PyAV。已有环境/模型可保留，显式传路径或用被忽略的本地配置。在单 GPU 本地工作站安装、编译、测试和推理，遵守[机器策略](../../MACHINE_zh-CN.md)。

<a id="code-locations-and-revisions"></a>

## 代码位置与版本

从仓库根目录设置下方变量。

| 库 | 来源及记录身份 |
| --- | --- |
| GVHMR BEDLAM2 | [上游](https://github.com/mkocabas/GVHMR_BEDLAM2)，`cac2d9dacc6b4b6f145ca02c2e6e616719fff916` |
| Pi3/Pi3X | [上游](https://github.com/yyfz/Pi3)，`9fa3ddb3f8d53041f8b2738df404f62223bbaa7b` |
| SAMURAI（可选替代） | [上游](https://github.com/yangchris11/samurai)，2026-09-13 的安装源码副本，原提交未记录 |
| BBoxMaskPose/PMPose | [上游](https://github.com/MiraPurkrabek/BBoxMaskPose)，包 2.0.0，内含 MMPose 1.3.1，2026-09-17 获取；原提交未记录；[冒烟验证版本](https://github.com/MiraPurkrabek/BBoxMaskPose/commit/49a070a6f8396147323b1c4959474077dbe2ce8e) 为 `49a070a6f8396147323b1c4959474077dbe2ce8e` |

原 BBoxMaskPose 部署提交未知，限制可复现性。新安装使用已记录 PMPose 冒烟版本，不证明原部署相同。保留工作安装并记录本次验证版本。克隆命令仅用于新的未使用目标。

只有显式 `--tracker samurai` 路线，才在克隆到 `$R2S/third_party/samurai` 前选择并记录已审查 SAMURAI 版本；历史副本未记提交。

```bash
export R2S="$PWD"
export GVHMR_ROOT="$R2S/.runtime/gvhmr-bedlam2"
export GVHMR_PYTHON="$GVHMR_ROOT/venv/bin/python"
export BMP_ROOT="$R2S/.runtime/bmp/src"
export PMPOSE_PYTHON="$R2S/.runtime/bmp/venv/bin/python"
export PI3X_UPSTREAM="$R2S/external/Pi3"
```


```bash
# Only in a new, unused destination.
export BMP_REVISION="${BMP_REVISION:-49a070a6f8396147323b1c4959474077dbe2ce8e}"
git clone https://github.com/MiraPurkrabek/BBoxMaskPose "$BMP_ROOT"
git -C "$BMP_ROOT" checkout --detach "$BMP_REVISION"
```


<a id="gvhmr-and-dense-cameras"></a>

## GVHMR 和密集相机

先按 [GVHMR 方案](gvhmr.md)安装专用环境，包括 SMPL-X 和 PyTorch3D，保持 NumPy 1.26.4 与 PyAV 12.3.0。作者 CUDA 编译使用 toolkit 12.8。再加入下方小型跟踪/相机依赖。

默认跟踪器使用加 PyAV 的 Static SAM3 运行时。可选 SAMURAI 导入自己的 `sam2` 并用 PyAV 解码，不需上游 Decord/JPEG 目录路线或旧 `runs/.../python-dependencies`、`runs/.../samurai/deps`。`--samurai-deps` 仍供显式路线使用。

按 [Pi3X 安装](pi3x.md)安装上方 Pi3 版本。密集相机辅助工具在 GVHMR 环境运行，将 `--pi3` 加入导入路径并加载显式 safetensors。不要把 Pi3 旧 Torch 2.5.1 要求覆盖到此环境。正常房间参考继续使用共享核心解释器。

```bash
"$GVHMR_PYTHON" -m pip install iopath portalocker loguru safetensors
```


<a id="separate-pmpose-environment"></a>

## 独立 PMPose 环境

已安装 PMPose 使用同一 Python/Torch 组合并加 OpenMMLab。使用新环境；下方不是旧环境升级方案。需编译版 MMCV，`mmcv-lite` 不提供内核。

已部署环境对 MMDetection 有本地兼容修改：`mmdet/__init__.py` 的 `mmcv_maximum_version = '2.3.0'` 允许 MMCV 2.2.0，原安装记录未包含。对于**新 PMPose 环境**中的准确 3.3.0/2.2.0 组合，下方带断言修改复现该边界，不证明通用 OpenMMLab 兼容性；修改后验证真实推理。

BBoxMaskPose 副本的 `mmpose/__init__.py` 允许 MMCV 到 2.3.0，需检查所选版本。不要在内含包上另外 pip 安装 MMPose。项目 worker 在 `$BMP_ROOT/mmpose` 工作以解析相对 metainfo，注册 `mmpretrain`，加载时允许可信检查点 NumPy 数据，将 23 个关节的前 17 个导出为 COCO-17；必须使用真实、已审查跟踪掩码。

若继承旧 Conda `libstdc++` 导致缺少 `GLIBCXX_3.4.32`，用本机兼容系统库设置 `PMPOSE_LD_PRELOAD`；记录机器用 `/usr/lib/x86_64-linux-gnu/libstdc++.so.6`。worker 仅对子进程应用，不写死到可移植源码。

```bash
python3.11 -m venv "$R2S/.runtime/bmp/venv"
"$PMPOSE_PYTHON" -m pip install --upgrade pip setuptools wheel ninja
"$PMPOSE_PYTHON" -m pip install torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu128
"$PMPOSE_PYTHON" -m pip install mmengine==0.10.7 numpy==1.26.4 opencv-python==4.10.0.84
export CUDA_HOME=/usr/local/cuda-12.8
export CC=/usr/bin/gcc-12 CXX=/usr/bin/g++-12
MAX_JOBS=6 FORCE_CUDA=1 MMCV_WITH_OPS=1 TORCH_CUDA_ARCH_LIST=12.0 \
  "$PMPOSE_PYTHON" -m pip install --no-build-isolation --no-binary=mmcv mmcv==2.2.0
"$PMPOSE_PYTHON" -m pip install mmdet==3.3.0 mmpretrain==1.2.0 \
  xtcocotools pycocotools hydra-core einops mat4py importlib_metadata \
  json_tricks munkres sparsemax==0.1.9 transformers==4.35.2 tokenizers==0.15.2
"$PMPOSE_PYTHON" -m pip install --no-deps -e "$BMP_ROOT"
```


```bash
"$PMPOSE_PYTHON" - <<'PY'
from importlib.metadata import distribution, version
assert version('mmdet') == '3.3.0' and version('mmcv') == '2.2.0'
p = distribution('mmdet').locate_file('mmdet/__init__.py')
s = p.read_text()
old = "mmcv_maximum_version = '2.2.0'"
new = "mmcv_maximum_version = '2.3.0'"
assert s.count(old) == 1 or s.count(new) == 1, 'Unexpected mmdet source; inspect manually'
if old in s:
    p.write_text(s.replace(old, new))
PY
```


<a id="external-weights-and-body-assets"></a>

## 外部权重和人体资产

用自己的授权下载，不把权重/人体模型放入 Git。包装器预期：

| 相对仓库位置 | 来源 |
| --- | --- |
| `.runtime/gvhmr-bedlam2/inputs/checkpoints/gvhmr/gvhmr_b1b2.ckpt` | BEDLAM2，见 [GVHMR 安装](gvhmr.md) |
| `.runtime/gvhmr-bedlam2/inputs/checkpoints/hmr2/epoch=10-step=25000.ckpt` | GVHMR 图像特征权重 |
| `.runtime/gvhmr-bedlam2/inputs/checkpoints/body_models/smplx/SMPLX_NEUTRAL.npz` | 获授权 [SMPL-X](https://smpl-x.is.tue.mpg.de/) |
| `.runtime/gvhmr-bedlam2/inputs/checkpoints/body_models/smpl/SMPL_NEUTRAL.pkl` | GVHMR 渲染所需获授权 [SMPL](https://smpl.is.tue.mpg.de/) |
| `.runtime/pi3x/checkpoint/model.safetensors` | [Pi3X](https://huggingface.co/yyfz233/Pi3X)，模型版本 `bb1deea4d7423de5b30691739cb451a3f57dc1d5` |
| `.runtime/samurai-checkpoints/sam2.1_hiera_base_plus.pt`（可选） | [SAM2.1 检查点](https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt) |
| `.runtime/bmp/checkpoints/PMPose-h-1.0.0.pth` | [BBoxMaskPose 模型库](https://huggingface.co/vrg-prague/BBoxMaskPose/tree/main/PMPose) |

显式 `--pose-detector vitpose` 需 ViTPose 权重。YOLO/DPVO 不是 SAM3/Pi3X 默认路线的跟踪/相机来源，但部分 GVHMR 导入仍需支持包。人体使用 `use_pca=False`、`flat_hand_mean=True`、`num_betas=10`。

<a id="verify-before-a-new-run"></a>

## 新运行前验证

在工作站仓库根目录运行下方导入检查。仅当环境需该配置绕过时，为 PMPose 检查加 `LD_PRELOAD="$PMPOSE_LD_PRELOAD"`。导入不测试 GPU 内核或模型质量。按[流水线](../WORLD_POSTOPT.md)分配新认领运行，准备完整图、执行，检查跟踪身份、检测器消费、代表性源叠加和全视频时间。已有实验快照保留原源码。

```bash
"$GVHMR_PYTHON" -c 'import torch, pytorch3d, smplx, av, iopath, portalocker, loguru, safetensors; print(torch.__version__, torch.cuda.get_device_capability())'
PYTHONPATH="$PI3X_UPSTREAM" "$GVHMR_PYTHON" -c 'from pi3.models.pi3x import Pi3X'
(cd "$BMP_ROOT/mmpose" && PYTHONPATH="$BMP_ROOT" \
  "$PMPOSE_PYTHON" -c 'import mmcv, mmpose, mmpretrain; from pmpose import PMPose; print(mmcv.__version__, mmpose.__version__)')
"$GVHMR_PYTHON" tools/gvhmr/world_pipeline.py prepare --help
```


<a id="sam3-tracking-with-pmpose-current-default"></a>

## SAM3 跟踪与 PMPose（当前默认）

通过 `SAM3_ROOT`、`SAM3_PYTHON`、`SAM3_CHECKPOINT` 复用 SAM3；主图在该解释器跟踪，在 `PMPOSE_PYTHON` 运行 PMPose。只有显式 `--tracker samurai` 对照需 SAMURAI。SAM3 在本地 GPU 运行。[参考安装器](../PI3X_GEOMETRY_REFERENCE_zh-CN.md#runtime)检查图像 API，源人物跟踪还需 PyAV 完整视频解码；按下方命令加入同一独立 SAM3 运行时。

按前文独立安装/检查 PMPose、GVHMR。[最终场景](blender.md)仍需 Blender 和 SMPL-X 蒙皮。

原 PMPose 冒烟试验使用 BBoxMaskPose `49a070a6f8396147323b1c4959474077dbe2ce8e`、具真实 CUDA NMS 的 MMCV 2.2.0，按原 bbox 策略和 SAM3 掩码完成 260 帧 PMPose-h 推理。额外包用于内含 MMPose/MMPretrain 兼容；不要将这些版本固定加入 Kimodo 环境。新环境 bin 加入 PATH，让 MMCV 找到 ninja 并行编译。

运行时成功与目标准确性独立；clip32 试验在重遮挡下仍有干扰人物污染。这些环境/检测器检查不构成三维验收。

```bash
export SAM3_ROOT="$PWD/external/sam3"
export SAM3_PYTHON="$PWD/.runtime/sam3-segmentation/venv/bin/python"
export SAM3_CHECKPOINT="$PWD/.runtime/sam3-segmentation/checkpoints/sam3.pt"
"$SAM3_PYTHON" -m pip install av==12.3.0
"$SAM3_PYTHON" -c 'import av; from sam3.model_builder import build_sam3_video_model; print("SAM3_TRACKING_IMPORT_OK")'
```

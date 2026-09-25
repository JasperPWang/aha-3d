#!/usr/bin/env bash
set -euo pipefail
SAM3_PROJECT_ROOT="${INDOOR_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)}"
cd "$SAM3_PROJECT_ROOT"
source kimodo_blender/env.sh
SAM3_RUNTIME="$SAM3_PROJECT_ROOT/.runtime/sam3-segmentation"
export PIP_CACHE_DIR="$SAM3_RUNTIME/pip-cache"
export HF_HUB_CACHE="$SAM3_RUNTIME/hf-cache"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$SAM3_RUNTIME"
if [[ ! -d external/sam3/.git ]]; then
  git clone --depth 1 https://github.com/facebookresearch/sam3.git external/sam3
fi
git -C external/sam3 rev-parse HEAD > "$SAM3_RUNTIME/source_revision.txt"
if [[ ! -f "$SAM3_RUNTIME/venv/bin/python" ]]; then
  "$KIMODO_ENV/bin/python" -m venv --system-site-packages "$SAM3_RUNTIME/venv"
fi
"$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps 'numpy==1.26.4' 'timm==1.0.20' 'ftfy==6.1.1' 'iopath==0.1.10' 'decord==0.6.0' 'setuptools<81'
# Keep the tested base Torch/cu128: an unconstrained torchvision install otherwise
# selects a newer Torch/CUDA stack inside this venv. Remove only local overrides.
if [[ -d "$SAM3_RUNTIME/venv/lib/python3.11/site-packages/torch" ]]; then
  "$SAM3_RUNTIME/venv/bin/python" -m pip uninstall -y torch torchvision triton
fi
"$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
"$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps portalocker wcwidth pycocotools 'opencv-python-headless==4.11.0.86' psutil 'einops>=0.8'
"$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps --no-build-isolation -e external/sam3
"$SAM3_RUNTIME/venv/bin/python" tools/object_pilot/segmentation/prepare_runtime.py --runtime "$SAM3_RUNTIME"

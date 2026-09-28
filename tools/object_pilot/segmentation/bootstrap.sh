#!/usr/bin/env bash
set -euo pipefail
SAM3_PROJECT_ROOT="${INDOOR_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)}"
SAM3_RUNTIME="${SAM3_RUNTIME:-$SAM3_PROJECT_ROOT/.runtime/sam3-segmentation}"
SAM3_PYTHON=python3.11
STANDALONE=false
NO_CHECKPOINT=false
while (($#)); do
  case "$1" in
    --runtime) SAM3_RUNTIME="${2:?--runtime requires a path}"; shift 2 ;;
    --python) SAM3_PYTHON="${2:?--python requires an executable}"; shift 2 ;;
    --standalone) STANDALONE=true; shift ;;
    --no-checkpoint) NO_CHECKPOINT=true; shift ;;
    -h|--help)
      printf '%s\n' 'Usage: bash tools/object_pilot/segmentation/bootstrap.sh [--standalone] [--no-checkpoint] [--runtime PATH] [--python python3.11]' \
        'Standalone installs SAM3 in its own venv; default retains the historical inherited-core pilot setup. Checkpoint download needs authorized access.'
      exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
cd "$SAM3_PROJECT_ROOT"
if ! "$STANDALONE"; then
  source kimodo_blender/env.sh
fi
export PIP_CACHE_DIR="$SAM3_RUNTIME/pip-cache"
export HF_HUB_CACHE="$SAM3_RUNTIME/hf-cache"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$SAM3_RUNTIME"
SAM3_REVISION=660a5e9e1b8b4c02c0ad97229b88a09a6e4ff5b7
if [[ ! -e external/sam3 ]]; then
  git clone https://github.com/facebookresearch/sam3.git external/sam3
  git -C external/sam3 checkout --detach "$SAM3_REVISION"
elif [[ ! -d external/sam3/.git ]] || \
     [[ "$(git -C external/sam3 rev-parse HEAD)" != "$SAM3_REVISION" ]] || \
     [[ -n "$(git -C external/sam3 status --porcelain --untracked-files=no)" ]]; then
  printf '%s\n' 'Existing SAM3 checkout must be clean and at the documented pin: external/sam3' >&2
  exit 2
fi
git -C external/sam3 rev-parse HEAD > "$SAM3_RUNTIME/source_revision.txt"
if [[ ! -f "$SAM3_RUNTIME/venv/bin/python" ]]; then
  if "$STANDALONE"; then
    command -v "$SAM3_PYTHON" >/dev/null
    "$SAM3_PYTHON" -m venv "$SAM3_RUNTIME/venv"
  else
    "$KIMODO_ENV/bin/python" -m venv --system-site-packages "$SAM3_RUNTIME/venv"
  fi
fi
if "$STANDALONE"; then
  if grep -qi '^include-system-site-packages = true' "$SAM3_RUNTIME/venv/pyvenv.cfg"; then
    printf '%s\n' 'Standalone SAM3 needs a private venv; select a new --runtime path rather than replacing an inherited environment.' >&2
    exit 2
  fi
  "$SAM3_RUNTIME/venv/bin/python" -m pip install --upgrade pip
  "$SAM3_RUNTIME/venv/bin/python" -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
  "$SAM3_RUNTIME/venv/bin/python" -m pip install -c "$SAM3_PROJECT_ROOT/constraints-core.txt" \
    'numpy==1.26.4' 'timm==1.0.20' 'ftfy==6.1.1' 'iopath==0.1.10' \
    'decord==0.6.0' 'setuptools<81' 'opencv-python-headless==4.11.0.86' \
    huggingface_hub safetensors pycocotools psutil einops -e external/sam3
  "$SAM3_RUNTIME/venv/bin/python" -m pip check
  "$SAM3_RUNTIME/venv/bin/python" -c 'from sam3.model_builder import build_sam3_image_model; from sam3.model.sam3_image_processor import Sam3Processor; print("SAM3_IMAGE_API_IMPORT_OK")'
else
  "$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps 'numpy==1.26.4' 'timm==1.0.20' 'ftfy==6.1.1' 'iopath==0.1.10' 'decord==0.6.0' 'setuptools<81'
  # Preserve the pilot's inherited Torch/cu128 pair.
  if [[ -d "$SAM3_RUNTIME/venv/lib/python3.11/site-packages/torch" ]]; then
    "$SAM3_RUNTIME/venv/bin/python" -m pip uninstall -y torch torchvision triton
  fi
  "$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
  "$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps portalocker wcwidth pycocotools 'opencv-python-headless==4.11.0.86' psutil 'einops>=0.8'
  "$SAM3_RUNTIME/venv/bin/python" -m pip install --no-deps --no-build-isolation -e external/sam3
fi
if ! "$NO_CHECKPOINT"; then
  "$SAM3_RUNTIME/venv/bin/python" tools/object_pilot/segmentation/prepare_runtime.py --runtime "$SAM3_RUNTIME"
fi

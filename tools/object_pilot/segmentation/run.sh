#!/usr/bin/env bash
set -euo pipefail
cd "${INDOOR_PROJECT_ROOT:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)}"
source kimodo_blender/env.sh
export PYTHONDONTWRITEBYTECODE=1
export SAM3_RUNTIME="$PWD/.runtime/sam3-segmentation"
export HF_HUB_CACHE="$SAM3_RUNTIME/hf-cache"
export TORCH_HOME="$SAM3_RUNTIME/torch-cache"
export TRITON_CACHE_DIR="$SAM3_RUNTIME/triton-cache"
export PYTHONUNBUFFERED=1
"$SAM3_RUNTIME/venv/bin/python" tools/object_pilot/segmentation/run.py "$@"

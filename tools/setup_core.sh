#!/usr/bin/env bash
# Shared Kimodo/Pi3X environment, or Pi3X-only inference for fresh references.
set -euo pipefail
BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CORE_ENV="${KIMODO_ENV:-$BUNDLE_ROOT/.venv}"
CORE_PYTHON=python3.11
PLAN=false
WITH_SAM3D=false
PI3X_ONLY=false
while (($#)); do
  case "$1" in
    --env) CORE_ENV="${2:?--env requires a path}"; shift 2 ;;
    --python) CORE_PYTHON="${2:?--python requires an executable}"; shift 2 ;;
    --plan) PLAN=true; shift ;;
    --with-sam3d) WITH_SAM3D=true; shift ;;
    --pi3x-only) PI3X_ONLY=true; shift ;;
    -h|--help)
      printf '%s\n' 'Usage: bash tools/setup_core.sh [--env PATH] [--python python3.11] [--with-sam3d | --pi3x-only] [--plan]' \
        'Low-level component installer used by tools/setup.sh after level selection. --pi3x-only skips Kimodo. --with-sam3d adds optional sparse pose guidance. No model weights are downloaded.'
      exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if "$PI3X_ONLY" && "$WITH_SAM3D"; then
  printf '%s\n' '--pi3x-only and --with-sam3d cannot be combined' >&2
  exit 2
fi
export KIMODO_ENV="$CORE_ENV"
export KIMODO_UPSTREAM="$BUNDLE_ROOT/kimodo_blender/upstream"
PI3X_UPSTREAM="$BUNDLE_ROOT/external/Pi3"
SAM_UPSTREAM="$BUNDLE_ROOT/external/sam-3d-body"
DINO_UPSTREAM="$BUNDLE_ROOT/external/dinov3"
if "$PLAN"; then
  printf 'Core environment: %s\nPython: %s\n' "$CORE_ENV" "$CORE_PYTHON"
  if "$PI3X_ONLY"; then
    printf '%s\n' 'Torch 2.7.1 / torchvision 0.22.1 (cu128).'
    printf '%s\n' 'Install Pi3X inference dependencies and the pinned Pi3X checkout; skip Kimodo and SAM 3D Body.'
  else
    printf '%s\n' 'Torch 2.7.1 / torchvision 0.22.1 (cu128); Transformers 5.1.0.'
    printf '%s\n' 'Install requirements-core.txt, pinned Kimodo, source tools and Pi3X.'
  fi
  printf '%s\n' 'Weights are acquired separately. H3 and Blender Python are not installed here.'
  if "$WITH_SAM3D"; then
    printf '%s\n' 'Also install pinned SAM 3D Body and DINOv3 source checkouts and SAM-only packages.'
  fi
  exit 0
fi
if "$PI3X_ONLY"; then
  case "${AHA3D_SETUP_LEVEL:-}" in
    static|human|robotics) ;;
    *) printf '%s\n' 'Select a level first with bash tools/setup.sh; direct component installation is disabled.' >&2; exit 2 ;;
  esac
elif [[ "${AHA3D_SETUP_LEVEL:-}" != robotics ]]; then
  printf '%s\n' 'Select Level 3 Robotics with bash tools/setup.sh before installing Kimodo.' >&2
  exit 2
fi
if [[ ! -x "$CORE_ENV/bin/python" ]]; then
  command -v "$CORE_PYTHON" >/dev/null
  "$CORE_PYTHON" -m venv "$CORE_ENV"
fi
"$CORE_ENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "The core environment requires Python 3.11"'
clone_pin() {
  local url="$1" destination="$2" revision="$3"
  if [[ ! -e "$destination" ]]; then
    git clone "$url" "$destination"
    git -C "$destination" checkout --detach "$revision"
  elif [[ ! -d "$destination/.git" ]] || \
       [[ "$(git -C "$destination" rev-parse HEAD)" != "$revision" ]] || \
       [[ -n "$(git -C "$destination" status --porcelain --untracked-files=no)" ]]; then
    printf 'Existing checkout must be clean and at the documented pin: %s\n' "$destination" >&2
    exit 2
  fi
}
mkdir -p "$BUNDLE_ROOT/external" "$BUNDLE_ROOT/kimodo_blender"
if ! "$PI3X_ONLY"; then
  clone_pin https://github.com/nv-tlabs/kimodo.git "$KIMODO_UPSTREAM" 1aece8c124d73d255ceff5086d983b844c9f4e94
fi
clone_pin https://github.com/yyfz/Pi3.git "$PI3X_UPSTREAM" 9fa3ddb3f8d53041f8b2738df404f62223bbaa7b
if "$WITH_SAM3D"; then
  clone_pin https://github.com/facebookresearch/sam-3d-body.git "$SAM_UPSTREAM" b5c765a0d89d789985e186d396315e7590887b94
  clone_pin https://github.com/facebookresearch/dinov3.git "$DINO_UPSTREAM" 6876159a11b4df116f30f667f8c9888617df0751
fi
source "$BUNDLE_ROOT/kimodo_blender/env.sh"
export KIMODO_ENV="$CORE_ENV" PATH="$CORE_ENV/bin:$PATH"
CORE_BIN="$CORE_ENV/bin/python"
"$CORE_BIN" -m pip install --upgrade pip
"$CORE_BIN" -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
if "$PI3X_ONLY"; then
  "$CORE_BIN" -m pip install -c "$BUNDLE_ROOT/constraints-core.txt" \
    'numpy==1.26.4' pillow opencv-python-headless plyfile huggingface_hub safetensors einops
else
  "$CORE_BIN" -m pip install -r "$BUNDLE_ROOT/requirements-core.txt"
fi
if "$WITH_SAM3D"; then
  "$CORE_BIN" -m pip install -c "$BUNDLE_ROOT/constraints-core.txt" \
    pytorch-lightning timm yacs==0.1.8 roma==1.6.1 pyrootutils==1.0.4 \
    dill loguru rich pandas scikit-image \
    webdataset==1.0.2 braceexpand==0.1.7 termcolor==3.1.0
fi
if "$PI3X_ONLY"; then
  "$CORE_BIN" -m pip install -c "$BUNDLE_ROOT/constraints-core.txt" -e "$BUNDLE_ROOT"
else
  KIMODO_CMAKE_BIN=$("$CORE_BIN" -c 'import cmake; print(cmake.CMAKE_BIN_DIR)')
  export PATH="$KIMODO_CMAKE_BIN:$PATH" CMAKE_GENERATOR=Ninja
  export CMAKE_BUILD_PARALLEL_LEVEL="${INDOOR_THREADS:-$(nproc 2>/dev/null || echo 4)}"
  "$CORE_BIN" -m pip install -c "$BUNDLE_ROOT/constraints-core.txt" -e "$KIMODO_UPSTREAM" -e "$BUNDLE_ROOT[test]"
fi
"$CORE_BIN" -m pip check
if "$PI3X_ONLY"; then
  XFORMERS_DISABLED=1 PYTHONPATH="$PI3X_UPSTREAM:$BUNDLE_ROOT/src" "$CORE_BIN" - <<'PY'
import torch, torchvision
from pi3.models.pi3x import Pi3X
print('PI3X_IMPORT_OK', torch.__version__, torchvision.__version__)
PY
else
  MOMENTUM_ENABLED=0 XFORMERS_DISABLED=1 \
    PYTHONPATH="$PI3X_UPSTREAM:$BUNDLE_ROOT/src" "$CORE_BIN" - <<'PY'
import kimodo, torch, torchvision
from pi3.models.pi3x import Pi3X
print('SHARED_CORE_IMPORT_OK', torch.__version__, torchvision.__version__)
PY
fi
if "$WITH_SAM3D"; then
  MOMENTUM_ENABLED=0 PYTHONPATH="$SAM_UPSTREAM:$BUNDLE_ROOT/src" "$CORE_BIN" - <<'PY'
from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
print('SAM3D_IMPORT_OK')
PY
fi
printf 'Setup completed in %s; see docs/install/pi3x.md for model acquisition.\n' "$CORE_ENV"

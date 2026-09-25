#!/usr/bin/env bash
# One environment for Kimodo, Pi3X, SAM 3D Body and source tools; no model downloads.
set -euo pipefail
BUNDLE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
CORE_ENV="${KIMODO_ENV:-$BUNDLE_ROOT/.venv}"
CORE_PYTHON=python3.11
PLAN=false
while (($#)); do
  case "$1" in
    --env) CORE_ENV="${2:?--env requires a path}"; shift 2 ;;
    --python) CORE_PYTHON="${2:?--python requires an executable}"; shift 2 ;;
    --plan) PLAN=true; shift ;;
    -h|--help)
      printf '%s\n' 'Usage: bash tools/setup_core.sh [--env PATH] [--python python3.11] [--plan]' \
        'Installs core packages and pinned source checkouts. Does not download model weights or install H3.'
      exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
export KIMODO_ENV="$CORE_ENV"
export KIMODO_UPSTREAM="$BUNDLE_ROOT/kimodo_blender/upstream"
PI3X_UPSTREAM="$BUNDLE_ROOT/external/Pi3"
SAM_UPSTREAM="$BUNDLE_ROOT/external/sam-3d-body"
DINO_UPSTREAM="$BUNDLE_ROOT/external/dinov3"
if "$PLAN"; then
  printf 'Core environment: %s\nPython: %s\n' "$CORE_ENV" "$CORE_PYTHON"
  printf '%s\n' 'Torch 2.7.1 / torchvision 0.22.1 (cu128); Transformers 5.1.0.' \
    'Install requirements-core.txt, pinned Kimodo, source tools, Pi3X, SAM 3D Body and DINOv3.' \
    'Weights are acquired separately. H3 and Blender Python are not installed here.'
  exit 0
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
clone_pin https://github.com/nv-tlabs/kimodo.git "$KIMODO_UPSTREAM" 1aece8c124d73d255ceff5086d983b844c9f4e94
clone_pin https://github.com/yyfz/Pi3.git "$PI3X_UPSTREAM" 9fa3ddb3f8d53041f8b2738df404f62223bbaa7b
clone_pin https://github.com/facebookresearch/sam-3d-body.git "$SAM_UPSTREAM" b5c765a0d89d789985e186d396315e7590887b94
clone_pin https://github.com/facebookresearch/dinov3.git "$DINO_UPSTREAM" 6876159a11b4df116f30f667f8c9888617df0751
source "$BUNDLE_ROOT/kimodo_blender/env.sh"
python -m pip install --upgrade pip
python -m pip install torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r "$BUNDLE_ROOT/requirements-core.txt"
KIMODO_CMAKE_BIN=$(python -c 'import cmake; print(cmake.CMAKE_BIN_DIR)')
export PATH="$KIMODO_CMAKE_BIN:$PATH" CMAKE_GENERATOR=Ninja
export CMAKE_BUILD_PARALLEL_LEVEL="${INDOOR_THREADS:-$(nproc 2>/dev/null || echo 4)}"
python -m pip install -c "$BUNDLE_ROOT/constraints-core.txt" -e "$KIMODO_UPSTREAM" -e "$BUNDLE_ROOT[test]"
python -m pip check
MOMENTUM_ENABLED=0 XFORMERS_DISABLED=1 \
  PYTHONPATH="$PI3X_UPSTREAM:$SAM_UPSTREAM:$BUNDLE_ROOT/src" python - <<'PY'
import kimodo, torch, torchvision
from pi3.models.pi3x import Pi3X
from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
print('SHARED_CORE_IMPORT_OK', torch.__version__, torchvision.__version__)
PY
printf 'Core setup completed. Set KIMODO_ENV=%s in future jobs; see docs/install/core.md for model acquisition.\n' "$CORE_ENV"

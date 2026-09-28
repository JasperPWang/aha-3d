#!/usr/bin/env bash
# Install the Python runtimes for a new-video static scene reference.
set -euo pipefail
REFERENCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
REFERENCE_PYTHON=python3.11
PI3X_ENV="${PI3X_REFERENCE_ENV:-$REFERENCE_ROOT/.runtime/pi3x-inference/venv}"
MESH_ENV="${PI3X_MESH_ENV:-$REFERENCE_ROOT/.runtime/pi3x-mesh/venv}"
SAM3_ENV_ROOT="${SAM3_RUNTIME:-$REFERENCE_ROOT/.runtime/sam3-segmentation}"
PLAN=false
while (($#)); do
  case "$1" in
    --python) REFERENCE_PYTHON="${2:?--python requires an executable}"; shift 2 ;;
    --pi3x-env) PI3X_ENV="${2:?--pi3x-env requires a path}"; shift 2 ;;
    --mesh-env) MESH_ENV="${2:?--mesh-env requires a path}"; shift 2 ;;
    --sam3-runtime) SAM3_ENV_ROOT="${2:?--sam3-runtime requires a path}"; shift 2 ;;
    --plan) PLAN=true; shift ;;
    -h|--help)
      printf '%s\n' 'Usage: bash tools/setup_reference.sh [--python python3.11] [--pi3x-env PATH] [--mesh-env PATH] [--sam3-runtime PATH] [--plan]' \
        'Low-level component installer used by tools/setup.sh after level selection. Blender is required separately.'
      exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done
if [[ "$PI3X_ENV" == "$MESH_ENV" || "$PI3X_ENV" == "$SAM3_ENV_ROOT/venv" || "$MESH_ENV" == "$SAM3_ENV_ROOT/venv" ]]; then
  printf '%s\n' 'Pi3X, mesh and SAM3 must have distinct environments' >&2
  exit 2
fi
if "$PLAN"; then
  printf 'Static level, first new-video reference (Python: %s):\n' "$REFERENCE_PYTHON"
  printf 'Pi3X inference: %s (pinned Pi3X, Torch/CUDA and inference dependencies)\n' "$PI3X_ENV"
  printf 'SAM3 segmentation: %s (pinned SAM3, standalone Torch/CUDA and image API)\n' "$SAM3_ENV_ROOT"
  printf 'Open3D mesh and reference views: %s (reference extra)\n' "$MESH_ENV"
  printf '%s\n' 'Pi3X and SAM3 checkpoints are separate downloads. Editable static scenes also require Blender; Human and Robotics levels add their own runtimes.'
  exit 0
fi
case "${AHA3D_SETUP_LEVEL:-}" in
  static|human|robotics) ;;
  *) printf '%s\n' 'Select a level first with bash tools/setup.sh; direct component installation is disabled.' >&2; exit 2 ;;
esac
cd "$REFERENCE_ROOT"
bash tools/setup_core.sh --pi3x-only --env "$PI3X_ENV" --python "$REFERENCE_PYTHON"
INDOOR_PROJECT_ROOT="$REFERENCE_ROOT" bash tools/object_pilot/segmentation/bootstrap.sh --standalone --no-checkpoint \
  --runtime "$SAM3_ENV_ROOT" --python "$REFERENCE_PYTHON"
if [[ ! -x "$MESH_ENV/bin/python" ]]; then
  command -v "$REFERENCE_PYTHON" >/dev/null
  "$REFERENCE_PYTHON" -m venv "$MESH_ENV"
fi
"$MESH_ENV/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "The reference mesh environment requires Python 3.11"'
"$MESH_ENV/bin/python" -m pip install -e "$REFERENCE_ROOT[reference]"
"$MESH_ENV/bin/python" -m pip check
"$MESH_ENV/bin/python" -c 'import open3d, numpy, scipy; from tools.layout_inspection import reference_views; print("REFERENCE_MESH_IMPORT_OK")'
printf 'Static reference code installed. Set PI3X_PY=%s and PI3X_MESH_PY=%s.\n' \
  "$PI3X_ENV/bin/python" "$MESH_ENV/bin/python"
printf 'Acquire the Pi3X checkpoint and authorized SAM3 checkpoint before a new-video build_reference run; see docs/PI3X_GEOMETRY_REFERENCE.md.\n'
printf 'Install Blender for an editable static scene; Human adds SAM3 tracking/PyAV, PMPose, GVHMR and skinning. See docs/INSTALLATION.md.\n'

#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
export GVHMR_PYTHON="${GVHMR_PYTHON:-$project_root/.runtime/gvhmr-bedlam2/venv/bin/python}"
if [ ! -x "$GVHMR_PYTHON" ]; then
  echo 'Set GVHMR_PYTHON to your installed interpreter; see docs/install/gvhmr.md.' >&2
  exit 2
fi
export PATH="$(dirname -- "$GVHMR_PYTHON"):$PATH"
export PYTHONUNBUFFERED=1
# run.py sets GPU visibility (--gpu, inherited CUDA_VISIBLE_DEVICES, else device 0) before model imports.
exec "$GVHMR_PYTHON" "$project_root/tools/gvhmr/run.py" "$@"

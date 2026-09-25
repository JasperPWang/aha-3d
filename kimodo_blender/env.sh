#!/usr/bin/env bash
# Portable, per-process defaults. Configure paths before sourcing this file.
export KIMODO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export INDOOR_PROJECT_ROOT="$(cd -- "$KIMODO_ROOT/.." && pwd -P)"
# Machine-only defaults are ignored by Git and shared by this checkout's jobs.
if [[ -f "$KIMODO_ROOT/env.local.sh" ]]; then
  source "$KIMODO_ROOT/env.local.sh"
fi
export KIMODO_ENV="${KIMODO_ENV:-$INDOOR_PROJECT_ROOT/.venv}"
export KIMODO_UPSTREAM="${KIMODO_UPSTREAM:-$KIMODO_ROOT/upstream}"
export CHECKPOINT_DIR="${CHECKPOINT_DIR:-$KIMODO_ROOT/checkpoints}"
export KIMODO_CHECKPOINT="${KIMODO_CHECKPOINT:-$CHECKPOINT_DIR/Kimodo-SMPLX-RP-v1}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-$INDOOR_PROJECT_ROOT/.runtime/huggingface/hub}"
export HUGGINGFACE_CACHE_DIR="$HF_HUB_CACHE"
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$INDOOR_PROJECT_ROOT/.runtime/pip-cache}"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$INDOOR_PROJECT_ROOT/.runtime/conda-pkgs}"
export TEXT_ENCODER_MODE="${TEXT_ENCODER_MODE:-local}"
export TEXT_ENCODER_DEVICE="${TEXT_ENCODER_DEVICE:-cuda}"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS="${INDOOR_THREADS:-$(nproc 2>/dev/null || echo 4)}"
export PATH="$KIMODO_ENV/bin:$PATH"
export PYTHONPATH="$INDOOR_PROJECT_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

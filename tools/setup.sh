#!/usr/bin/env bash
# Select the installation level before running any component installer.
set -euo pipefail
SETUP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
SETUP_LEVEL=
LEVEL_GIVEN=false
SETUP_PYTHON=python3.11
SETUP_PLAN=false
WITH_SAM3D=false

usage() {
  printf '%s\n' \
    'Usage: bash tools/setup.sh [--level static|human|robotics] [--python python3.11] [--with-sam3d] [--plan]' \
    'Without --level, asks on a terminal. Noninteractive use requires --level.' \
    'Level 2 installs the Static code and SAM3 video decoding; follow the Human guide for GVHMR, PMPose, Blender and weights.'
}

normalize_level() {
  case "$1" in
    1|static) SETUP_LEVEL=static ;;
    2|human) SETUP_LEVEL=human ;;
    3|robotics) SETUP_LEVEL=robotics ;;
    *) return 1 ;;
  esac
}

while (($#)); do
  case "$1" in
    --level) [[ $# -ge 2 ]] || { printf '%s\n' '--level requires a value' >&2; exit 2; }
      if "$LEVEL_GIVEN"; then printf '%s\n' 'Specify --level only once.' >&2; exit 2; fi
      normalize_level "$2" || { printf 'Unknown installation level: %s\n' "$2" >&2; exit 2; }
      LEVEL_GIVEN=true; shift 2 ;;
    --python) SETUP_PYTHON="${2:?--python requires an executable}"; shift 2 ;;
    --with-sam3d) WITH_SAM3D=true; shift ;;
    --plan) SETUP_PLAN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$SETUP_LEVEL" ]]; then
  if [[ ! -t 0 ]]; then
    printf '%s\n' 'Choose an installation level explicitly with --level static|human|robotics in noninteractive use.' >&2
    exit 2
  fi
  printf '%s\n' \
    'Which installation level do you want?' \
    '  1. Static 3D scene (Pi3X, SAM3, Open3D; Blender installed separately)' \
    '  2. Human reconstruction (Static + SAM3 video; GVHMR/PMPose guide required)' \
    '  3. Robotics motion generation (Static + Kimodo and native G1)' >&2
  while true; do
    printf 'Choose 1, 2 or 3: ' >&2
    IFS= read -r answer || { printf '\nNo level selected. Installation cancelled.\n' >&2; exit 2; }
    if normalize_level "$answer"; then break; fi
    printf 'Invalid level: %s\n' "$answer" >&2
  done
fi

if "$WITH_SAM3D" && [[ "$SETUP_LEVEL" != robotics ]]; then
  printf '%s\n' '--with-sam3d is available only with Level 3 Robotics.' >&2
  exit 2
fi

PI3X_ENV="${PI3X_REFERENCE_ENV:-$SETUP_ROOT/.runtime/pi3x-inference/venv}"
SAM3_ENV_ROOT="${SAM3_RUNTIME:-$SETUP_ROOT/.runtime/sam3-segmentation}"
printf 'Selected installation level: %s\n' "$SETUP_LEVEL"
export AHA3D_SETUP_LEVEL="$SETUP_LEVEL"
if [[ "$SETUP_LEVEL" == human ]]; then
  printf '%s\n' 'Level 2 setup installs the Static code and SAM3 PyAV. Complete GVHMR, PMPose, Blender SMPL-X, body assets and weights using docs/install/human-motion.md.'
fi
cd "$SETUP_ROOT"

reference_args=(--python "$SETUP_PYTHON")
if "$SETUP_PLAN"; then reference_args+=(--plan); fi
bash "$SETUP_ROOT/tools/setup_reference.sh" "${reference_args[@]}"

case "$SETUP_LEVEL" in
  static)
    printf '%s\n' 'Level 1: install compatible Blender and acquire Pi3X/SAM3 checkpoints using docs/INSTALLATION.md.' ;;
  human)
    if "$SETUP_PLAN"; then
      printf 'Level 2: add PyAV 12.3.0 to %s/venv for SAM3 video tracking.\n' "$SAM3_ENV_ROOT"
    else
      "$SAM3_ENV_ROOT/venv/bin/python" -m pip install av==12.3.0
      "$SAM3_ENV_ROOT/venv/bin/python" -c 'import av; from sam3.model_builder import build_sam3_video_model; print("SAM3_TRACKING_IMPORT_OK")'
    fi
    printf '%s\n' 'Level 2 remaining installation and checks: docs/install/human-motion.md.' ;;
  robotics)
    core_args=(--env "$PI3X_ENV" --python "$SETUP_PYTHON")
    if "$WITH_SAM3D"; then core_args+=(--with-sam3d); fi
    if "$SETUP_PLAN"; then core_args+=(--plan); fi
    bash "$SETUP_ROOT/tools/setup_core.sh" "${core_args[@]}"
    printf '%s\n' 'Level 3 model and Blender setup: docs/install/kimodo.md.' ;;
esac

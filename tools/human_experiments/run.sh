#!/usr/bin/env bash
set -euo pipefail
runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="${runner_root}/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${HUMAN_RUNNER_PYTHON:-python3}" -m aha3d.workflow.human_runner "$@"

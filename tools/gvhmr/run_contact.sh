#!/usr/bin/env bash
# Run locally on the workstation GPU (--device cuda by default). New output paths only.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source "$project_root/kimodo_blender/env.sh"
export PYTHONDONTWRITEBYTECODE=1
manifest=''; output=''; models=''; render_only=0; placement_only=0; diagnostic_layout=0; device=cuda; refine_contact=0
while (($#)); do
 case "$1" in
  --manifest) manifest="$2"; shift 2;;
  --output) output="$2"; shift 2;;
  --models) models="$2"; shift 2;;
  --device) device="$2"; shift 2;;
  --refine-contact) refine_contact=1; shift;;
  --render-only) render_only=1; shift;;
  --placement-only) placement_only=1; shift;;
  --diagnostic-layout) diagnostic_layout=1; shift;;
  *) echo "Unknown option: $1" >&2; exit 2;;
 esac
done
[[ -n "$manifest" && -n "$output" ]] || { echo 'Required: --manifest JSON --output NEW_RUN [--models SMPLX_DIR] [--render-only]' >&2; exit 2; }
gvhmr_root="${GVHMR_ROOT:-$project_root/.runtime/gvhmr-bedlam2}"
python_bin="${CONTACT_PYTHON:-${GVHMR_PYTHON:-$gvhmr_root/venv/bin/python}}"
if (( diagnostic_layout && ! render_only )); then
 echo '--diagnostic-layout requires --render-only; it never bypasses alignment/contact/body placement gates.' >&2; exit 2
fi
[[ -x "$python_bin" ]] || { echo "Set CONTACT_PYTHON or GVHMR_PYTHON to an installed interpreter; see docs/install/gvhmr.md." >&2; exit 2; }
export PATH="$(dirname -- "$python_bin"):$PATH"
if (( placement_only )); then
 (( ! render_only )) || { echo 'Choose placement-only or render-only.' >&2; exit 2; }
 camera_cache="$("$python_bin" -c 'import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); d=json.load(open(p)); print((p.parent/d["render"]["camera_cache"]).resolve())' "$manifest")"
 exec "$python_bin" "$project_root/tools/gvhmr/placement_diagnostics.py" --manifest "$manifest" --camera-cache "$camera_cache" --output "$output" --require-accepted
fi
if (( ! diagnostic_layout )); then
 "$python_bin" - "$project_root" "$manifest" <<'PY_LAYOUT'
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'src'))
from aha3d.workflow.layout_gate import validate_layout
path=Path(sys.argv[2]).resolve()
validate_layout(json.loads(path.read_text()),path)
PY_LAYOUT
fi
if (( ! render_only )); then
 [[ -n "$models" ]] || { echo '--models is required for refinement' >&2; exit 2; }
 needs_group="$("$python_bin" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(int(len(d["actors"])>1 and not d.get("group_alignment",{}).get("report")))' "$manifest")"
 if [[ "$needs_group" == 1 ]]; then
  [[ ! -e "$output" ]] || { echo 'Group output must be new.' >&2; exit 2; }
  camera_cache="$("$python_bin" -c 'import json,sys,pathlib; p=pathlib.Path(sys.argv[1]); d=json.load(open(p)); print((p.parent/d["render"]["camera_cache"]).resolve())' "$manifest")"
  "$python_bin" "$project_root/tools/gvhmr/align_group.py" --manifest "$manifest" --camera-cache "$camera_cache" --output "$output/alignment"
  manifest="$output/alignment/manifest.json"
  output="$output/contact"
 fi
 motion_args=()
 if (( refine_contact )); then motion_args+=(--refine-contact); fi
 "$python_bin" "$project_root/tools/gvhmr/contact_refine.py" --manifest "$manifest" --output "$output" --models "$models" --device "$device" "${motion_args[@]}"
fi
render_args=()
if (( diagnostic_layout )); then render_args+=(--diagnostic-layout); fi
"$python_bin" "$project_root/tools/gvhmr/contact_render.py" --manifest "$manifest" --refinement "$output" --output "$output/preview" "${render_args[@]}"

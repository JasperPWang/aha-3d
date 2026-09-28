# Install Pi3X scene references

Pi3X supplies approximate room geometry and sparse source cameras for the scene
workflow. Install it when creating new references; cached measurement work does
not need model inference.
Pi3X inference alone does not load SAM3. The first new-video
`tools.layout_inspection.build_reference` run also creates semantic masks and
requires a separate SAM3 runtime and checkpoint. A later rebuild of the same
Pi3X bundle can reuse its complete source-matched mask cache. See
[reference rendering setup](../layout-inspection/reference-rendering.md#inputs-and-review).
For that first-run scope, start with the [reference installer](../PI3X_GEOMETRY_REFERENCE.md#runtime),
which installs Pi3X, Open3D and SAM3 code for the Static level. Follow
[machine rules](../../MACHINE.md).

## Supported baseline and validation boundary

The project's September 2026 pilot ran Python 3.11, Torch 2.7.1 with CUDA 12.8,
and a separate environment layered over its Kimodo environment. The shared
installation is a documented reproduction path, not a newly tested clean
installation or a universal hardware compatibility claim. It deliberately uses
one shared core environment and preserves the tested Torch pair. On another GPU/driver,
select a supported build from [official PyTorch releases](https://pytorch.org/get-started/previous-versions/)
and record the deviation before testing.

| Component | Pinned identity |
| --- | --- |
| [Pi3 source](https://github.com/yyfz/Pi3) | `9fa3ddb3f8d53041f8b2738df404f62223bbaa7b` |
| [Pi3X weights](https://huggingface.co/yyfz233/Pi3X) | revision `bb1deea4d7423de5b30691739cb451a3f57dc1d5` |

The upstream quick start installs its requirements file, whose pinned revision
requests Torch 2.5.1 / torchvision 0.20.1. Do not apply it to Kimodo, SAM, or an
existing working environment. This adapter only needs the inference subset below;
Gradio and training dependencies are not required. See the
[official Pi3 instructions](https://github.com/yyfz/Pi3#-quick-start).

## Use the Pi3X inference environment

For first-video references, `bash tools/setup.sh --level static` installs a dedicated
Pi3X environment at `.runtime/pi3x-inference/venv`. The Robotics level adds
[Kimodo to that Pi3X environment](core.md) after Static is installed. Select the installed Python
explicitly; its model/checkpoint directory is separate from its source checkout:

```bash
export BUNDLE_ROOT="$PWD"
export PI3X_PY="${PI3X_PY:-$BUNDLE_ROOT/.runtime/pi3x-inference/venv/bin/python}"
export PI3X_ROOT="$BUNDLE_ROOT/.runtime/pi3x"
export PI3X_UPSTREAM="$BUNDLE_ROOT/external/Pi3"
export PYTHONDONTWRITEBYTECODE=1
export XFORMERS_DISABLED=1
mkdir -p "$PI3X_ROOT"
```

The selected installer supplies the pinned Pi3X checkout and inference dependencies.
Do not apply upstream's old Torch pins on top of it. Use the model/download and
inference commands below for this component.

## Download authorized weights

Review the [model card and terms](https://huggingface.co/yyfz233/Pi3X) before using
the weights. Download them into runtime storage, not into a source export. The
historical safetensors file is approximately 5.44 GB, excluding cache/environment
space. This adapter loads an explicit file and never downloads it implicitly.

```bash
export HF_HUB_CACHE="$PI3X_ROOT/cache/huggingface"
"$PI3X_PY" - <<'PY'
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="yyfz233/Pi3X",
    revision="bb1deea4d7423de5b30691739cb451a3f57dc1d5",
    allow_patterns=["model.safetensors", "config.json", "README.md"],
    local_dir=os.path.join(os.environ["PI3X_ROOT"], "checkpoint"),
)
PY
export PI3X_CHECKPOINT="$PI3X_ROOT/checkpoint/model.safetensors"

```

## CPU import check and GPU smoke run

The CPU check imports architecture code without constructing a model, loading
weights, or claiming GPU support:

```bash
PYTHONPATH="$PI3X_UPSTREAM:$BUNDLE_ROOT/src" "$PI3X_PY" - <<'PY'
import torch, torchvision, cv2, numpy, safetensors
from pi3.models.pi3x import Pi3X
print("PI3X_IMPORT_OK", torch.__version__, torchvision.__version__)
PY
```

On the workstation GPU, first check CUDA, then run the project
adapter on a short continuous shot. Set `SOURCE_VIDEO` to a real input and
`PI3X_OUTPUT` to a new, claimed output directory; do not create that directory
in advance. This is a smoke run, not a final geometry or camera validation.

```bash
: "${SOURCE_VIDEO:?Set an absolute reference-video path}"
: "${PI3X_OUTPUT:?Set a new claimed output directory}"
"$PI3X_PY" -c 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
"$PI3X_PY" "$BUNDLE_ROOT/.agents/skills/pi3x-scene-reference/scripts/reconstruct.py" \
  --video "$SOURCE_VIDEO" --upstream "$PI3X_UPSTREAM" \
  --checkpoint "$PI3X_CHECKPOINT" --num-frames 32 --output "$PI3X_OUTPUT"
```

Inspect `run_report.json`, `inputs.json`, `cameras.json`, point-cloud views and
source frames. Successful inference must retain source frame IDs and timestamps,
finite predictions and valid rotations. It does not establish absolute metric
accuracy or a correct floor. Use 32 frames by default, or the 64-frame tier,
spanning both shot endpoints; shorter videos use every native frame.
`--frame-indices selection.json` accepts an ascending unique list of native IDs
matching the selected tier and including both endpoints. See the [Pi3X skill](../../.agents/skills/pi3x-scene-reference/SKILL.md)
for reconstruction, cached measurement and camera review.

## Full geometry reference

The smoke command above runs inference only. The normal room-reference entry is
`tools.layout_inspection.build_reference`: inference, SAM3 masks for every cached
frame, TSDF/context geometry and 3-5 native-camera overlays. Follow the
[geometry guide](../PI3X_GEOMETRY_REFERENCE.md) to configure Open3D and SAM3.
It also documents CPU-only rebuilding from cached predictions and masks.

## Troubleshooting

- `No module named pi3`: use the pinned checkout in the CPU check's `PYTHONPATH`;
  the reconstruction adapter adds `--upstream` itself.
- Torch/torchvision operator or CUDA errors: verify the paired wheel versions and
  driver compatibility (`nvidia-smi`). A CPU import pass cannot test CUDA.
- Out-of-memory (likely for the 64-frame tier on 24 GB cards; the pipeline was
  validated on a 96 GB card): use the 32-frame tier, reduce `--pixel-limit`,
  or select a shorter continuous shot and record the change. Preserve the chosen
  tier and both endpoints; a sparse subset is not a full-shot reference.
- Missing video timestamps/decoder failures: verify full input decoding with the
  source tools; do not invent timestamps or mix shots to bypass an error.
- Existing output directory: choose a new run path; helpers intentionally refuse
  overwrite. Confidence/floor failures need source and geometry inspection.
- Historical deployment details are not bundled prerequisites. The source project
  recorded them under `tasks/pi3x-investigation-20260908/evidence/` and its
  `REPORT.md`; these private run artifacts are excluded from this source bundle.

Official sources above were checked on 2026-09-10. No new environment, model
download or GPU inference was performed while writing this guide.

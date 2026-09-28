# Install SAM 3D Body reference inference

SAM 3D Body estimates selected body poses for approximate generated-motion
guidance. It uses exact frames and cameras from a same-shot [Pi3X bundle](pi3x.md).
It does not reconstruct the real person's motion or automatically solve room
contacts. Start with [Setup](../SETUP.md)
and follow [machine rules](../../MACHINE.md).

## Pinned components and deployment boundary

| Component | Required identity |
| --- | --- |
| [SAM 3D Body source](https://github.com/facebookresearch/sam-3d-body) | `b5c765a0d89d789985e186d396315e7590887b94` |
| [DINOv3 architecture source](https://github.com/facebookresearch/dinov3) | `6876159a11b4df116f30f667f8c9888617df0751` |
| [SAM DINOv3 checkpoint](https://huggingface.co/facebook/sam-3d-body-dinov3) | revision `11aaa346c7204874a1cbafe3d39a979080b2c55a` |
| MHR TorchScript | `assets/mhr_model.pt` from that same checkpoint revision |
| Historical GPU runtime | Python 3.11, Torch 2.7.1+cu128, torchvision 0.22.1+cu128 |

The adapter checks both Git revisions and rejects modified tracked source. Keep
`.git` in both checkouts. Its Torch Hub override loads the pinned local DINOv3
architecture with pretrained loading disabled, so no separate DINOv3 weight
file is needed. SAM's checkpoint supplies its learned parameters. The adapter
sets `MOMENTUM_ENABLED=0` and uses the checkpoint's MHR TorchScript; installing
the separate [MHR/Momentum project](https://github.com/facebookresearch/MHR) or
substituting a global body model is unnecessary for this path.

Historical inference (one 96 GB RTX PRO 6000) succeeded with these source/weight
identities in a venv inheriting Kimodo dependencies. The shared core recipe has not
been rerun as a clean installation. Its CPU and GPU checks are acceptance steps
for the recipient, not results already established on their machine.

## Use the shared core environment

Install [the Robotics level](core.md) with `--with-sam3d`. SAM, Pi3X and Kimodo use
the same Python and compatible Torch stack; model/checkpoint directories do not
create extra Python environments. If the core is already installed, rerun its
installer with that flag to add the optional adapter.

```bash
export BUNDLE_ROOT="$PWD"
export KIMODO_ENV="$BUNDLE_ROOT/.runtime/pi3x-inference/venv"
bash tools/setup.sh --level robotics --with-sam3d
source kimodo_blender/env.sh
export SAM_ROOT="$BUNDLE_ROOT/.runtime/sam3d-body"
export SAM_PY="$KIMODO_ENV/bin/python"
export SAM_UPSTREAM="$BUNDLE_ROOT/external/sam-3d-body"
export DINO_UPSTREAM="$BUNDLE_ROOT/external/dinov3"
export PYTHONDONTWRITEBYTECODE=1
export MOMENTUM_ENABLED=0
mkdir -p "$SAM_ROOT"
```

The `--with-sam3d` flag provides the pinned SAM/DINO checkouts and the adapter's
extra packages used with manually supplied person boxes, Pi3X intrinsics and
image overlays. Upstream's full demo has a broader dependency list and Detectron2
installation; MoGe and SAM3 are additional optional paths. Follow the
[official installation guide](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md)
only if choosing those extra demo features, and resolve conflicts without replacing
the shared Torch/Transformers constraints.

## Authorized checkpoint and MHR download

Request access to the [official SAM DINOv3 model repository](https://huggingface.co/facebook/sam-3d-body-dinov3)
and accept its terms using your own account. Authenticate locally after access is
approved. Keep credentials out of commands, source exports and job logs; do not
copy another user's credential cache. The login below prompts interactively and
stores authentication through Hugging Face's normal local mechanism.

```bash
"$SAM_PY" - <<'PY'
from huggingface_hub import login
login(add_to_git_credential=False)
PY
```

Acquire the three files at the same revision:

```bash
export HF_HUB_CACHE="$SAM_ROOT/cache/huggingface"
"$SAM_PY" - <<'PY'
import os
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="facebook/sam-3d-body-dinov3",
    revision="11aaa346c7204874a1cbafe3d39a979080b2c55a",
    allow_patterns=["model.ckpt", "model_config.yaml", "assets/mhr_model.pt"],
    local_dir=os.path.join(os.environ["SAM_ROOT"], "checkpoint"),
)
PY
export SAM_CHECKPOINT="$SAM_ROOT/checkpoint/model.ckpt"
export MHR_MODEL="$SAM_ROOT/checkpoint/assets/mhr_model.pt"
test -s "$SAM_CHECKPOINT"
test -s "$MHR_MODEL"
test -s "$SAM_ROOT/checkpoint/model_config.yaml"

```

`model_config.yaml` must be beside `model.ckpt` or one directory above it. Preserve
the matching config and bundled MHR. The inference adapter never downloads these weights itself.

## CPU import check

This checks imports and the adapter's CLI without loading
weights or exercising CUDA. `MOMENTUM_ENABLED=0` must be set before importing SAM.

```bash
export PYTHONPATH="$SAM_UPSTREAM:$BUNDLE_ROOT/src"
export MOMENTUM_ENABLED=0
"$SAM_PY" - <<'PY'
import torch, torchvision, cv2, termcolor, webdataset, braceexpand
from sam_3d_body import SAM3DBodyEstimator, load_sam_3d_body
print("SAM_IMPORT_OK", torch.__version__, torchvision.__version__)
PY
"$SAM_PY" -m aha3d.motion.sam3d --help
```

An import pass does not prove that DINO architecture construction, MHR loading,
body/hand inference or the input camera conventions work. Test those below.

## GPU smoke inference through the project adapter

Prepare `selection.json` from inspected Pi3X processed RGB. At minimum inference
needs an `events` list with `source_frame` and `bbox_xyxy` for one person per
selected frame. These example values are placeholders that must be replaced with
an actual frame present in the bundle and a box in processed-image pixels:

```json
{"events": [{"source_frame": 120, "bbox_xyxy": [100, 20, 300, 370]}]}
```

For subsequent guidance compilation, author the complete
[selection schema](../../.agents/skills/sam3d-motion-reference/references/schema.md),
including native timing and room orientation. Do not mark review complete before
inspecting overlays. Inference and reviewed selection are separate artifacts.

On the workstation GPU, with a same-shot Pi3X bundle, run:

```bash
: "${PI3X_BUNDLE:?Set the absolute same-shot Pi3X bundle directory}"
: "${SELECTION_JSON:?Set the absolute authored selection JSON path}"
: "${SAM_OUTPUT:?Set a new claimed output directory}"
export PYTHONPATH="$SAM_UPSTREAM:$BUNDLE_ROOT/src"
"$SAM_PY" -c 'import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))'
"$SAM_PY" -m aha3d.motion.sam3d \
  --pi3x "$PI3X_BUNDLE" --selection "$SELECTION_JSON" \
  --upstream "$SAM_UPSTREAM" --dinov3 "$DINO_UPSTREAM" \
  --checkpoint "$SAM_CHECKPOINT" --mhr "$MHR_MODEL" --out "$SAM_OUTPUT"
```

Do not create `SAM_OUTPUT` beforehand. Retain `observations.json` (including provenance), `raw/` and overlays. Inspect full-body limb/facing plausibility and cropping in the
original image coordinates. Projection agreement verifies adapter conventions,
not real-world pose accuracy. Guidance compilation runs separately in the Kimodo
environment and needs a native 30 fps Kimodo baseline; follow the
[SAM workflow](../../.agents/skills/sam3d-motion-reference/references/workflow.md).

## Troubleshooting and evidence limits

- `GatedRepoError`, HTTP 401/403: confirm this account has model access and that
  the process sees its local authentication. Retry only after access is resolved.
- Missing `torchvision`, `braceexpand`, or `termcolor`: these caused actual historical
  setup/model-load failures. Install in the selected `KIMODO_ENV`, retain constraints, then
  repeat the appropriate import or inference check.
- Revision/modified-source rejection: check `git rev-parse HEAD` and
  `git status --porcelain --untracked-files=no` in both checkouts. Recreate a clean
  pinned checkout at a fresh path; do not disable the adapter checks.
- An unexpected Torch Hub request is intentionally rejected. Use the DINOv3
  variant and the pinned adapter, not a ViT-H checkpoint or a changing remote hub.
- MHR import warnings with Momentum disabled are expected for this TorchScript
  path. Missing config, incompatible TorchScript or absent `mhr_model.pt` are
  failures; do not substitute unrelated global MHR assets.
- Empty/missing event frames: reconstruct Pi3X with exact selected frame IDs from
  the same source shot. Person boxes use processed Pi3X pixels, not video pixels.
- CUDA/OOM: verify paired wheels and free GPU memory (`nvidia-smi`; stop other
  GPU processes first); start with one inspected event. Lower memory in one smoke image does not
  establish a general requirement for every image/hand-refinement case.

The source project's `tasks/sam3d-integration-20260908/HANDOFF.md`,
`environment.freeze.txt`, `runtime.json` and `gpu-smoke.json` record historical
imports, preprocessing and successful one-image body/hand inference. Those private
run artifacts are not distributed in this bundle, and the smoke test was not an
accuracy or room-contact benchmark. Official sources were checked on 2026-09-10;
no new installation, checkpoint download or GPU job was run for this guide.

# Run the adapter

Run from the aha3d project root. Use [machine rules](../../../../MACHINE.md)
and claim output paths before executing. Examples use shell variables for paths
that the caller must set to actual claimed inputs/outputs.

## Runtime

This bundle contains no installed SAM runtime or model assets. The paths below are suggested locations; version/access statements describe the original deployment. Configure your own authorized runtime using docs/SETUP.md.

SAM checkout: `external/sam-3d-body`, pinned to
`b5c765a0d89d789985e186d396315e7590887b94`. The inference module checks the revision
and rejects modified tracked source. Review coordinate/API changes before updating
that pin. Suggested SAM Python: `.runtime/sam-3d-body/venv/bin/python`.
It inherits the existing Kimodo environment and adds dependencies locally; never
install SAM dependencies over the shared Kimodo environment. Runtime setup and
validation evidence are in the integration task handoff.

DINOv3 architecture checkout: `external/dinov3`, pinned
to `6876159a11b4df116f30f667f8c9888617df0751`. The adapter routes SAM's Torch Hub
request to this local checkout with pretrained weights disabled; it does not
silently fetch changing architecture code into the global Torch cache.

Access to [facebook/sam-3d-body-dinov3](https://huggingface.co/facebook/sam-3d-body-dinov3)
was verified and the official files downloaded at revision
`11aaa346c7204874a1cbafe3d39a979080b2c55a` into
`.runtime/sam-3d-body/checkpoint/`. Use `model.ckpt` and
`assets/mhr_model.pt` there; `model_config.yaml` is beside the checkpoint. See the integration handoff for download/runtime evidence. Supply these files through your own authorized access. Keep local authentication out of logs when checking future access.

## Infer selected observations

Use the Pi3X skill to produce/reuse a same-shot reference bundle with the selected
event frames. Never reuse the existing home-office cameras for g0070 footage.
The compiler consumes the original bundle, not just a calibrated measurement
export. Uniform metric calibration does not affect the relative directions used
here. Author `selection.json` using [the schema](schema.md).

On the workstation GPU (validated on one 96 GB RTX PRO 6000):

```bash
source kimodo_blender/env.sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src"
SAM_PY="$PWD/.runtime/sam-3d-body/venv/bin/python"
"$SAM_PY" -m aha3d.motion.sam3d \
  --pi3x "$PI3X_BUNDLE" --selection "$SELECTION_JSON" \
  --upstream external/sam-3d-body \
  --dinov3 external/dinov3 \
  --checkpoint "$SAM_CHECKPOINT" --mhr "$MHR_MODEL" \
  --out "$OBSERVATION_OUTPUT"
```

`model_config.yaml` must be beside the checkpoint or one directory above, matching
the official loader. Person boxes bypass detector dependencies. The helper uses
the checkpoint's TorchScript MHR, not a globally installed MHR model. It performs
full inference, including hand refinement. Large intrinsic warps can crop image
content; inspect the original-image overlays and reject clipped/poor estimates.

## Compile guidance

Inspect overlays and set actual per-event review notes. Retain a native Kimodo
single-clip baseline NPZ containing `local_rot_mats [T,22,3,3]`,
`root_positions [T,3]` and `smooth_root_pos [T,3]` in native Y-up coordinates.
The baseline must be 30 fps and match `native_frames`. Do not supply a skinned cache,
AMASS export or arbitrary output-frame-rate animation. The NPZ alone may not prove
its rate; check its generation report.

On CPU (no GPU needed):

```bash
source kimodo_blender/env.sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src"
"$KIMODO_ENV/bin/python" -m aha3d.motion.reference \
  --observations "$OBSERVATION_OUTPUT/observations.json" \
  --pi3x "$PI3X_BUNDLE" --selection "$SELECTION_JSON" \
  --baseline "$NATIVE_BASELINE" --route "$ROOT_ROUTE_JSON" \
  --out "$GUIDANCE_OUTPUT"
```

For source-video people, pass the reviewed root2d route by default, following
root > hands >= feet > text-only. Omit `--route` only for a documented exception
or an explicit task that does not need route guidance. The compiler preserves the
route, rejects conflicting hand/route goals at the same frame, and checks
native FK serialization. Inspect `report.json` for the extra root/heading fields.
The output directory must not already exist; failures never overwrite a prior run.

## Use in the shared pipeline

Create a new claimed scene recipe with `body.mode: generate`, the desired prompt,
seed and timing, and `body.constraints` pointing to the generated `constraints.json`.
Keep baseline and guidance coordinate placement consistent with the recipe. Then:

```bash
bash tools/indoor plan "$SCENE_ID" --recipe "$RECIPE_NAME"
bash tools/indoor run "$SCENE_ID" --recipe "$RECIPE_NAME" --preview
```

The existing pipeline copies/fingerprints the constraints and passes them to native
Kimodo generation. Preserve output duration and resample rotations before skinning.
Follow the Kimodo skill for baseline comparison, representative visual inspection,
floor/furniture clearance, framing and complete video validation. Direction-only
constraint compilation does not establish smooth motion or actual surface contact.

## Avoid repeating pilot setup work

Reuse the pinned runtimes and authorized weights above. A different
source video needs its own Pi3X bundle. Review overlays before generation: the
pilot's first raised arm was left, despite an earlier right-hand interpretation.

For optional neighboring-frame refit, use [temporal guidance](temporal.md). Keep
the original sparse event selection separate from the larger support selection.
Do not emit every support pose as a native hand key. The compiler always records
pairwise temporal diagnostics, even with refit disabled.

Keep preview configuration limited to fields actually consumed, rather than
carrying old manual keyframes into a copied config. Use the generic preview helper
with the actual target report; avoid scene scripts with hardcoded key counts.
Store generation, decode and visual review as separate evidence and link them
from the final report, so an earlier stage's pending status is not mistaken for
the final run state. The previous pilot scripts are examples in
`tasks/sam3d-kimodo-pilot-20260908`; reusable pose logic remains in the modules.

## Stage-aware reuse

Identify actors and important moments during source analysis so Pi3X selection
contains the required timestamps. Infer only useful sparse observations. Keep raw
observations independent of the reviewed selection and compiler output: changing
an authored root or facing interpretation can reuse valid observations, but needs
new guidance and affected generated motion. An unnecessary constant facing override
can remove an intended turn because native hand keys also carry root and heading.

Use `--motion-only` for baseline/guided generation and skinning before ensemble
integration. Room/camera comparison can be completed first using the
[scene workflow](../../../../docs/SCENE_WORKFLOW.md). Do not rerun SAM for camera
lighting changes or populate every output frame with gesture constraints. The
current SAM inference interface remains one person per selection; multi-person
model-load batching has not been implemented or benchmarked.

## Full-body and leg references

Use [full-body review and leg guidance](legs.md) to redraw cached observations,
merge explicitly reviewed same-person sparse batches, or test native feet. The
inference adapter now draws arms and legs; cached legacy observations need no
reinference for this presentation change. New inference selections may include
`person_id`. The leg compiler retains baseline root/heading and global ankle rotation and
requires matched generation plus withheld-time and mesh comparison before use.

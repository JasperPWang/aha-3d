---
name: sam3d-motion-reference
description: Estimate sparse body poses with SAM 3D Body and same-shot Pi3X cameras, review full-body overlays, and compile reviewed arm directions or experimental leg directions into native Kimodo constraints. Use for reference-assisted approximate gestures and motion keyframes in aha3d.
---

# SAM 3D Body motion references

Current source-person default: use [GVHMR](../gvhmr-body-reconstruction/SKILL.md)
for visible source motion, then room alignment and import into the authored Blender
room. Keep existing Blender room modeling; Pi3X is a reference. Kimodo/SAM guidance
below applies to generated new/changed actions or an authorized fallback. This
skill extracts observations and compiles guidance; full reconstruction contact
requirements belong to the scene workflow. A reference-only task does not expand
into full reconstruction.


Use SAM to interpret selected reference poses, Pi3X for camera orientation, and
Kimodo to generate similar motion. The adapter supports left/right arm directions,
optional authored facing/root placement, and native hand constraints. A separate
experimental compiler supports reviewed body-relative leg directions and native
feet; read [leg review and comparison](references/legs.md) before using it. It does
not recover the real person's motion or automatically fit furniture contacts.

For optional source-informed Kimodo generation, use this skill
with priority **root > hands >= feet > text-only**. Use judgment to select reliable,
useful source references; record material omissions and review the resulting motion.
Foot guidance retains its experimental status and validation requirements.

Read [workflow and runtime](references/workflow.md) to run inference or compile
cached observations; read [selection schema](references/schema.md) when authoring
events. For jitter diagnosis and optional pre-compilation arm refit, read
[temporal guidance](references/temporal.md). Implementation lives in project `src/aha3d/motion/sam3d.py` and
`reference.py`; use those modules rather than copying pose logic into scene scripts.

- Use a Pi3X bundle from the same video and exact selected source frames. Preserve
  its original `inputs.json`, `inputs.npz` and `cameras.json`.
- Inspect SAM overlays, select only useful events, and record actual review notes.
  Out-of-frame, occluded or implausible limbs are not reliable guidance. Projection
  agreement verifies the adapter's convention, not model accuracy.
- Author the proper world-to-Kimodo rotation for the chosen room/recipe. It must
  map Pi3X world Z up to Kimodo Y up. Baseline root placement is retained unless
  explicitly overridden; estimated SAM body depth is not used as a root target.
- Follow [motion control policy](../../../docs/MOTION_CONTROLS.md). Native hand
  constraints also fix root height, smooth root and heading at each key. Keep
  events sparse; examine those extra fields in the compiler report. Do not add
  post-generation arm IK or keyed facing edits.
- Treat exact contact, wrist/ankle twist, full-body pose conversion and automatic
  path fitting as separate work. The hand and experimental foot compilers retarget
  selected directions on existing proportions. Neither result is a contact fit.

SAM already estimates lower limbs. Missing legs in older arm-only overlays are
an adapter presentation/control limitation, not evidence that SAM legs are
universally unstable. Use `motion.observations` for cached full-body overlays and
paired source/body crops. Review actual visibility; in-frame flags are not
occlusion confidence.

Claim writable paths first and run compute/tests locally. Inference uses
one GPU and an isolated SAM environment; compilation uses the installed Kimodo
environment on CPU. New run outputs belong under `runs/<scene>/<run-id>/`.
Use the Pi3X skill for a missing same-shot bundle and the Kimodo skill for generated
motion, skinning and room validation. The compiled JSON plugs into an ordinary
scene recipe's `body.constraints` field.

For user-facing human motion previews, default to the actual SMPL-X mesh, as
requested in [preferences](../../../docs/PREFERENCES.md). The shared
`python -m aha3d.motion.preview --motion ... --out ...` now defaults to
mesh, using deployed skinning and a fixed viewing direction to expose facing.
Use `--baseline` for side-by-side comparison. `--representation skeleton` is an
explicit diagnostic option. Mesh previews resample rotations before skinning,
follow pelvis XY for display, preserve heading and vertical motion, and do not
establish furniture contact. Claim the output video and its sibling assets folder.

In a complete scene workflow, identify useful gesture/turn moments during source
analysis, then reuse the same-shot cached observations after room/camera review.
Keep observation selection, reviewed native guidance and generated motion as
separate artifacts. Recompile guidance when facing interpretation changes; native
hand events carry heading/root values, so an unnecessary constant facing override
can suppress an intended turn. See the [staged workflow](../../../docs/SCENE_WORKFLOW.md)
for scheduling and reuse boundaries.

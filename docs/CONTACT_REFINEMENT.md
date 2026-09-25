# Reusable source-motion contact refinement

## Full reconstruction includes contact repair

For full reconstruction requests, the owner's 2026-09-20
[completion contract](MOTION_CONTROLS.md#full-pipeline-completion-contract) requires
scene anchoring followed by finite-object and foot-ground contact refinement and
validation. The legacy entrypoint defaults below describe software behavior, not
permission to stop a full task at placement. Supply the explicit refinement mode
and source-bound constraints; include GVHMR foot contacts in scene-contact solves.
No observed furniture interaction means no invented furniture-contact target, but
floor/contact and collision checks still apply.

Keep source-supported contact refinement (hand, seat and predicted foot contacts).
The owner's 2026-09-22 clarification permits whole-body translation to improve
contact and penetration; it does not permit collision-driven joint modification
or human leg repair/IK. Preserve body scale and local poses during translation,
and check temporal continuity, slip and source alignment. Source-supported upper-
body contact fitting remains a separate method subject to the motion policy.

The current `solve_scene_coefficients` implementation defaults to
`collision_correction=False`. This is a software default, not a ban on translation
that improves penetration. Contact/depth objectives already move the whole body;
changing an explicit collision objective requires implementation validation and
must preserve joint poses. This documentation change does not enable that flag.
Contact patch gap/velocity terms still run. Record temporal loss weights, weighted
contributions, added velocity/acceleration and actual contact-transition playback.
Conflicting contacts remain explicit residuals. `refine_leg_contacts.py` now exits
without producing a result. Its earlier outputs are not current deliverables.

## Legacy native-motion placement interface

Accepted 2026-09-12: preserve GVHMR native global motion and body dimensions with
one fixed rigid room alignment (scale 1). The existing entrypoints default to
this mode. There is no support-foot detector, automatic height correction,
per-frame root/floor correction, temporal smoothing or IK in the default branch.
Native-parameter re-skinning verifies that the input cache still reproduces the
original motion; source-placement and layout checks remain in effect.

For a specific person with legs below the floor, first set that actor's
`vertical_translation_m` to a reviewed scalar in metres (room Z, positive upward).
The default is 0 for each person; do not put this setting in the batch `config`.
For example, in an existing manifest's actor list:

```json
[
  {"id": "person_001", "vertical_translation_m": 0.12},
  {"id": "person_002", "vertical_translation_m": 0.0}
]
```

These are illustrative actor fields, not a complete manifest or inferred offsets.
Keep each actor's existing `motion`, `alignment`, `cache` and source evidence.
The first person is translated upward by 12 cm at every frame; the second receives
no additional translation. Both vertices and joints move together. Poses, root XY,
timestamps, topology and frame-to-frame motion are preserved. Source parameters
remain unchanged and the output parameter file records the combined fixed
translation. A zero-offset selected cache is copied byte-for-byte.

Run with a claimed output path using the GVHMR environment:

```bash
bash tools/gvhmr/run_contact.sh --manifest /absolute/path/manifest.json \
  --models /absolute/path/body_models --output /absolute/path/new-native-run
```

The wrapper fits fixed-unit rigid placement first if multi-person group evidence
is absent, then validates native preservation and renders the selected caches.
The existing `contact/` output naming is retained for compatibility; it does not
imply contact repair ran. Per-actor reports and Blender metadata record the method
and constant offset. The native report's acceptance concerns motion preservation;
`contact_validated=false` explicitly leaves physical contact unvalidated. Source
placement is separately gated. Inspect the full source/room clip for remaining
penetration and floating; neither residual automatically enables IK. No particular
scene or offset has been validated by this code/policy update.

## Historical leg solver (not the current reconstruction route)

The remainder archives the older solver. The current request for contact refinement
does **not** authorize this leg-IK route. For historical reproduction only, add `--refine-contact` to either the wrapper above or the
direct CLI below. It uses one solver configuration for all actors. Do not combine
this automatic support-height mode with nonzero `vertical_translation_m`.

## Scope and decisions

The caller supplies a reviewed, horizontal Z-up ground plane and marks each actor
as performing grounded motion. Stairs, jumping, sitting on raised supports and
unknown floors need a different support model. Visibility exclusions are explicit.

0. Preserve native human dimensions and nominal metric units (scale fixed to 1).
   Align only constant yaw/placement against the room, ground and source projection.
   No independent or shared scale fitting is allowed. Reject changed evidence,
   any fitted scale, or failed rigid alignment. Relative body shape is retained.
   Check actual observed source placement before contact and again on the selected
   repaired caches. Model-generated incam projections alone cannot pass this gate.
1. Reproduce the aligned cache from native-global SMPL-X parameters, timestamp
   resampling and the recorded constant similarity. Reject mismatches.
2. Estimate one robust constant vertical shift from low-speed grounded samples.
   Offsets below 3 cm are left alone; offsets above 50 cm require review.
3. Detect sustained low/slow foot segments, excluding unreliable observations.
   Foot vertices come from the SMPL-X ankle/toe skinning weights.
4. If local penetration or sliding remains, optimize hip, knee, ankle and toe
   rotations jointly across the clip, with bounded joint excursions, broad knee
   flexion limits, original-pose preference and temporal smoothing. Optimize exact
   SMPL-X foot skinning, then re-skin the full body.
5. Validate penetration, stationary-foot speed and acceleration on the same
   before/after sample cohort, and verify that root XY did not change.

Root orientation and upper-body rotations remain unchanged. Root Z receives only
the constant alignment shift. This never uses camera-space root replacement or
per-frame viewing-ray floor correction. The validity mask gates IK data/floor
losses; temporal regularization spans excluded intervals but cannot recover them.

Small remaining penetration up to 5 mm is the current acceptance tolerance.
Contact-speed P90 may increase by at most 2.5 cm/s; acceleration P90 by at most
25% plus 0.5 m/s². These are engineering gates, not benchmark accuracy claims.
Candidate failure keeps the original selected cache and returns exit code 2 after
writing the batch summary. Numerical/input failures return nonzero immediately.
No-op actors preserve the original selected NPZ byte-for-byte.
Contact acceptance alone is insufficient: it cannot validate body scale or source
placement. The rejected ref42 contact-only result used 1.069 / 0.767 / 0.700 actor
scales; making those bodies touch the floor made the size mismatch obvious.
That output is withdrawn. The group-scale gate runs before any contact editing.

## Invocation

Use a fresh claimed output path with the deployed GVHMR environment. See [machine rules](../MACHINE.md) and
[example manifest](../configs/examples/contact_refinement.json).

    "$GVHMR_PYTHON" tools/gvhmr/contact_refine.py \
      --manifest /absolute/path/manifest.json \
      --models /absolute/path/body_models \
      --output /absolute/path/new-contact-run --device cuda --refine-contact

Manifest paths resolve relative to the manifest file. Each actor requires id,
motion, alignment, cache, grounded_motion; optional exclude_seconds contains
inclusive timestamp intervals. The cache uses the shared schema with vertices,
joints, faces, vertex_ids, time_seconds and fps.
The initial adapter supports neutral SMPL-X with 12 PCA hand components and native
GVHMR global parameters; it is not a generic mesh-warp tool. Native endpoint hold
is limited to one 30 fps interval. Alignment up-axis tilt above 15 degrees fails.

## Outputs and automation

Each actor gets candidate.npz, selected body_room.npz,
refined_parameters.npz and report.json; the batch writes summary.json,
manifest.json and implementation/model provenance. Refined parameters retain
original arrays and add refined_body_pose plus the new constant room transform.
Candidate parameters are not necessarily the selected result: check accepted and
selected in report.json before consuming them.

Pass only accepted selected caches to the shared Blender body importer. Preserve
the authored room and source camera, save to a distinct scene, reopen it and check
all actor meshes across the output timeline. Render source/before/after comparisons,
fully decode videos and inspect representative frames. The stage does not hide
scene/model mismatch by moving the camera or changing the room.

### One-command refinement and rendering

With `--refine-contact`, the shared wrapper automatically inserts fixed-unit rigid alignment for a multi-person
manifest without an existing group report, then runs contact and rendering in the
same local process. Grouped output uses alignment/, contact/ and contact/preview/.
An already grouped manifest runs directly into the requested new contact directory:

    bash tools/gvhmr/run_contact.sh --manifest /absolute/path/manifest.json \
      --models /absolute/path/body_models --output /absolute/path/new-run --refine-contact

Add a render section containing scene (room-only Blender file), camera_cache and
source_video paths. Optional output_blend selects a distinct scene destination;
otherwise preview/scene.blend is used. Explicit per-actor visible_until_seconds
controls render visibility; reliability exclusions do not automatically hide people.
Use --render-only to render an already accepted batch. Existing preview/scene paths
are rejected to avoid overwriting earlier artifacts. Output preview/ contains the
source comparison, full rendered video, all-frame Blender validation, video decode
report and review sheets. This initial renderer requires a uniform whole-clip
timeline beginning at source time zero.


## Group alignment evidence

A multi-person aligned manifest must include group_alignment.report pointing to
the rigid alignment report. It binds locked native units, ordered actor identities,
alignment/cache hashes, camera hash, and source-projection/height diagnostics.
Neither per-person nor shared scale fitting is permitted. Diagnostic source targets from GVHMR
camera-space projections are approximate predictions, not annotated ground truth;
room scale remains provisional without external metric evidence. Inspect source
comparisons before selecting a result, even when numerical gates pass.


## Native-unit correction after audit

Pi3X already applies its predicted metric factor to points and camera translation;
the room floor transformation is rigid. The old actor-wise similarity optimization
was not a validated unit conversion. Do not compensate projection errors by fitting
human size. The replacement optimizes only constant yaw and XY placement, derives
constant Z from support, and keeps scale=1. A future metric recalibration requires
independent evidence and a separate explicit unit transform, not this optimizer.

The earlier shared-scale fitting proposal and its outputs are unadopted. The
alignment report now requires scale_policy=native_units_locked and
scale_optimized=false. Old shared-scale reports are rejected even if all actor
scales happen to be equal.


## Standardized source-placement acceptance

All actors and scenes use the same observed-placement stage, implemented in
`tools/gvhmr/placement_diagnostics.py`. It reads source COCO17 detector XY and
confidence, native timestamps, the actual camera image size/calibration, and
aligned SMPL-X joints. Only anatomically matched hips, knees, ankles, shoulders,
elbows and wrists contribute; inferred spine/head points are not observations.
Detector joint definitions and body-model joint definitions can still differ.

Run a CPU-only diagnosis before spending GPU time:

    bash tools/gvhmr/run_contact.sh --placement-only \
      --manifest /absolute/path/aligned-manifest.json \
      --output /absolute/path/new-placement-report

The manifest supplies `pose_confidence` per actor, or the existing
`preprocess/vitpose.pt` beside its native motion is discovered. The standard
confidence threshold is the upstream detector score 0.5, not a calibrated
probability. Configurations apply to the entire batch, never individual IDs.
Reports expose temporal coverage and per-window errors; a good whole-clip median
cannot override a bad observed window. Missing or insufficient observations are
unverified, not zero error. Excluded intervals retain explicit limited coverage.

Constant-XY and separate time-window fitting probes classify likely rigid versus
temporal mismatch. These probes never alter motion or provide executable per-frame
corrections. Apparent extent alone cannot separate depth, body morphology and joint
semantics. A temporal mismatch calls for a separately validated trajectory/camera
investigation; no general root-trajectory optimizer is implemented by this stage.

Direct `contact_refine.py` runs the checks before loading the body model and after
contact acceptance, recording `placement_before/report.json` and
`placement_after/report.json`. Direct `contact_render.py`, including Blender
assembly/verification and `--render-only`, requires accepted post-contact evidence.
The evidence binds the full manifest, camera, body caches, native motion, alignment,
observations and diagnostic implementation. Changing exclusions, render visibility
or a selected cache invalidates it. Old contact-only candidates cannot be promoted
by skipping the wrapper. Use the diagnostic CLI with `--refinement` to inspect an
older candidate; it does not grant delivery acceptance by itself.

Nonzero status preserves diagnostic evidence and stops the stage. Passing means
observed-projection engineering checks passed; it does not prove source identity,
physical scale, contact truth, visibility/occlusion correctness or full scene fidelity.
Retain visual source comparisons. The reusable contact solver is restricted to
reviewed horizontal grounded motion; stairs, sitting, jumps and unknown supports
must report unsupported scope instead of applying this flat-floor procedure.

The lounge is a regression example, not a source of actor-specific constants.
Source-workspace regression evidence and handoffs are excluded from this bundle.
An accepted second real-scene validation has not been established.

## Portable runtime setup

Follow [GVHMR installation](install/gvhmr.md) for the separate Python environment
and licensed body assets. Set `GVHMR_PYTHON` (or `CONTACT_PYTHON` for this stage),
`BLENDER_BIN`, and optionally `FFMPEG_BIN` before invoking the wrapper. Its Python
default follows `GVHMR_ROOT/venv/bin/python`; the default GVHMR root matches the
installation guide. Blender and FFmpeg also support discovery on `PATH`.
The existing core environment is not modified or used as an implicit GVHMR
installation. The stage runs on the local GPU (`--device cuda`).

This portable copy includes CPU geometry tests and command-line checks. A fresh
pretrained runtime installation, GPU refinement and Blender delivery run have
not been performed in this copy; source-workspace validation is separate evidence.

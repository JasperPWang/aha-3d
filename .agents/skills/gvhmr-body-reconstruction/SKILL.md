---
name: gvhmr-body-reconstruction
description: Reconstruct source people with reviewed tracking, GVHMR and default v2 world optimization, refine scene contacts, and bake validated motion into an editable room. Use for source-person reconstruction; generated new actions use Kimodo.
---

# GVHMR source-person reconstruction

Use the [motion policy](../../../docs/MOTION_CONTROLS.md) for current constraints.
Full reconstruction defaults to **GVHMR → shared-scene anchoring → v2 → contact
refinement → validated scene delivery**. Preserve a native GVHMR comparison.
A stage-only, review or debugging request retains its narrower scope. Reuse valid
caches unless the requested comparison requires fresh inference.

## Run the requested work

- For the full route, use [the pipeline](../../../docs/REAL2SIM_PIPELINE.md) and
  [v2 commands](../../../docs/WORLD_POSTOPT.md). Use reviewed scene floor/upright,
  same-shot dense Pi3X depth/cameras and the configured tracking frontend.
- For actor identity, source exits or failed tracking, read
  [tracking operations](references/source-motion.md#actor-tracking-and-track-termination).
  Review masks before mask-conditioned PMPose/GVHMR; preserve source frame IDs.
  Confirmed exit hides the actor; temporary occlusion does not end a track.
- For alignment and contact errors, read
  [room basis](references/source-motion.md#source-motion-and-room-basis) and
  [contact refinement](references/source-motion.md#full-pipeline-contact-refinement).
- For saving playback into an existing room, read
  [scene import](references/source-motion.md#import-into-the-modeled-room).
- For repeated controlled comparisons, use
  [human automation](../../../docs/HUMAN_AUTOMATION.md); this does not require
  rerunning unrelated valid stages.

## Preserve these constraints

Body scale remains 1. Initial rigid alignment is followed by default v2;
trajectory scaling is not enabled implicitly. Keep local articulation and body
shape fixed during whole-body translation. Contact optimization may translate
root XYZ to improve support and penetration, with temporal regularization and
checks for source projection, continuity and foot slip. Do not modify joints to
remove collisions or run human 6D leg repair/leg IK. Report incompatible contacts.

V2's per-person camera transform is not the shared room camera. Check the final
bodies through the shared scene camera and preserve dense depth, confidence,
intrinsics and frame mappings. Own-camera reprojection is insufficient evidence.

Kimodo completion is implemented but disabled by default. Use it only for an
explicit completion experiment with observed-action text. A failed contact fit
or low keypoint count alone does not authorize action replacement. Optional
[completion details](references/source-motion.md#v2-and-optional-generated-motion) and
[Kimodo](../kimodo-body-motion/SKILL.md) apply only to authorized generated work.

## Deliver and verify

Open the authored room in background Blender and save a distinct output, preserving
materials, actors, requested camera and timing. The pilot reference-mesh builder
clears its scene and is not an importer for an authored room. Resample rotations
before skinning when FPS changes; bake explicit actor visibility at exits.

Reopen the saved scene, check all declared actors over all active frames, inspect
representative source/room mesh views and fully decode delivered videos with
frame/timing checks. V2 execution or a diagnostic preview is not acceptance.
Finish the task's [acceptance and selected delivery](../../../docs/WORKFLOW_ACCEPTANCE.md),
keeping numerical checks, visual review and remaining approximations explicit.

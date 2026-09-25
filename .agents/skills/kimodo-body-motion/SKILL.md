---
name: kimodo-body-motion
description: Generate and review new human or native G1 motions with Kimodo, including object-state interactions, constrained subsequences and scene playback. Use for generation, model-call debugging and motion/contact comparisons; use GVHMR for reconstructing observed people.
---

# Kimodo body motion

Current source-person default: use [GVHMR](../gvhmr-body-reconstruction/SKILL.md)
for visible source motion, then room alignment and import into the authored Blender
room. Keep existing Blender room modeling; Pi3X is a reference. Kimodo/SAM guidance
below applies to generated new/changed actions or documented fallback. A requested
complete interaction includes scene placement, simultaneous hand/support contact
refinement, validation and the updated viewer; generation alone is not delivery.

For model calls, multi-segment interactions, G1, or implausible generated motion,
read [verified calling and validation lessons](references/call-and-validation.md).
It covers actual text/constraint receipts, per-call local frames, implicit height
keys, native human/G1 differences, stance repair and batch-wide output selection.
The shared frame adapter is `src/aha3d/motion/kimodo_frame.py`.

For new scene interactions, first judge whether each interval is driven by
whole-body travel, torso/upper-body motion, upper-arm/elbow articulation, hand
motion, or a mixture. Derive root travel from reach, support and clearance; do
not copy hand/object displacement by default. Keep text and numerical constraints
consistent with that judgment. An enforced root/contact equality is not evidence
of natural motion. Before revising generated interactions, read the
[chair-interaction planning lesson](../../../docs/lessons/interaction-motion-planning.md).

For requested source-contact repair, use **contact > source action/style > image
alignment**. Discover and review contact/release intervals against the source,
associate a body patch with the actual finite object/support surface, and keep
targets in the same room basis as the trajectory. Begin with fixed-body placement
correction when that can satisfy the targets. Whole-body translation may improve
penetration. Do not modify joint poses to remove collisions or run human leg
repair/IK. Source-supported articulated upper-body repair follows the motion
policy; an infeasible contact does not authorize generated action replacement. Use Kimodo for authorized changed actions or the explicit completion
fallback, not merely because source reconstruction needs refinement. See
[tracking, trajectory and contact constraints](../../../docs/HUMAN_TRACKING_AND_TRAJECTORY.md).
The implemented `tools/kimodo/contact_edit.py` experiment accepts native joint
targets, mandatory text, optional warm-start motion and a hashed clean-prediction
contact callback. Final decoded mesh contact and visible-part/transition checks
remain necessary; a denoising constraint does not guarantee exact contact.
Keep source timing and style, acquisition/release and support-relative slip in
the comparison. Simultaneous hand/foot targets may be infeasible for root-only
correction; do not change stature or silently drop one contact to report success.

A confirmed source-frame exit ends the tracked actor and hides its baked body.
Do not generate a continuation for that departed actor. Temporary occlusion is
different: the completion contract below still requires visible-part constraints
and action text. Preserve `track_active` through any generated candidate/import.

For explicitly requested occlusion-completion research, read
[completion modes](references/completion.md). Partial-body preservation and
whole-body gap replacement have different input contracts; neither is enabled
by a contact failure or low-confidence observations alone.

Project root: `${INDOOR_PROJECT_ROOT}`. The human branch uses body-only SMPL-X with
no facial expression animation. G1 uses its native checkpoint, skeleton and rigid
link meshes, not a resized human. This skill generates new actions; source-person
reconstruction belongs to the GVHMR skill.

Follow the [motion control policy](../../../docs/MOTION_CONTROLS.md):
**root > hands >= feet > text-only** for source-informed Kimodo generation. Use reviewed source
references and deliver continuous, source-informed approximate motion. Text supplies
semantics; document material reference limitations. Use the SAM skill for reference
inputs. External arm IK and timed post-generation facing edits remain retired.

- Use `bash tools/indoor run SCENE --recipe NAME` for new runs. The project-root `docs/PIPELINE.md` documents recipes, timing, stage reuse and validation. `walk_generate` is the existing five-second / 24 fps example.
- For another action, trajectory, person placement or duration, read [motion variants](references/motion.md). Keep original motion and the room source, and make a new output variant.
- For mesh/joint correspondence, camera projection, data reuse or tracking accuracy, read [tracking schema](references/tracking.md). A saved mesh cache supports synthetic tracking without estimating a body from real video.

Use the configured project GPU runtime for inference/skinning and the documented
Blender runtime on the local workstation GPU. The Llama encoder and Kimodo must
fit that device (validated only on 96 GB; see
[runtime](../../../kimodo_blender/RUNTIME.md) for 24 GB options); do not infer
installation or capacity from a historical example.

Resample rotations before skinning. Retain fixed topology and matching frame timestamps when exporting tracks. After changing an action/path, check floor contact, person/furniture clearance and camera framing for the requested motion; a previously valid straight walk does not validate another route.

The final room `.blend` uses baked shape keys and is self-contained for playback. Keep the separate rig `.blend` when later skeletal editing is useful. If the pose, placement or camera changes, regenerate tracking from the final evaluated scene.

For user-facing human motion previews, default to the actual SMPL-X mesh, as
requested in [preferences](../../../docs/PREFERENCES.md). The shared
`python -m aha3d.motion.preview --motion ... --out ...` now defaults to
mesh, using deployed skinning and a fixed viewing direction to expose facing.
Use `--baseline` for side-by-side comparison. `--representation skeleton` is an
explicit diagnostic option. Mesh previews resample rotations before skinning,
follow pelvis XY for display, preserve heading and vertical motion, and do not
establish furniture contact. Claim the output video and its sibling assets folder.

For independent actor iterations, `plan`, `prepare` and `run` accept `--motion-only`
with `generate` or `native` mode. They snapshot motion inputs and stop after skinning
without opening or copying a room; status remains `staged`. Use the
[scene workflow](../../../docs/SCENE_WORKFLOW.md) for stable person IDs, configured
multi-person assembly and all-person saved-scene checks. A single-body pipeline
report does not establish that every actor was checked.

When travel distance or long-duration support is uncertain, use the workflow's
`execute --until motion` and `aha3d.motion.diagnostics` before skinning.
Review root travel, height drift and segment joins against the intended action;
optional limits are scene-specific, never a physical-motion certificate. Keep a
continuous prompt for a continuous action when joins damage the route; use bounded
segments when sustained actions drift, with only necessary native support keys.
Inspect actual mesh facing/contact and source-camera framing afterwards. Use the
ensemble's constant world-space `z_offset` for origin placement without another
handwritten shifted-cache script.

Respect the deployed model's **10-second maximum per prompt** (300 native frames
at 30 fps), documented in its model card (historical or external input; omitted from this bundle).
Longer clips need multiple native prompt segments. In the direct Python interface,
pass a list of complete prompt strings and matching integer frame counts; inspect
the installed CLI/recipe conversion when using a string-based wrapper. Do not
assume punctuation alone creates the intended subsequences. The shared recipe
validator rejects oversized segments before generation.
Reference 33's rejected single 15.015-second candidates exceeded this supported
range and are not evidence that a valid 10-second segment is inherently unstable.
Within the limit, choose splits by action and inspect motion; do not universally
shorten segments to five seconds. Passing the duration check does not guarantee
route length, foot support or transition quality.

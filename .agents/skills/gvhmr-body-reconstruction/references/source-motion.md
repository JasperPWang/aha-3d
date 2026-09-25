# Source motion operations

Read the relevant section for tracking, alignment, contact fitting or scene import.
The current defaults and authorization boundary are in the skill entrypoint and
[motion policy](../../../../docs/MOTION_CONTROLS.md).

## Actor tracking and track termination

Review the intended actor in source frames before initializing SAMURAI. Replace
GVHMR's default tracking input **before** running mask-conditioned PMPose (default), image features and
GVHMR with `tools/gvhmr/samurai_reconstruct.py`; a new overlay on an old motion
cache is not a tracking experiment. Preserve raw masks and any reviewed derivative.

When the actor is confirmed fully out of frame, end that tracking segment and
hide its body from that frame onward. Do not extrapolate boxes, infer a moving
tail or ask Kimodo to complete the departed person. Preserve the full scene and
camera duration with explicit `track_active` metadata. Interior occlusion and
initial missing masks are not proof of exit. Partial cropping remains active;
reentry starts a new reviewed segment. Check the source at the exit boundary.

For source-fidelity or contact investigations, select one or two reference
clips that exhibit the relevant challenge. Preserve raw tracker IDs
and detection support before box interpolation; dense boxes cannot establish
visibility. Report per-joint/body-part support and time-window errors using
`tools/gvhmr/motion_quality.py`. Prefer the upstream mesh-regressed COCO17 joints
for detector comparison, with exact full-image coordinates and timestamps. PMPose
is an inference input, so agreement measures consistency, not independent truth.
Unknown/hidden observations remain unknown even when detector scores are high.
Keep native-camera and independently aligned room-camera checks separate.

Sitting and touching need the actual corresponding support surface and reviewed
contact/release events; the existing flat-floor leg solver does not support seat
or hand contact. Evaluate body-surface gap, penetration and support-relative slip,
and label hidden contact area uncertain. Neither GVHMR body output nor the
deployed 22-joint Kimodo skeleton establishes source finger articulation.
Kimodo gap completion and low-noise editing are implemented experiments in the
audit, not accepted universal replacement routes. Preserve generated-versus-estimated provenance
per interval and check visible wrists after placement changes.
For the partial-body preservation experiment, require constraints on all visible body
parts throughout the affected interval and an explicit action text prompt.
Preserve visible motion and original motion outside the interval; verify the
final output, since stock Kimodo conditioning is not an exact preservation
guarantee. Follow the audit's required-input contract; endpoints alone do not
satisfy it.

## Source motion and room basis

Read the [installation guide](../../../../docs/install/gvhmr.md) to install code and models,
and the [deployment and pilot guide](../../../../docs/GVHMR_BEDLAM2.md) for the
installed runtime, weights, commands and evidence. Use the documented local runtime
with claimed output paths; preserve the compatible GVHMR environment and
licensed SMPL/SMPL-X assets. Its layered Python is distinct from the Kimodo
runtime. Choose static/moving camera from the actual shot, not as a speed shortcut.
Keep raw predictions, source hashes, native timestamps, intrinsics and overlays.
Split cuts; review identity, whole-body visibility and full-clip action coverage.
Do not treat the single-person pilot as a multi-person association implementation.

Room work continues through [Pi3X references](../../pi3x-scene-reference/SKILL.md)
and the existing [Blender modeling workflow](../../blender-roomkit/SKILL.md): author
editable room geometry and reuse furniture/material assets. Pi3X surfaces are
reference and alignment evidence; they do not replace the modeled room.

Align the native global motion to the same-shot camera/room basis, checking the
floor against static source regions. Keep uniform scale explicit, transform room
points and camera translations consistently, and record any additional transform
from Pi3X coordinates to the authored Blender room. Camera-up alone is not a floor.
Never reuse reference 30's floor patches, masks or fitted transform for another shot.
The upstream global preview recenters the body and is not a calibrated room frame.

Initialize with one fixed rigid same-shot alignment at body scale 1, then use
default v2 and contact refinement under the [motion policy](../../../../docs/MOTION_CONTROLS.md).
For explicitly requested trajectory refinement, use the source-bound depth workflow:
fit trajectory scale and XYZ translation, then a smooth root residual only when
supported observations justify it. Add the same per-frame offset to all vertices
and joints; keep body dimensions, local articulation and native heading intact.
Use actor-mask interior depth near reviewed hips or shoulders; visible clothing
depth is not a pelvis center. Check axial-depth, camera-pose and room-basis conventions.

Support a separate constant vertical translation in room Z, positive upward,
for the affected actor. Choose it from reviewed support intervals, then recheck
all requested contacts. A vertical shift can fix floor origin and break a hand
or seat contact; solve conflicting constraints together or retain the conflict.
Do not apply a second grounding shift implicitly during Blender import.
The older `run_contact.sh` manifest also supports `vertical_translation_m`;
its native-preserving default does not run the new trajectory solver automatically.

Use `tools/gvhmr/run_contact.sh --placement-only` for the legacy CPU placement
diagnosis; this flag does not belong to the new trajectory CLI. Native-parameter cache reproduction and
actual source-placement checks remain required; diagnostic temporal probes never
become corrections. Resample rotations before skinning. The legacy `align_room.py`
similarity fit is for historical pilot reproduction, not the current native-unit
route. The old leg solver is historical and excluded from current reconstruction.

## Multi-person scale gate

Preserve native human dimensions and nominal metric units: **body scale is 1**.
A trajectory scale changes the distances traveled by the pelvis; it does not
resize the person. Do not fit independent or shared body sizes to source projection.
Keep the scene/camera basis common across actors. Near-stationary motion cannot
identify a trajectory scale reliably; use translation-only or keep the baseline.

## Full-pipeline contact refinement

For requested contact repair, prioritize **contact, then source action/style,
then image alignment**. Find source contact/release intervals, the anatomical
body patch and the corresponding finite authored support surface. Record which
contacts are observed, inferred or unknown. Review the room against static source
evidence before using it as a target; do not move furniture to meet a bad hand pose.

Use `smooth_scene_contact` with a source-bound `scene_constraints_file` to include
reviewed object contacts and predicted GVHMR foot contacts. Whole-body translation
may improve penetration; collision-driven joint modification remains prohibited.
Evaluate all-active floor/object intersections and source correspondence.
Report the finite/convex proxy scope and preserve the authored geometry. Inspect
positive support clearance as well as penetration: lifting the body can reduce
collisions while worsening grounded walking. Check corresponding patch-point slip;
a stationary patch centroid alone does not rule out rotation-induced sliding.

Use the trajectory solver's contact constraints for placement errors that can be
repaired while retaining articulation. Penalize contact gap, penetration and,
for a reviewed planted interval, support-relative slip; regularize correction
velocity/acceleration and ramp contact acquisition/release. A solver return code
does not establish contact: measure the final mesh and finite object, including
noncontact collisions. Root-only correction can be infeasible for simultaneous
hand and foot targets. Keep that failure explicit instead of distorting body size.
Check ground clearance and unintended object intersection over **all active
frames**, including source-occluded/cropped intervals. A local contact improvement
does not justify adopting a candidate that creates larger floor errors elsewhere;
retain the more stable baseline and label the contact candidate rejected.

Only when the task authorizes generated motion, action replacement or a specified
Kimodo experiment, use the [Kimodo skill](../../kimodo-body-motion/SKILL.md). A failed
contact fit alone does not authorize that route. Its requirements include: action text, visible-part
preservation and native joint/contact targets, followed by final contact and
transition checks. Keep generated intervals labeled. The older flat-floor leg
solver is excluded from this workflow and archived in [contact refinement](../../../../docs/CONTACT_REFINEMENT.md).
Never use per-frame viewing-ray floor snapping or revive retired external arm IK.

## Import into the modeled room

Open the saved authored room in background Blender and write a distinct output.
Use the shared [body cache importer](../../../../src/aha3d/blender/body.py)
(`import_cache`) or the existing ensemble workflow to add the aligned body. Keep
materials, furniture, cabinet animation, other actors and the requested camera.
Use stable person IDs and bake `track_active` as constant visibility keys. Exclude
inactive padding from contact/visibility metrics and synthetic observations.
If the authored room uses another basis, apply its recorded
transform to vertices/joints before import; do not hand-place only the first frame.

The pilot `tools/gvhmr/import_room_blender.py` **clears the scene and builds a Pi3X
reference-mesh demonstration**. Do not use its build mode on the modeled room.
Reuse its validation approach or the shared import/ensemble helpers instead.
Source-camera alignment does not by itself request replacing or animating the
room's delivery camera. Add source-camera playback only when requested.

Preserve duration. If the room uses another FPS, resample native rotations and
translations before skinning; do not relabel the 246-frame / 30 fps pilot as 24 fps.
Keep fixed topology, raw parameters and aligned mesh caches. Bake playback without
requiring Torch, model weights, an add-on or startup handlers in the final file.

Reopen the saved scene and check every actor's evaluated mesh and requested camera
across all output frames, including immediately before/at/after each exit. Review representative source comparisons and room views
for scale, heading, trajectory and framing; fully decode delivered videos and
verify frame count/FPS/duration. Retain alignment, validation and visual-review
reports in the task handoff. Room geometry holes in a diagnostic preview must not
be presented as completion of the separate Blender modeling stage.

## V2 and optional generated motion

For full source-person reconstruction, use the default
[full world-postopt v2 pipeline](../../../../docs/WORLD_POSTOPT.md). Its default full
command snapshots the implementation and runs reviewed tracking, bbox/lifecycle,
PMPose/GVHMR, dense Pi3X, adaptation, v2 and review through the human-experiment
runner. Do not reduce a full-pipeline request to cached-input post-optimization.
Compare against both a fixed scale-1 native
alignment and the camera-lifted initialization. Always report camera path length
and fixed-camera reprojection beside foot slip: v2 can absorb foot motion into
camera drift while preserving its own-camera reprojection. Default v2 execution
does not establish shared-scene acceptance or select a final delivery.

Use [Kimodo](../../kimodo-body-motion/SKILL.md) for new actions, intentional motion
changes, text-only generation or an authorized fallback when source estimation is
unusable. [SAM 3D Body](../../sam3d-motion-reference/SKILL.md) supplies optional reviewed
sparse guidance for that generated route. Do not run SAM plus Kimodo as mandatory
stages after a usable GVHMR estimate. Preserve method/provenance per actor and
explain a fallback instead of labeling generated motion as source reconstruction.


For the default scene-ground route, prepare the full
[world pipeline](../../../../docs/WORLD_POSTOPT.md) with an accepted scene-ground prior
and skip Kimodo completion by default. Ground/upright enter GVHMR's world
reconstruction and v2; do not fit another floor from body predictions. The owner
found current Kimodo results visually unsatisfactory. Retain GVHMR estimates in
low-evidence frames without claiming their accuracy. Only explicit
`--kimodo-completion` plus observed action text enables the completion experiment:
PMPose evidence below five reliable keypoints triggers generation with three
reliable frames on each side, falling back to two per side. No valid dual boundary means an unresolved interval,
not a generated continuation. Check source-shaped mesh joins and label generated
frames before considering scene delivery.

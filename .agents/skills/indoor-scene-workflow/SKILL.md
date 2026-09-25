---
name: indoor-scene-workflow
description: Coordinate video-to-room reconstruction from Pi3X references through an editable room, source-person tracking and motion, optional camera animation, and validated scene delivery. Use for complete scene requests or resuming their stages.
---

# Indoor scene workflow

For source people, follow [motion controls](../../../docs/MOTION_CONTROLS.md)
and [GVHMR](../gvhmr-body-reconstruction/SKILL.md). Preserve native motion with
fixed whole-clip rigid initial alignment at scale 1. Full reconstruction requests
include scene position anchoring, default v2 world post-optimization,
finite-object and foot-ground contact refinement,
validation and final integrated delivery. Follow the
[completion contract](../../../docs/MOTION_CONTROLS.md#full-pipeline-completion-contract);
do not stop at diagnostic motion or weaken scope after a failed stage. Kimodo/SAM
references apply to new/changed actions or documented generated fallback.

Use the configured tracking frontend for the reviewed actor (SAM3 in the full
world pipeline, SAMURAI for its explicit legacy route), then mask-conditioned **PMPose**
(the default 2D detector) before fresh GVHMR inference. See the
[whole pipeline](../../../docs/REAL2SIM_PIPELINE.md) for runtime configuration,
default v2 processing and the implemented endpoint-constrained Kimodo completion
of low-evidence intervals. Kimodo completion is disabled unless explicitly requested.
Keep raw masks and reviewed physical exits separate from bbox support. Hide the
actor after confirmed exit while preserving full scene duration. Pi3X remains a
reference for the editable room; requested contacts use actual authored supports.

Before downstream reconstruction, claim the scene/delivery paths and
[initialize or bind acceptance scope](../../../docs/WORKFLOW_ACCEPTANCE.md#declare-scope-before-downstream-work).
The appearance brief below is separate from acceptance registration. Keep current
user mismatches in the acceptance ledger; a narrative handoff cannot close them.

Use [human automation](../../../docs/HUMAN_AUTOMATION.md) for repeated source-motion
experiments: freeze reviewed decisions, execute resumable configured stages, inspect
selected source/scene evidence and skip full rendering after numerical rejection.
Keep reconstruction cache reuse distinct from new model inference and retain the
existing editable-room authoring and final visual-review stages.


Use the [staged workflow](../../../docs/SCENE_WORKFLOW.md) as the shared entry point.
It contains runnable commands, configuration examples, reuse boundaries and actual
validation evidence. Reusable code belongs in `src/aha3d/`; keep inferred
room geometry, actor decisions and source selections in the scene workspace.

Before new scene work, use the [requirements entry](../../../docs/SCENE_REQUESTS.md)
and its [opening questions](../../../docs/SCENE_REQUESTS.md#opening-questions) to
establish included components and geometric fidelity. Video delivery bundles the
editable scene and preview stills; an interactive demo is optional. Honor explicit
static scope. Apply the fidelity scope and X-ray repair rules in
[layout inspection](../../../docs/LAYOUT_INSPECTION.md#fidelity-and-correction-depth).
Keep async question forms pending until answers arrive; a test intake starts no work.
Use the requirements entry
and `bash tools/indoor intake` to record appearance, delivery/camera, independent
people/cabinet/object motion, timing and final replacement scope. Prefill choices
from conversation and scene state; ask only missing product decisions in short
groups in the user's language. A specific request already authorizes its scope.
Do not repeat intake for a narrow correction whose scope is established, or apply
a static preset over unrelated existing animation. Preserve existing components
explicitly for revisions. Source video alone does not request an animated camera.
Save the request/brief under a claimed run path, then consume its dependency plan
with the stage guidance below. Intake is not a runnable legacy recipe or a job
submission; requested asset variants remain recorded as deferred phase-3 work.
That deferral concerns automatic workflow integration. Authorized narrow model/
material revisions can still use the existing standalone variant interface;
do not stop or deliver unchanged output because of the deferral label. Resolve
contact-sensitive target assets before final person motion and recheck affected
contacts after replacement.

Start with the source and current scene/task state. Interpret the action timeline,
visible people, cuts and requested deliverables before choosing compute. Prefer
Pi3X reference preparation, then room/camera comparison, then source or generated people,
then integrated validation. Analysis of people can happen during the first stage;
expensive body generation usually benefits from a stable room/camera basis.
This order is a working preference, not a reason to repeat valid completed stages.

For source-informed Kimodo generation, follow the control priority
**root > hands >= feet > text-only** in the [motion policy](../../../docs/MOTION_CONTROLS.md).
Establish root routes, then review same-shot SAM hand/foot references before the
final native generation. Text supplies semantics. Record missing/unreliable limb
evidence explicitly; do not silently substitute a text-only final candidate.

## Route by stage

- New or changed source/basis: use [pi3x-scene-reference](../pi3x-scene-reference/SKILL.md).
  Reuse suitable cached predictions for ordinary revisions; an explicitly independent
  rebuild needs new source-based inference. Resolve floor/scale uncertainty before
  committing heights or placements.
- Editable white room and requested camera: use [blender-roomkit](../blender-roomkit/SKILL.md).
  Compare representative source and render views before integrating people. A video
  reference alone does not request an animated camera; existing explicit authorization
  is sufficient when animation is requested.
- Similar human actions: use [kimodo-body-motion](../kimodo-body-motion/SKILL.md).
  Use `--motion-only` for generation/resampling/skinning without room copies. Keep
  stable person IDs and independent caches; review actual meshes and heading.
- Source-person hand/foot references: use [sam3d-motion-reference](../sam3d-motion-reference/SKILL.md)
  when guidance is useful for Kimodo generation. Review sparse useful events and keep observations
  separate from native guidance. Use judgment about reliable source evidence.
- Runtime issues: use [runtime policy](../../../MACHINE.md) and the
  [Kimodo/Blender runtime](../../../kimodo_blender/RUNTIME.md). Batch ready compute
  into one local background run; use stage stops during extended modeling/review
  rather than keeping the GPU busy with waiting work.
- Full rendering: follow [render execution](../../../docs/RENDER_EXECUTION.md)
  after preview acceptance for job waiting and completed-result review.

Load only the specialist references needed at the active stage. Claims, model
storage and execution rules remain in the project coordination/runtime documents.

For a new scene batch, follow the [quality-before-expansion gate](../../../docs/SCENE_WORKFLOW.md#quality-before-batch-expansion):
finish and review one representative room, materials and source-camera preview
before expanding authoring, then keep one unfinished scene per author. GPU queue
capacity does not set authoring breadth. Parallel reference preparation and frozen,
reviewed renders may still share the requested resources. Use actual matched
source frames, separate visual review from builder metadata, and keep rejected
regions/unfinished gates explicit. Do not fill several scene templates before
checking whether the first scene resembles its source.

Use independent agents for bounded ready components when parallel work is requested:
room and action planning may share a reviewed reference basis; later person caches,
cabinet actions and object actions need separate outputs. Assign one integrator
to the combined `.blend`. The intake's dependency groups identify potential
parallelism, not permission to write the same file or submit unbounded GPU jobs.

Use the workflow guide's camera preflight before combining room and motion.
For generated motion, load the Kimodo skill's duration, native-constraint and
preview guidance. For sparse limb observations, load the SAM skill only when
that guidance is needed.

## Integration and delivery

Use parameterized camera, ensemble and comparison helpers from the workflow guide,
and the existing pipeline for immutable snapshots, failed-stage stopping, rendering
resume and complete video checks. An ensemble must be reopened and checked for
**every** declared person; the original single-body pipeline check alone is insufficient.
Configure GPU devices in each Blender render process. Preserve source materials,
exact timing and the common point/camera world transform.
Use `workflow.compare --run` to resolve the recorded video and frozen timing.
Recover a comparison-only failure independently; do not rerender a validated clip
for a filename error. Preserve separate render, all-person, comparison and visual
review evidence in the handoff so another worker can finish interrupted delivery.

Stage reviews are the agent's technical and visual checks within the user's scope;
they do not introduce approval pauses. Continue when evidence supports the next
stage. Keep failures and unreviewed results distinct from delivered results.
From the first blockout, use the layout stage's automatic object-focus packet.
Inspect each fidelity target's isolated X-ray/source and plan/side views before
editing, then require before/after evidence. Keep user findings open
until current before/after evidence closes them; acceptance blockers do not halt
authorized repair. Use [the RoomKit tool router](../blender-roomkit/SKILL.md#choose-the-inspection-tool)
for native outlines versus source masks and the bounded repair loop.

Report approximate generated actions accurately. Collision findings are diagnostics;
do not silently change an intended action/path merely to obtain a zero count. Resolve
visible problems according to the user's priorities and record any approximation.
Deliver the requested video/scene with actual decode, timing, all-person/camera and
visual-review evidence. Workflow improvement or skill maintenance is additional
work only when requested.

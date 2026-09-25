# Unified scene requirements entry

Status: phase 2 implemented for the user's September 10, 2026 request. This entry
collects scope before authoring or expensive work. It produces missing questions,
a durable request and stage dependencies. It does not launch jobs or convert a
high-level request into an executable legacy recipe. Phase 3 will connect asset
variant execution to complete delivery. Implementation handoff (historical or external input; omitted from this bundle).

## Conversation before work

Read current scene/task state and reuse requirements already present in the
conversation. Fill known choices first; ask only material missing choices. The
questions below describe independent axes, so combinations need no new preset.

| Topic | Choices to establish |
| --- | --- |
| Appearance | Whitebox, or materials; retain real materials beneath clay overrides |
| Fidelity | Approximate, major-object alignment, precise, or precise only for named targets |
| Delivery and camera | Editable scene + video + preview stills by default; optional interactive demo; inspection, source-video trajectory, custom animated path, or existing saved camera |
| Motion | Independently choose people, cabinet doors/drawers, and other objects; each can be absent/static, newly authored, or preserved from a saved scene |
| Timing and action | Follow the source, or requested duration and fps; describe relevant actors/actions and any required interactions |
| Final variants | No replacement, model replacement, material replacement, or both; record intended categories when known |

### Opening questions

Ask only missing choices, in short groups:

1. **What should the reconstruction include?** Start with editable whitebox room
   geometry; independently offer source camera, materials/textures, people and
   object motion. Example packages: whitebox only; whitebox + source camera;
   whitebox + source camera + materials/textures; the same plus people. Accept
   custom combinations; packages are shortcuts, not mutually dependent features.
   A whitebox-only component choice does not imply stills-only delivery; the legacy
   static presets are for explicitly static requests.
2. **How precisely should geometry match?** Approximate; major objects (structure,
   main furniture and salient lamps, with small surface decor free); all objects;
   or named targets. Follow [layout review](LAYOUT_INSPECTION.md#fidelity-and-correction-depth).
3. **Also include an interactive demo?** Standard video delivery already includes
   the editable scene and representative preview stills. Do not present stills as
   an alternative to video in the standard intake. Honor explicit static/stills-only
   requests and established delivery scope.

Ask conditional follow-ups only when relevant: original versus custom camera;
materials approximating colors/finishes versus closely matching visible textures;
static people, reconstructed source motion or newly generated actions; which objects
move and when. Source people follow [motion controls](MOTION_CONTROLS.md), not an
implicit generated-action preset. Record material intent in `details.appearance`.
If matching priority is unclear, ask whether source views, dimensions across views,
or both matter; request a known measurement only when physical accuracy needs it.
Whitebox appearance does not imply approximate geometry. Do not promise exact
unseen geometry from a video.

When the active environment offers a question tool, use its actual schema and
availability rules. With `request_user_input_async`, submit the short group and
keep the turn active while answers are pending; continue independent read-only
work or use bounded waits. Do not immediately send a final response after opening
questions. A preselected option or elapsed wait is not an answer. If forms are
unavailable, ask the same concise questions in chat. A test intake must not start
reconstruction or bind its sample answers to a real scene.

Use short grouped questions in the user's language. Do not expose schema keys,
internal scene IDs, frame arithmetic or low-level rig choices unless useful.
Derive the scene ID/source path from the existing task/catalog where possible.
Natural-language understanding remains with the agent: the helper validates
structured answers and does not parse chat. Ask at most the useful few questions
at a time; continue independent read-only work while a necessary answer is pending.

A specific request is already authorization for its scope. Do not require a
second approval after answers are complete. A video reference alone does not ask
for camera animation. For narrow revisions, prefill established context: e.g.
preserve an existing camera/people/actions when only materials change. Do not use
a new-static-scene preset to erase unrelated existing animation. If the user
clearly requests only a static whitebox, the whitebox preset establishes that
scope; no need to ask about adding every available animation feature.

## Entry command and saved checkpoints

The command uses ordinary small JSON files without runtime discovery, Blender,
models or hashing source binaries. Claim paths before using `--out`; run
regression checks locally.

```bash
export PYTHONDONTWRITEBYTECODE=1
bash tools/indoor intake
bash tools/indoor intake --preset source_camera
bash tools/indoor intake --request configs/requests/whitebox.json
bash tools/indoor intake --request configs/requests/source_camera_actions.json \
  --out runs/open_plan_group_walk_g0055/REQUEST_ID/intake
```

The checked-in requests are examples, not instructions to start those scenes.
The action/variant example explicitly includes a synthetic cabinet action.
Use a new claimed run/ID for actual work. Without `--out`, stdout contains the
report and nothing is written. `--out` must be a new directory; existing bundles
are never overwritten. It contains:

- `request.json`: resolved context, suitable for resuming collection.
- `intake.json`: questions, applied defaults, stage dependencies, parallel groups
  and deferred requested work; execution stays `not_started`.
- `BRIEF.md`: a readable scope and dependency summary.

To resume, put only changed/new fields in an answers JSON:

```bash
bash tools/indoor intake --request runs/SCENE/REQUEST_ID/intake/request.json \
  --answers answers.json --out runs/SCENE/REQUEST_ID/intake-v2
```

Answers recursively merge objects and replace explicit scalar/list values.
Switching `timing.mode` replaces the former timing object. A new explicit duration
replaces the old frame count while retaining unchanged fps/start; a new frame
count replaces the old duration. Supplying both still requires exact agreement.
An explicit value always wins over a preset. Presets only fill absent fields;
switching the preset does not erase existing answers. Applied defaults are
reported for that invocation; persisted resolved values become established
context on resume. Incomplete requests return `needs_input` with stable question
fields and no stage plan. Malformed/contradictory answers return a CLI error
before creating an output directory. Complete ones return `ready_for_authoring`,
which is not a claim that source files, rendering or video validation have passed.

## Request schema v1

Older requests without fidelity remain readable but return `needs_input` until
existing intent is recorded or the missing choice is answered. Never silently
downgrade a resumed task; retain its acceptance scope and open findings. The helper
records a plan, not runtime enforcement of the fidelity loop. The agent must carry
these obligations into authoring and acceptance evidence. Source-person/static-person
choices beyond the helper's legacy people enum must be recorded in the brief and
routed under motion controls; do not encode source reconstruction as `approximate`.

The strict [module](../src/aha3d/workflow/intake.py) accepts:

| Field | Meaning |
| --- | --- |
| `schema_version`, `scene` | Version 1 and the stable target scene ID |
| `inputs` | Optional `video`, `images` (nonempty path list), `source_scene`; at least one input needed |
| `preset` | Optional `whitebox`, `materials`, `whitebox_people`, `source_camera` |
| `reuse` | `reuse_allowed` default, or `independent` fresh source-based rebuild |
| `appearance` | `whitebox` or `materials` |
| `delivery` | `video` by default, including editable scene and preview stills; `stills` for explicit static scope |
| `fidelity` | Required `mode`: `approximate`, `major_objects`, `precise`, or `selective`; selective requires nonempty `targets` |
| `interactive_demo` | Optional boolean, default false; adds browser-demo delivery |
| `camera` | `inspection`, `source_trajectory`, `custom`, `existing` |
| `people` | `none`, `approximate`, `existing` |
| `cabinets`, `objects` | Independently `none`, `animate`, `existing` |
| `details` | Optional text under `appearance`, `people`, `cabinets`, `objects`, `camera`; new actions/custom camera need intent descriptions |
| `timing` | `mode: source`, or `mode: explicit` with rational `fps`, `frames` or `duration_seconds`, optional positive `start` |
| `variants` | Explicit boolean `models` and `materials`, optional `notes` |

Whitebox/material presets select static inspection output without newly added
people or motion. Whitebox-people selects a fixed-camera whitebox video with
approximately generated people. Source-camera selects whitebox video and the
source trajectory, leaving all three motion choices to the caller. Every preset asks for missing fidelity; static presets remain explicit stills-only shortcuts. Every preset
allows independent overrides and asks about variants if they are not already known.

Video or requested people/object/cabinet motion needs timing. Source timing
remains `{"mode":"source"}` until the source stage reads media/scene metadata;
no guessed 5-second/24-fps values are introduced. Explicit seconds times fps must
give an integral frame count, and an accompanying frame count must agree exactly.
Canonical output stores rational fps and integer frames, without a rounded derived
duration. For instance, 208 frames at `24000/1001` remain exactly that count/rate.

New source-trajectory/custom-camera requests use video delivery in intake v1;
use inspection for static source comparison. Existing cameras may be preserved
for stills. This entry's new-camera restriction does not invalidate legacy recipes
that render selected frames from animation. Source trajectory needs a video;
existing components need a saved scene. An independent rebuild cannot also reuse
a scene implementation or its existing motion/camera.

## From requirements to parallel authoring

Consume the resolved request in the [staged workflow](SCENE_WORKFLOW.md), claim
distinct outputs and author stage-specific configs. A request is not a
[pipeline recipe](PIPELINE.md): legacy recipes default to video/body preservation
and cannot represent all these independent choices. Explicitly implement requested
exclusions when reusing a source; do not equate `body.mode: keep` with no person.

The report emits a dependency graph and topological `parallel_groups`. Reference
preparation establishes the common basis. Room work and people/action planning
can proceed independently after that basis exists. Expensive people generation
waits for room/camera review; person caches, cabinet motion and other object motion
can then be authored in separate outputs. One integrator writes the combined
scene and verifies every requested component after reopening. Respect source
reuse and orientation/support contracts throughout. This is an authoring plan,
not an automatic agent dispatcher or a reason to keep idle GPUs allocated.

Technical and visual checks remain agent work, not user approval gates. Reuse
valid completed stages in resumed tasks after checking provenance instead of
blindly repeating the graph. Every final delivery still needs appropriate scene,
camera, person, still/video and actual visual evidence.

Requested model/material variants appear under `deferred` with status
`deferred_phase_3`; they are not applied, discarded or reported as complete.
The base-scene output does not satisfy that deferred part of the user's request.
The [variant interface](SCENE_VARIANTS.md) remains separately usable within its
existing scope; complete workflow execution is the next phase.

This deferral concerns automatic integration, not removal of working capabilities
or a new approval requirement. For an authorized narrow material/model revision,
route directly to the existing standalone interface and validate the requested
revision. Do not deliver an unchanged base video or stop solely because its intake
records a deferred automation step. Base appearance in `details.appearance` and
additional model/material variants are distinct scope; preserve what the user
actually requested rather than classifying every material edit as a future task.

When people sit on or otherwise contact replaceable furniture, settle the target
asset and required contact compatibility during action planning, before final
motion generation. Later changes to support/contact geometry require affected
motion checks and possibly regeneration. The intake graph records this authoring
obligation but does not automatically solve contacts or schedule replacement work.

## Validated examples

CPU job `45912939` passed 59 intake/pipeline/workflow/preflight tests and three
real CLI invocations. These validate requirements collection and
planning, not new scene generation or render quality.

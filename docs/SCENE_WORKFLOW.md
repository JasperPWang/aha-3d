# Staged reference-to-scene workflow

Current routing (accepted 2026-09-11): source-video people default to
[GVHMR](../.agents/skills/gvhmr-body-reconstruction/SKILL.md), same-shot room
alignment and import into the authored Blender scene. Room modeling stays with
Pi3X references and the existing Blender/asset workflow. The current source-person
route uses SAMURAI before fresh GVHMR inference and ends/hides a track on confirmed
exit. Preserve body dimensions and local motion; use same-shot depth for supported
trajectory scale/translation and smooth drift correction, with a separate constant
room-Z placement. Requested contact constraints use reviewed source events and
finite authored supports. See [the current executable guide](HUMAN_TRACKING_AND_TRAJECTORY.md).
Kimodo handles new/changed actions or documented
fallback; SAM guidance is optional for that generated route. Historical generated
motion examples below retain their scope and do not override this default.


Status: implemented on 2026-09-09 following the user's request to improve the
completed piano workflow and create a repeatable entry point. Invoke
[$indoor-scene-workflow](../.agents/skills/indoor-scene-workflow/SKILL.md).


## Plan once, consume results at the appropriate stage

Use the [unified requirements entry](SCENE_REQUESTS.md) before new scene work:
`bash tools/indoor intake` records independent appearance, delivery/camera,
people/cabinet/object motion, timing and final replacement requirements. Prefill
known context and ask only missing choices. Its saved request/brief and dependency
groups guide authoring; they do not submit compute or replace executable recipes.
Narrow revisions reuse established scope. Requested asset variants stay explicit
as deferred phase-3 obligations until complete workflow integration is implemented.

Start from [coordination](COORDINATION.md), the scene's `STATE.md`, and the source.
Record a short scene-specific storyboard: source/timing, shot boundaries, actor
IDs, approximate action intervals, important contact/turn moments, visible layout
landmarks, uncertainties and requested outputs. This is an agent reasoning record,
not a new model input format. The piano storyboard (historical or external input; omitted from this bundle)
is an example, not a universal action template.

For source-informed Kimodo generation, the control priority is **root > hands >= feet > text-only**.
Use source-informed root routes and useful SAM hand/foot references; text supplies
semantics. Record material reference limitations and review the generated result.
The [motion policy](MOTION_CONTROLS.md) defines scope; implementation choices remain
with the agent and the specialist tools.

| Stage | Main output | Evidence needed before consuming it |
| --- | --- | --- |
| Source analysis and Pi3X | Cached same-shot RGB/PTS/predictions/cameras; storyboard | Source frames/cuts reviewed, exact timing, identity of source |
| Aligned references | Source-linked dimensions, floor/scale status, common world transform | Reliable static endpoints; floor hypothesis reviewed; independent cross-view observations |
| White room and requested camera | Editable saved room and comparison stills; optional full-rate camera cache | CPU camera preflight; [per-object layout review](#furniture-layout-review-entrypoint), furniture proportions/facing, circulation, occlusions and static support reviewed before people routes and full rendering |
| People | Reviewed SAMURAI identities/exits, native motion, fixed-body trajectories and contact targets | Exact source timing and activity; support evidence; correction smoothness; source style; rotation resampling before skinning |
| Integration | Baked ensemble `.blend`, placed caches and per-person checks | Every active actor present and departed actor hidden; actual room interactions/floor/framing reviewed; camera preserved |
| Delivery | Fully decoded video and final scene, optional comparison | Requested frame count/rate/duration, reopened bodies/camera, representative actual rendered frames |

Analyze people during source analysis so important moments enter Pi3X/SAM source
selection early. Prefer stabilizing the white room and camera basis before costly
motion iterations. A text-generated baseline needed by the native reference adapter
may proceed once its placement basis is known; it is not the default final
reference-guided candidate. Technical and visual stage checks are performed by the agent;
they do not require a new user confirmation. Preserve the user's static/animated
scope and any explicit request for an independent rebuild.

## Furniture layout review entrypoint

When checking furniture position, size, orientation or spacing, use **simplified
colored silhouettes plus per-object highlighting** as the default readable layout
comparison. This belongs to `blender-roomkit`; it is not a separate skill name.
Use it on the first saved blockout and after relevant edits, especially when the
user points out a mismatch. It is useful even when the full overlay is not dense.
Material/front-detail stills, depth panels, source landmarks and measurements
remain complementary; choose a better-supported comparison when silhouettes are
ambiguous and record that choice.

For a saved scene with a matching completed common-frame inspection, run the
following using new output directories (paths are placeholders):

```bash
"$BLENDER_BIN" -b /absolute/model.blend --python-exit-code 1 \
  --python tools/layout_inspection/export_model.py -- \
  --cameras /absolute/cameras.json --out /absolute/new-export
"$PI3X_MESH_PY" -m tools.layout_inspection.object_outline \
  --geometry /absolute/new-export/model.npz --metadata /absolute/new-export/model.json \
  --inspection /absolute/matched-inspection --out /absolute/new-outlines
"$PI3X_MESH_PY" -m tools.layout_inspection.agent_review \
  --outlines /absolute/new-outlines/objects.json --out /absolute/new-agent-review
```

If the common-frame inspection is missing or describes an older scene, first
generate matching evidence using the [layout inspection commands](LAYOUT_INSPECTION.md).
Reuse source predictions and reviewed masks; do not bypass scene/camera hashes.
Pass the review packet's optional `--inventory` and `--source-fit` inputs when
available; absence is reported as unassessed, not accepted. SAM3 is not required
to generate silhouettes or highlight modeled objects.

Read `summary.json` for findings and image paths. Agents can inspect the static
`*_context.png` and finding-driven `focus_*.png` images without browser clicks;
these retain walls and other geometry in gray. The outline `report.html` also
supports interactive object selection. Compare relevant objects in a matched
plan and source-camera RGB views. Keep actual front/back details and depth
evidence where silhouettes cannot establish orientation or occlusion.

On first use or after grouping changes, open a produced image and check its
displayed inventory: complete furniture roots need `furniture/...` classes.
Bare `bed` or `chair` tags are omitted by the default furniture filter. A filtered
preview can be empty despite successful execution. A created HTML/JSON file
does not establish that useful object outlines were inspected.

Record the saved scene revision, inspected image paths, object IDs and remaining
findings. A reported mismatch stays open until supported before/after review;
tool execution alone does not resolve it. Program-first inspection reuses an
unchanged visual review; it does not remove the initial coverage check or final
source-fidelity review. The pipeline layout stage now composes export, outlines and
`agent_review --all-objects` by default. The gate binds their artifacts to the
saved scene/cameras and requires exact-object observations on focus images.
Missing, empty, wrong-object or stale packets cannot authorize acceptance. See
[the object review contract](LAYOUT_INSPECTION.md#object-review-default-and-repair-loop).
This is an agent review requirement, not an additional user approval step.

## Quality before batch expansion

For a new reconstruction batch, complete one representative scene through room,
materials, source-camera comparisons and the requested preview review before
expanding authoring. Keep one unfinished authored scene per worker thereafter.
Free GPU time or queued inputs do not establish modeling capacity. Parallelize
bounded reference preparation or rendering of already reviewed, frozen scenes;
do not generate several rooms and postpone their visual acceptance together.
These are agent reviews within the existing request, not new approval pauses.

Keep a compact scene-specific record of the following decisions:

- **Source coverage:** inspect early, middle, late and newly revealed spaces.
  Inventory major walls, openings, furniture counts, visible fronts and finishes.
  A broad category match or plausible first view does not cover a later hallway.
- **Geometry basis:** preserve the common Pi3X/camera basis. Use eligible surface
  measurements with source endpoints; distinguish observed support from inferred
  hidden bounds. Empty or rejected regions remain unsupported. Raw depth medians,
  glass reflections and isolated pixels do not establish complete object sizes.
- **Assets and materials:** compare available registered assets with the source
  before choosing custom geometry. Record the reason for a custom replacement.
  Preview its silhouette, construction, material scale and finish before repeating
  it. Colored boxes and generic noise remain blockout approximations when the
  requested textured reconstruction needs recognizable furniture and finishes.
  Photographs of art or exterior context need correct projection and provenance;
  a frozen photo is not a reconstructed mirror, glass surface or room interior.
- **Complete objects:** transform one complete semantic root with unique IDs and
  all its parts. Use the root returned by `tag_root`, or group explicit parts with
  `adopt_group`; give already-positioned parts a reviewed floor/mount-centered
  `placement_matrix`, or start with geometry normalized around that origin. Its
  default world-origin pivot is not an inferred furniture pivot. Do not continue
  transforming the mesh child as if it were the placement root. For supported
  upright, static directional objects, declare the trusted actual front and use
  `place_root`/`place_asset` with source-observed facing intent. Follow the
  [orientation contract](ASSET_ORIENTATION.md) for transform restrictions;
  symmetric, tilted or animated objects need appropriate reviewed placement, not
  forced facing metadata. Inspect the seat/backrest, not only a yaw value.
- **Evidence:** pair the actual decoded source frame/PTS with the requested model
  time. Decode missing source frames or fail the comparison; never silently reuse
  a nearby image under the requested frame label. Bind each texture image to its
  real source frame and timestamp. Builders write measurements and check results;
  separate, later visual review names the exact source/render evidence and issues.
  Generated sentences claiming review do not establish that review happened.

Maintain pending, failed or reviewed status separately for source/layout agreement,
placement, camera-cache consistency, material appearance and full-clip preview.
Camera cache agreement does not prove room/source agreement. Standalone scripts
must observe these same gates; bypassing the pipeline does not bypass review.
Keep each revision's saved scene, script/config identity and evidence in distinct
paths. Stop on a failed authoring/validation command before attempting its render;
do not consume a missing or older scene file. Resolve conspicuous defects in the
current scene before starting the next.

## Layout inspection before people and final rendering

Before the expensive complete layout packet, perform the
[early source-relation check](LAYOUT_INSPECTION.md#early-source-relation-check)
on matched source/blockout views. Prioritize user corrections, shared planes,
major silhouettes, facing and repeated-object counts. Fix those relationships
with local diagnostic views before freezing the candidate for complete review.

Use the [common-frame layout inspection](LAYOUT_INSPECTION.md) after authoring the
first white room. Inspect matched top/front/side reference-model overlays and
early/middle/late native source-camera comparisons. Keep SAM3 people excluded
from static reference, glass/mirror separately toggleable, and geometric validity
and missing coverage distinct. Correct material layout errors before body alignment
and full rendering; the agent performs this review without new user approval.

## Reuse boundaries

Newly authored scenes follow the [semantic asset contract](SCENE_VARIANTS.md):
group each complete replaceable object under a stable identity root, tag wall and
floor material roles, and record support relationships for tabletop objects.
Create cabinets with explicit operable layouts so their doors, drawers, interiors
and independent controls remain reusable. Cabinet diversity belongs in the
shared generator/asset recipe. Room-specific scripts configure placement and
action timing. Preserve native articulation when exporting these assets.
Legacy proxy geometry needs an explicit migration before claiming the same
capabilities; names alone are insufficient. This authoring convention does not
add animation to a static-scene request.

| Change | Reuse | Recompute/review |
| --- | --- | --- |
| Diagram labels, grid, colors or display slices | Raw Pi3X predictions and RGB | Presentation/legibility; verify dimensions and camera export stay identical |
| Floor basis or uniform scale | Raw predictions | Aligned points/cameras, dimensions, placements and camera validation |
| Camera or lighting only | Compatible native/resampled/skinned body caches | Assembly, final evaluated calibration/tracks, render and review |
| One actor's prompt/route/required native keys | Room, camera, other actors; same-shot reviewed observations | That actor's generation/resample/skin, ensemble and affected checks |
| SAM event selection or facing interpretation | Same-shot raw observations where suitable | Reviewed selection/native guidance, affected motion and checks |
| Source shot, output cadence or body shape | Only artifacts with matching inputs and timing | Dependent camera/motion/skinning/assembly stages |

For an ordinary correction, record the changed object IDs, dependent neighbors,
changed inputs and affected stages before scheduling work. Use this repair order:

1. Check the changed object and its supports/neighbors in matched source-camera
   crops and a useful plan/side view. Preserve the reviewed camera unless camera
   error is established. Resolve the concrete issue before generating a full packet.
2. Freeze the repaired scene. Complete the required current-candidate layout,
   sampled preview and final reviews once the local repairs pass. A local image
   is diagnostic; it cannot transfer an old whole-scene acceptance to new geometry.
3. Resume failed encoding, decoding or reporting from intact completed frames.
   Resume a malformed image-review response from the unchanged image packet with
   a fresh review output. Neither failure alone requires rendering those images again.
4. Use the existing [pipeline resume/reuse commands](PIPELINE.md#resume-and-reuse)
   for recorded stages. Preserve immutable snapshots and let the runner verify
   dependencies; never relabel stale outputs or edit receipts to force reuse.

Changes to geometry can alter occlusion, shadows, reflection and contact outside
the edited object's crop. Do not assume all other final pixels remain valid.
Material or lighting changes reuse source reconstruction and compatible geometry
diagnostics, but require new affected appearance renders and final acceptance.
Global basis, camera, source or timing changes invalidate their dependent evidence.
Switch between rendering, CPU checks and image review in the same session; do
not restart a background batch solely to change activity.

Do not rerun Pi3X for cosmetic changes or reload dense NPZ members inside a pixel
loop. `NpzFile[key]` reads/decompresses the member each time; the cross-view helper
loads each required member once. See its real-data benchmark in the lesson.
Do not rewrite frozen run snapshots. Use a new variant and verified stage reuse.

Source-colored metric views and full-body SAM crops support recognition before
modeling or choosing constraints. Display slicing changes the drawn samples, not
measurement endpoints. The [colored-reference/leg comparison](lessons/colored-reference-leg-guidance.md)
records the implementation, tested benefits and limits. Sparse native foot
guidance remains an experiment: review visibility, keep a matched baseline,
compare withheld source times, then examine actual skinned floor/sole behavior
before adopting a variant. Better keyed poses alone do not establish better gait.

## Shared commands and configuration

Run preprocessing, hashing, tests, Blender and encoding locally. Source
`kimodo_blender/env.sh`, set `PYTHONDONTWRITEBYTECODE=1`, and export
`PYTHONPATH="$PWD/src"` from the project root. Use installed runtimes from the
specialist references: the Pi3X Python has OpenCV/NumPy/SciPy/Pillow;
the Kimodo Python runs the shared pipeline. Blender executes `bpy` modules.
All output paths below must be distinct, claimed paths under `runs/<scene>/<run>/`.
Replace shell variables with this task's actual inputs; none is a global setting.

### Camera and independent static cross-view checks

After Pi3X and reviewed alignment:

```bash
"$PI3X_PYTHON" -m aha3d.workflow.camera \
  --bundle "$ALIGNED_BUNDLE" --config "$CAMERA_CONFIG" --out "$CAMERA_OUTPUT"
"$PI3X_PYTHON" -m aha3d.workflow.crossview \
  --bundle "$ALIGNED_BUNDLE" --config "$STATIC_REGION_CONFIG" --out "$CROSSVIEW_OUTPUT"
```

Camera configuration (historical or external input; omitted from this bundle)
requires rational timing, output `[width,height]`, `continuous_shot_reviewed: true`
and an endpoint policy. Optional `source_start_seconds` offsets the output sample
clock. `error` rejects samples outside observations; explicit `hold` records their
count. The helper uses PCHIP translations, rotation SLERP and linear intrinsics.
It converts integer-index pixel centers to boundary centers **before** resizing,
preserving off-center principal points. It does not automatically detect cuts or
retime variable-frame-rate footage; split/map those cases explicitly first.

Before a combined room/motion job, check the camera using the planned ensemble
config. Person cache paths can name future outputs; this check does not load them:

```bash
"$PI3X_PYTHON" -m aha3d.workflow.preflight \
  --root "$PWD" --config "$ENSEMBLE_CONFIG" --out "$CAMERA_PREFLIGHT"
```

This checks the complete camera timeline, raster, rigid poses and skew, and predicts
the fixed-pixel-aspect intrinsic residual without Blender. It writes `camera.json`
and exits 2 when the declared tolerance is exceeded. Investigate the convention,
scale or approximation and document any deliberate tolerance choice; do not raise
it automatically. Assembly repeats preflight before scene mutation and retains
the separate all-frame evaluated Blender camera check. Analytic success alone
does not establish Blender playback or source-camera accuracy.

Static region configuration (historical or external input; omitted from this bundle)
uses native source frame IDs, excluded rectangles `[x0,y0,x1,y1]` in processed
pixels, frame pairs, descriptor ratio and confidence thresholds. Adapt masks to
moving people, reflections, source graphics/floor-plan overlays and unreliable regions in the actual source. ORB matches
are selected independently of predicted 3D. Repeated patterns can produce outliers;
these metrics assess consistency, not physical scale or absolute pose accuracy.
Report match count and error per pair, especially weak turns or glass-only pairs;
a pooled low median can hide a poorly supported interval. Review static floor
patches separately from a camera-up fallback or a higher horizontal surface.
Keep `world_transform` rigid in the aligned bundle. Supply any calibrated uniform
scale through the measurement scale interface, applied to points and camera
translations together; do not insert scale into the rotation block. An assumed
camera height is not measured calibration.

### Motion without a room copy

```bash
bash tools/indoor plan "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only
bash tools/indoor run "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only
```

`plan`, `prepare` and `run` support `--motion-only`. Only `generate` and `native`
body modes apply. The existing recipe still names a prospective `.blend`, but that
file need not exist and is not opened, hashed or copied. The run snapshots code,
motion/constraint inputs and runtime identity, then stops after `skin`. Status is
`staged`, never `validated`: no room/video validation has happened. Resume uses the
same frozen scope; create a normal scene run to integrate the cache. `submit`
resumes prepared motion-only runs; `batch` does not currently expose this flag.

For a new uncertain route or long support-sensitive action, split generation from
skinning using existing stage stops. These commands run in the foreground:

```bash
bash tools/indoor prepare "$SCENE_ID" --recipe "$PERSON_RECIPE" --motion-only --run-id "$MOTION_ID"
bash tools/indoor execute "$MOTION_RUN" --until motion
"$KIMODO_ENV/bin/python" -m aha3d.motion.diagnostics \
  --motion "$MOTION_RUN/stages/motion/motion.npz" \
  --recipe "$MOTION_RUN/snapshot/recipe.json" --out "$NATIVE_DIAGNOSTICS"
```

`MOTION_RUN` is `runs/$SCENE_ID/$MOTION_ID`. For `native` mode inspect the supplied
native file directly; there is no generation stage. Diagnostics report native
Y-up root travel, displacement, height range, root steps and prompt-segment joins.
Optional `--max-travel-m`, `--max-root-step-m`, `--min-root-height-m` and
`--max-height-range-m` are scene/action-specific limits: violations write evidence
and exit 2. An unconstrained report is `diagnostic`, not motion acceptance.
Review it before `execute "$MOTION_RUN" --until skin`; free the GPU (stop at a
stage) if further interpretation or authoring will take time. Native FPS defaults to the
matching recipe's `source_fps` or 30, with an explicit override available.

First respect the deployed model's maximum **10 seconds per prompt** (300 native
frames at 30 fps). The shared recipe validator rejects any longer segment and
requires one duration per period-separated prompt before generation. Total clip
duration may exceed 10 seconds through multiple native segments. Reference 33's
first two single 15.015-second candidates exceeded the documented range; that
failure does not establish that valid 10-second generation is insufficient.
Within the supported range, choose segmentation from action changes and candidate
behavior. Reference 33 ultimately used bounded segments plus sparse native support;
reference 32's 8.675-second continuous route improved with one prompt after joins
disrupted travel. Neither establishes a universal five-second segment rule.
Inspect segment boundaries and critical source times in the actual mesh and
source-camera view after skinning; root diagnostics cannot establish facing,
foot contact or whether a doorway hides the person.

Use the reviewed root route and hand/foot references under the stated priority;
text describes the surrounding action. A path alone does not specify forward or
backward walking. Inspect actual mesh facing and necessary native heading. Native
hand/foot keys also carry root/heading constraints: reconcile them with the route
before generation. Keep these choices separate from room geometry and do not use retired external arm IK or
keyed facing corrections. Support-surface and collision diagnostics do not justify
automatically rerouting an intended action. Record any accepted approximation.

### Parameterized room and multi-person assembly

Ensemble configuration (historical or external input; omitted from this bundle)
contains timing, image size, optional camera cache, unique integer person IDs and
labels, input cache paths, constant scale/yaw, initial pelvis `anchor_xy`, optional
`z_offset` or `ground_z`, preview frame IDs and validation policy. Paths resolve against
`--root`; ID `1` maps to `Person_001_Body`. The config validator rejects unknown
fields, duplicate identities and incompatible cache timing. An unlisted existing
person fails room extraction rather than being silently omitted.

`z_offset` is one constant vertical translation in **world metres after scale**,
recorded in the placement matrix and assembly report. Omit both vertical fields
to retain the original placement. For example, a previous whole-cache raw Z shift
of 0.02 m at scale 0.9 is equivalent to `"z_offset": 0.018` with the original
cache; do not apply both shifts. This avoids writing another large derivative
cache just to shift its origin and preserves native vertical differences.

`ground_z` is an explicit per-frame whole-body vertical correction to that lowest
vertex height. Omit it to preserve vertical motion. It is appropriate only for the
reviewed flat support case, not stairs, jumps or precise foot-contact fitting.
A child's uniform scale is approximate stature, not fitted pediatric morphology.
`z_offset` and non-null `ground_z` are mutually exclusive. A constant offset can
leave airborne or penetrating soles and does not repair gait or certify contact.

```bash
"$BLENDER" -b "$SAVED_SOURCE" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage room --out "$ROOM_OUTPUT" --preview
"$BLENDER" -b "$ROOM_OUTPUT/scene.blend" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage assemble --out "$ENSEMBLE_OUTPUT" --preview
"$BLENDER" -b "$ENSEMBLE_OUTPUT/scene.blend" -t 8 --python-exit-code 1 \
  --python src/aha3d/blender/ensemble.py -- --root "$PWD" \
  --config "$ENSEMBLE_CONFIG" --stage verify --assembly "$ENSEMBLE_OUTPUT" \
  --out "$ENSEMBLE_CHECKS"
```

A newly built room can go directly to `assemble` after room/camera review. `room`
is useful for separating an existing scene: it removes only declared people and
preserves geometry/materials. It does not infer room geometry; author that with
RoomKit and source-linked measurements. Generic helpers do not contain furniture
names, room dimensions, actor routes or scene-specific geometry corrections.
Compare furniture footprints, facing and usable aisles against source views before
committing people routes. Where an aisle is ambiguous, a plan or oblique preview
can separate a furniture-layout error from a motion problem; keep the room and
camera in their shared source basis.
Check evaluated support for major furniture and props during this room preview,
before full rendering. A useful low-side/cutaway view needs visible support planes,
working lighting and adequate framing; a saved black or obscured image is not
review evidence. Keep inspection-only visibility/cameras in a separate output.

Blender's render pixel aspect cannot be animated. The importer uses median
`fx/fy`, keys lens and principal-point shifts, and compares **all** evaluated
camera matrices with the desired cache. The default intrinsic tolerance is 2 px;
configure it for the actual accuracy requirement. A larger residual fails before
saving a successful stage report. This is a representation check, not an accuracy
claim about Pi3X. GPU device selection is configured in each preview process.
Each Blender pixel-aspect axis has a lower bound of 1. The importer now represents
a ratio below 1 with `(x,y)=(1/ratio,1)`, avoiding the old silent clamp of `y` to 1.
This was the extra error in reference 32; inspect implementation/convention errors
before treating a tolerance failure as unavoidable camera approximation.

Reopened verification compares topology, stable
vertex IDs, geometry, placement, framing/floor/intersections for every person and
camera poses/intrinsics at every output frame. Sampling is explicit; `all` is the
changed-path default here. Checks do not certify self-collision, containment,
between-frame clearance, foot sliding or exact hand contacts.

### Final render and comparison

After preview acceptance, follow [render execution](RENDER_EXECUTION.md) for
batching ready stages, job waiting and completed-result review.

Point an ordinary recipe at `ENSEMBLE_OUTPUT/scene.blend`, keep its baked bodies,
and use the [shared pipeline](PIPELINE.md) for rendering, resume and full decoding.
The original pipeline still centers its tracking/validation interface on one body;
run the ensemble `verify` command again on the **final** saved pipeline scene to
cover all people. Do not label single-person tracks as multi-person tracks.

```bash
bash tools/indoor run "$SCENE_ID" --recipe "$FINAL_RECIPE"
"$PI3X_PYTHON" -m aha3d.workflow.compare \
  --reference "$SOURCE_VIDEO" --run "$FINAL_RUN" --out "$COMPARISON_OUTPUT"
```

It refuses a live execution lock. Do not guess `clip.mp4` or `animation.mp4`. For a video outside the pipeline, use `--render VIDEO --config TIMING_CONFIG`
instead. The two forms are mutually exclusive. The source is still explicit;
derive a scene alias from `scene.json.reference` and verify it exists when updating
catalogs, since agents may use different alias filenames.

Comparison uses FFmpeg to scale/pad/composite both streams with a static label
image, replacing per-frame Python/PIL compositing. Tile size defaults to 640x360
and is configurable. Source/render must have
matching constant-rate timelines starting at their respective first frames. A short metadata probe follows the strict full decode; a contact-sheet decode is
separate work. No general VFR or cut-alignment guarantee is implied. Comparison runs independently of rendering. A trailing comparison failure leaves
the existing render evidence intact but means the requested comparison is still
unfinished. Retry only that command into a new output directory after fixing its
inputs. It does not record visual acceptance or replace all-person verification.

Inspect actual representative white-room, mesh and final render/comparison frames.
Record observations separately from automated success, then update scene state and
task handoff. Use artifact links for delivery. A final `.blend` has baked bodies
and works without Kimodo or a body add-on during playback.

## Execution and repeatability

Use the existing runner's locks, immutable snapshots, fingerprints and failure
propagation instead of a `.ready`-file shell queue. Stop a run at a meaningful
checkpoint when further modeling or visual interpretation is needed; do not hold
a GPU idle through prolonged authoring. Small ready CPU stages can run beside an
active GPU run. For standalone helpers, save the configuration and source/code
provenance and use new output directories; they deliberately do not implement a
scheduler. Scene geometry authoring and review remain agent work.

For an explicitly parallel batch, follow the quality-before-expansion gate above,
assign one writer per scene and one owner for shared catalogs. CPU preparation may
run independently; GPU work goes through one `indoor batch`/`submit`
background worker at a time, which runs its tasks sequentially. Record batch IDs, stage results, selected/rejected variants and next actions in the
handoff at each meaningful stop. Wait for shell sessions and claim operations to
finish before dependent writes. Use the existing recovery procedure after a worker
disappears; a conversational update is not a durable completion record.

## Submission preflight and full-clip preview acceptance

New pipeline video runs stop with `status: preview_required` after assembly and
saved-scene verification, before the final render. This is an agent technical
checkpoint within the authorized task, not a user approval request. Completed
assembly/verification are reused when `execute` resumes. Historical run manifests
without `preview_policy` retain their existing behavior and delivery validity.
Motion-only runs and still-image recipes do not require the full-clip gate.

Use the unified read-only preflight before spending GPU time. `plan`, `run`,
`batch` submission and `prepare` invoke the same recipe/input checks. Recipe names
are identifiers, **not JSON file paths**:

```bash
bash tools/indoor preflight desert_view_lounge_g0061 --recipe actor2_final --motion-only \
  --sam-selection scenes/desert_view_lounge_g0061/workflow/sam_2_reviewed.json \
  --sam-cameras runs/desert_view_lounge_g0061/reconstruction-20260911/pi3x/cameras.json
```

Checks cover recipe schema, prompt segmentation/10-second limits, actual native
`int(duration * 30)` frame counts per segment, constraint end bounds and conflicting
explicit root/heading targets, dependency existence, and optional SAM processed-raster
bounds and endpoint rounding. Kimodo `global_root_heading` is `(cos(angle), sin(angle))`
(native +Z forward `[1,0]`); SAM `facing_xz` is an XZ vector (+Z `[0,1]`). Unit checks
cannot establish intended facing. Read the explicit convention and inspect the mesh.
Optional SAM inputs must be supplied together. Bounds checks cannot identify the wrong
person, in-bounds boxes from the wrong coordinate scale, handedness, or visibility:
review the exact processed frame/full-body overlay. The preflight does not load model
assets, open Blender, inspect linked libraries/textures, or prove source reconstruction
accuracy. Saved-scene checks still run separately.

After a new run reaches `preview_required`, run the following on the GPU
(machines without a usable GPU graphics context can use `--backend cpu`):

```bash
bash tools/indoor preview runs/SCENE/RUN --backend gpu --max-width 320 --preview-fps 5
bash tools/indoor accept-preview runs/SCENE/RUN --evidence /absolute/path/review.json
```

Then continue the final stages in a background worker (or `execute` them in the
foreground):

```bash
bash tools/indoor submit runs/SCENE/RUN
```

Preview defaults to **5 FPS across the complete source duration**, including both
endpoints. Use `--preview-fps 1` for coarse inspection; increase the rate for fast
camera/action/contact events, or explicitly use `--preview-fps source` when every
frame is needed. Do not render every source frame merely because the final video
must preserve source timing. For example, an 899-frame, approximately 15-second
clip needs about 75 preview frames at 5 FPS. Final rendering and full decode/timing
checks still cover every requested delivery frame.

The preview records exact sampled scene-frame indices and original timestamps in
`sampling.json`; encoded images use consecutive indices. A rational presentation
rate near the requested rate preserves exact clip duration, including fractional
source FPS. The saved scene timing, final recipe and final camera animation stay
unchanged. Short clips retain both available endpoints, and sampling never adds
frames beyond the source. Original-resolution start/middle/end stills remain.
Old frozen snapshots without sampling support require a new run or explicit
`--preview-fps source`; do not modify their snapshots or silently fall back to a
costly full-rate preview.

Use the retained task GPU when available (`--backend gpu` is the CLI default).
The rendering helper selects the configured raster engine or explicit Cycles GPU;
CPU previews explicitly use headless Cycles. Reduced previews use four requested
samples, preserve saved pixel aspect and an integer raster divisor for exact
aspect/even video dimensions. An unusual raster may exceed `--max-width`.
Encoding fully decodes the **sampled preview** and checks its own count, rate and
duration; it does not certify unsampled source frames. Generation, skinning and
assembly are reused.
The older `run --preview` quality flag remains supported, but is not acceptance evidence.

Each preview is stored in a new `RUN/previews/<id>/` directory, including a sampled full-duration
MP4, original recipe-resolution start/middle/end renders (8–16 samples), and an all-frame evaluated
mesh/contact report for every tagged `person_id`. Numerical contact checks distinguish
triangle overlap findings from visual acceptance; an explicit recipe `collisions: error`
still fails on detected intersections, while `off`/`report` enable diagnostic reporting; they do not prove cache correspondence,
continuous collision freedom, self-collision, or identity. Retain intended support contacts
and explain limitations. Untagged people cannot be discovered automatically.

Actually inspect the entire sampled preview, original-resolution keyframes against
original source frames, and all-person placement/contact evidence. All-frame numerical
mesh/contact checks remain independent of the preview rendering sample rate. A thumbnail montage is useful
for coverage but insufficient for proportion decisions. Record this technical review in
JSON (paths should be absolute):

```json
{
  "reviewer": "scene-agent",
  "preview_reviewed": true,
  "reviewed_scene_frames": [1, 13, 25],
  "sampling_limitations": "Describe between-sample risks and any higher-rate follow-up.",
  "note": "Describe observed camera, action timing, framing and remaining approximations.",
  "source_video": "/absolute/path/to/registered/source.mp4",
  "source_comparisons": [
    {"frame": 1, "note": "Opening source/render proportions reviewed at original resolution."},
    {"frame": 450, "note": "Midpoint sofa, actor and circulation reviewed."},
    {"frame": 900, "note": "Endpoint window/table projected extents reviewed."}
  ],
  "people": [
    {"id": 1, "placement_contact_note": "Describe floor/support/contact observations and any accepted approximation."}
  ],
  "people_report_limitations": "Describe all-frame integer sampling and any intended or unresolved overlaps."
}
```

The example frame list above is abbreviated: copy the **entire exact**
`sampling.json.scene_frames` list after reviewing those samples. Sampled preview
acceptance requires `preview_reviewed`, exact `reviewed_scene_frames`, and explicit
`sampling_limitations`; a legacy `whole_clip_reviewed: true` alone is insufficient.
Original-rate previews retain the `whole_clip_reviewed` field.

The preview extracts original-resolution lossless source PNGs itself and records their
video hash, zero-based decoded source indices and image hashes. Review those exact
`source_keyframes/` files. Default frame mapping is allowed only after source/output
frame count, FPS and duration match; for trimmed or retimed scenes pass explicit
`preview --source-frames INDEX_FIRST INDEX_MIDDLE INDEX_LAST`. These indices correspond
to the output keyframes recorded in `render_report.json`; review their alignment.
An optional external `source_image` must hash-match the receipt-extracted PNG, so an
unrelated full-size image cannot satisfy provenance.

Use the actual keyframe numbers from `render_report.json`, and list every enumerated
person ID (an empty list for no people). By default acceptance uses the preview's
`people_report.json`; an explicit `people_report` may select a stronger ensemble report
with the same assembled scene SHA256, all matching person IDs and complete sampled frames.
The original single-body verification alone cannot stand in for an ensemble report.
For a text-authored scene with no registered `scene.json.reference`, replace `source_video`
and `source_comparisons` with `no_reference_rationale` and `render_keyframes` (same frame/note
structure, without source images). Source requirements derive from frozen reference
provenance, not from guessing whether the room looks realistic.

Acceptance hashes the source scene, all frozen recipe/runtime/code/input identities,
preview artifacts, and supplied review evidence. Modified video, source, camera/timing,
mesh report or review evidence invalidates acceptance; regenerate/review applicable
artifacts before continuing. Keep those evidence files durable. Acceptance is a record
of the agent's actual review, not an automated visual-quality score or a request for
human permission. New changes require a new immutable run rather than editing snapshots.

Actual command execution also checks GPU visibility for motion generation,
assembly and final rendering, and for `preview --backend gpu`, before launching
those commands: it fails when `CUDA_VISIBLE_DEVICES` hides all devices. Reusing an
already completed GPU stage does not require a GPU; CPU-supported
verify/resample/video and CPU previews stay available. Blender separately verifies
usable OptiX devices. The assembly implementation currently configures GPU
rendering, so running assembly itself still needs the GPU.

Validated on the additional44/45/47 inputs, a real fractional-FPS full47 preview,
and headless CPU fixtures: workflow-gate validation report (private run evidence; excluded from distribution).
The real-scene test rejected an unreadable one-sample preview before adopting the
legible defaults above. Existing final videos were not rerendered.

# Common-frame layout inspection

Compare an authored room with matched source views and approximate Pi3X geometry
before final body alignment or rendering. Keep the reviewed camera/world basis
fixed during object fitting; neither geometry is silently registered to the other.

Read only the operation needed:

| Operation | Reference |
| --- | --- |
| Prepare semantic reference layers, configure matched renders, profile cost | [Reference rendering](layout-inspection/reference-rendering.md) |
| Generate colored silhouettes, isolated focus images or quick native contours | [Object views and review packets](layout-inspection/object-views.md) |
| Measure a discrepancy using reviewed masks or landmarks | [Optional source-fit checks](layout-inspection/source-fit.md) |

## Fidelity and correction depth

Use the fidelity established at [intake](SCENE_REQUESTS.md#opening-questions).
Appearance and geometric precision are independent:

- **Approximate:** compare representative source/whitebox views, review the main
  objects and correct obvious defects. Detailed X-ray correction is optional.
- **Major objects:** align structure, scene-defining furniture and salient lamps
  with isolated X-ray/source and plan/side views. Small tabletop/cabinet-top decor
  may vary unless user-flagged.
- **Precise:** require matched X-ray/contour and ordinary whitebox views for
  object-by-object correction. Verify camera/scale, then structure, large furniture
  and smaller objects. Keep reviewed cameras fixed during object fitting; show
  before/after source evidence and recheck neighbors and the combined room.
- **Selective:** apply the precise loop to named objects/areas and affected
  neighbors; retain basic review elsewhere. Resolve names to stable object IDs.

These modes choose correction depth, not exemptions from required object coverage,
source comparison or acceptance gates. Existing tasks retain their established
scope. User-reported mismatches remain blocking until supported before/after
review closes them in every mode. Unseen geometry and uncalibrated dimensions
remain explicit uncertainty. X-ray alone cannot judge openings or surface details.

## Early source-relation check

Before building the full packet, compare matched early/middle/late source and
blockout views. Inspect user-flagged and dominant objects: shared front/top planes,
proportions, openings, visible fronts, support, neighbor spacing and counts.
Record exact object IDs, source frames/crops, model views and concrete discrepancies;
use measurements where useful. Predicted metres are not physical calibration.

Repair known visible defects locally using cached source images and cameras, with
neighbors and occluders retained. Verify a reviewer's alleged mismatch against the
actual named images before editing. Preserve raw rejected judgments; schema or
transport errors call for a review retry, not geometry changes.

## Object review default and repair loop

Start with **numbered, colored semantic envelopes** in `outlines/comparison.html`
or the agent packet. Stable IDs/colors and faint architecture remove tile/fluting
clutter. The overview reuses cached contours without another 3D render. Detailed
X-ray, depth and individual-object views remain available. Envelopes omit internal
parts and enclosed holes; use clay/material/source views to judge openings and
front-panel details. Colors identify authored objects, not detected source objects.

Individually inspect each main item—at least beds, tables and shelves—plus dominant
and user-flagged objects. Compare isolated focus images with matched native and
plan/side views; record extent, placement, facing and support/neighbor observations.
Register source-required IDs in `required_object_ids`, including missing modeled
items. Whole-room prose or a generated packet does not replace per-item review.

Save distinct candidates, hold reviewed cameras fixed and recheck changed objects,
neighbors and visibility. Use inexpensive projection/placement checks during
iteration; use image judgment for ambiguous identity, regressions or stalled edits.
Recheck children/support after root scaling. User-reported mismatches stay open
until actual before/after review supports closure. Follow [acceptance](WORKFLOW_ACCEPTANCE.md)
for persisted findings; correction within scope needs no extra user approval.

Edit only after recording a mismatch in the target's isolated X-ray/source and
plan/side views. Save a distinct candidate, compare before/after, recheck affected
neighbors, and stop when the target passes or the source is ambiguous.

## Inputs and review

Reuse reviewed cameras, cached RGB and source frame/timestamp mappings. People are
excluded from static reference by default; glass, mirrors and missing geometry
remain explicit uncertainty. For semantic runtime/setup and render commands, read
[reference rendering](layout-inspection/reference-rendering.md).

The layout renderer includes [placement diagnostics](PLACEMENT_CHECK.md).
Collision, projection and mask scores supplement source comparison; they do not
prove fidelity. Keep unseen regions uncertain and inspect visible fronts in
ordinary material/clay images as well as outlines.

## Pipeline and GVHMR review gates

`layout_gate.prepare()` generates evaluated geometry, matched silhouettes and an
`agent_review --all-objects` packet. Every exported ID, including architecture and
unclassified geometry, needs nonempty individual focus views: one orthographic and
up to two available source views. Use stable `instance_id` ownership for complete
furniture roots and separately reviewed structural planes.

`evidence.json` binds the packet/images to the candidate. Each `object_views` entry
needs concrete observations with that exact subject ID. Changed scene, camera,
transform or evidence requires regeneration; do not reuse stale acceptance.
Recipe paths and `indoor review-layout` are in
[pipeline configuration](layout-inspection/object-views.md#pipeline-configuration).
GVHMR uses the same gate; `--diagnostic-layout` remains explicitly unaccepted.

For an existing gate request, run the schema-constrained image reviewer:

```bash
"$PI3X_MESH_PY" tools/review_images.py /absolute/request.json --out /absolute/new-review.json
```

It attaches actual images and validates evidence; rejection returns exit 2. Keep raw
stdout/stderr. Schema validity is not visual acceptance. Programmatic callers can
pass its absolute executable path to `review_contract.run_reviewer`.

Source inventory, full object coverage and final combined-scene image review remain
required. Reuse unchanged inputs during local repair, then regenerate current gate
evidence. There is no persistent inspection service or object-level invalidation.
Use [job waiting](RENDER_EXECUTION.md) and [acceptance](WORKFLOW_ACCEPTANCE.md)
for execution and delivery; a blocker prevents acceptance, not authorized repair.

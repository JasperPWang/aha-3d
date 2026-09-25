# Generate object views and review packets

Use cached geometry for local correction; retain current-candidate evidence for final review.

## Colored object outlines and interactive selection

For a less cluttered comparison, reuse a completed inspection and export the same
saved source once. Then compute independent per-object silhouettes in the Open3D
runtime; this does not repeat Pi3X inference, placement checks or Blender renders.

```bash
"$BLENDER_BIN" -b /absolute/model.blend --python-exit-code 1 \
  --python tools/layout_inspection/export_model.py -- \
  --cameras /absolute/cameras.json --out /absolute/new-export
"$PI3X_MESH_PY" -m tools.layout_inspection.object_outline \
  --geometry /absolute/new-export/model.npz --metadata /absolute/new-export/model.json \
  --inspection /absolute/completed-inspection --out /absolute/new-object-outlines
```

Run both stages locally. Match the source scene, cameras, frame and exclusions
to the inspection; the generator rejects provenance mismatches. It applies the
inspection's recorded model transform and identical crop/camera to each object.
Parts use their nearest authored semantic `instance_id`; collection instances use
their placed parent's semantic ownership. Untagged components stay ungrouped.

`report.html` embeds the backgrounds and interactive SVG outlines. Furniture is
shown initially; choose architecture/built-ins, other tagged objects, ungrouped
components or all objects from the filter. Click a contour or search/select an
object to highlight it, optionally solo it; Escape clears the selection. Color
is deterministic from the object ID and persists across views. Names and IDs also
disambiguate similar hues. Optional tint fills the silhouette, not a transparent
physical material. Native views can switch to original cached source RGB.

The report uses each object's external projected silhouette, with internal edges
and holes omitted and a one-pixel simplification. It deliberately ignores other
objects/reference occlusion, while retaining crop planes. Tiny disconnected
regions below three square pixels are omitted. This display cannot infer missing
chairs or assign reference-video identities: model counts and source inventory
still require comparison. Keep the depth panels for visibility/depth review.
`objects.json` records groups, colors, component membership, projected paths,
input provenance and limitations; `*_furniture.png` provides static previews.

Author complete furniture roots with `furniture/` semantic classes (for example
`furniture/bed`) and architecture with `structure/`. Bare classes such as `bed`
remain tagged objects but are omitted by the report's default furniture filter.
Check the displayed inventory and open a generated preview; an HTML file or a
successful projection command does not prove that the intended outlines appear.
Keep table and tabletop lamp identities separate when the reviewed source mask
includes only the table. Do not change grouping merely to improve a score.

## Readable whole-scene overview

The overview reuses the existing silhouette packet, requiring **no additional 3D
render or ray cast**. To inspect an existing packet without changing its evidence:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.overview \
  --outlines /absolute/outlines/objects.json --out /absolute/new-overview
```

External envelopes omit enclosed holes and internal construction. A window or
opening merged into a wall root may therefore need the detailed/clay/source
views; never infer its absence from this overview. Keep detailed edges and the
interactive per-object report for individual shape and opening inspection.
Numbers, IDs and solo selection disambiguate similar colors. Presentation
filtering changes neither geometry nor required all-object acceptance coverage.

## Agent review packet

Agents should consume a compact work queue before browsing a report. Reuse
`objects.json` and cached backgrounds:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.agent_review \
  --outlines /absolute/outlines/objects.json --out /absolute/new-agent-review \
  --inventory /absolute/reviewed-inventory.json \
  --source-fit /absolute/source-fit/source_fit.json --all-objects
```

Both optional inputs expose missing coverage when absent. `summary.json` gives
priority findings and bounded next images; `agent_review.json` records exact
object IDs, counts, projection coverage, fingerprints and limitations.
Overview images use numbered object colors and faint architecture; individual
focus images highlight the selected object over gray context, including
unclassified walls. Native backgrounds use original cached RGB. Colors identify
modeled objects; they do not match source identities automatically. Cropped or
unobserved geometry remains unknown.

Inventory `expected_counts` entries require `id`, exact `semantic_class`, `count`
and source `evidence`. Scene-specific `review_items` require `id`, `object_ids`,
`message`, `evidence` and `source_scene_sha256`; a changed scene marks the
observation for recheck, never silently resolved. Add `--previous` pointing to
an earlier `agent_review.json` to compare input signatures and findings. If inputs
and findings are unchanged, reuse the recorded review; do not repeatedly reopen
unchanged images while waiting. A removed finding alone is not proof of repair.

## Minimal native-view contour check

For a quick modeling revision, export the evaluated static scene once and draw
its visible contours on exact cached source RGB. This supplements the full
orthographic/reference inspection above; it does not replace its review gate.
With the saved authored scene already in the reviewed camera basis:

```bash
"$BLENDER_BIN" -b /absolute/model.blend --python-exit-code 1 \
  --python tools/layout_inspection/export_model.py -- \
  --cameras /absolute/cameras.json --out /absolute/new-export
"$PI3X_MESH_PY" -m tools.layout_inspection.quick_check \
  --geometry /absolute/new-export/model.npz \
  --metadata /absolute/new-export/model.json \
  --cameras /absolute/cameras.json --inputs /absolute/inputs.npz \
  --frames 0,22,34 --object-id sofa --only-highlight \
  --out /absolute/new-check
```

`--object-id` matches exact, repeatable authored IDs; legacy `--highlight` matches
component/parent name substrings. Choose IDs from `model.json` and frame IDs from
the actual cached observations. The IDs above are examples,
not universal frames. Omit `--only-highlight` for whole-room contours. All exported
surfaces remain occluders when highlighting a subset. Explicitly excluded
non-room context can be named with repeated exporter `--exclude` arguments;
exclusions are recorded. The exporter preserves modifiers and evaluated instances,
does not save over the source scene, and applies no additional alignment.

Each selected view produces source RGB, source plus thin visible contours, a
comparison panel, and camera-Z/object-ID buffers. `overview.jpg` and
`inspection_report.json` provide the image pack, provenance and stage timings.
There is no per-object render loop, new depth/segmentation inference, automatic
error ranking, or automatic scene acceptance. The modeling agent compares the
images and edits geometry directly. For an adjacency issue, inspect both members
of the pair and use a selected-pair plan or evaluated clearance to explain their
relationship; checking only nonintersection is insufficient.

This first version does not compare reference depth or model shader transparency.
Glass, mirrors, people, unseen areas and fine details require source review.
Highlight names identify authored components, not detected source-video objects.
The shared world transform is a caller-declared contract, not an inferred or
externally calibrated registration. Image evidence and geometric checks remain
separate. A few views can miss an error; add different views for unresolved
relationships and do not call reused reconstruction frames independent ground truth.

## Pipeline configuration

Recipes supply `layout_inspection` with `reference`, `cameras`, `inputs`, `config`
and `camera_cache`. Optional `source_scene`, `source_video`, `scale_provenance`
and `review_dir` preserve input provenance. The pipeline snapshots inputs/tools.
After inspecting required orthographic and native views, record the judgment with
`indoor review-layout RUN --reviewer NAME --verdict accepted --notes TEXT --views ...`
(using the actual verdict), then resume the existing execute/submit command.
Changed inputs invalidate the review; diagnostics do not accept a layout.

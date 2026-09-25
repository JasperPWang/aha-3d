# Prepare and render matched reference views

Read when generating reference layers, configuring crops or diagnosing render cost.
See the [review contract](../LAYOUT_INSPECTION.md) for inspection requirements.

## Inputs and review

Select the reviewed camera JSON explicitly, including its rigid `world_transform`.
Use the matching dense Pi3X `predictions.npz` and `inputs.npz`. Semantic preparation
operates on exact cached processed RGB frames, retaining original source frame IDs
and timestamps. Text masks identify person, glass and mirror separately. These are
per-view predictions, not propagated identities or detections of missing space.

Keep people out of the static reference by default. Glass and mirrors retain their
observations in separate uncertainty layers: their depth may refer to the surface,
behind it, or a reflection. Confidence and depth-edge filtering express another
kind of uncertainty. Missing or mismatched masks must not become safe background.
Absent geometry is unknown, never an inferred empty room region.

Configure your runtime following [setup](../SETUP.md). The semantic stage uses the
optional [SAM3 segmentation bootstrap](../../tools/object_pilot/segmentation/bootstrap.sh),
which creates `.runtime/sam3-segmentation/venv`, `checkpoints/sam3.pt` and
`runtime.json`; authorized checkpoint access is required. SAM3 segmentation is
separate from SAM 3D Body and is not installed by the shared core installer.
The `--runtime` option accepts another directory with the same checkpoint and
provenance layout; run with the Python environment containing SAM3. Preparation
uses the optional Open3D runtime described in the
[geometry guide](../PI3X_GEOMETRY_REFERENCE.md#runtime); rendering uses your configured Blender.

On the workstation GPU (validated on one 96 GB RTX PRO 6000), source
`kimodo_blender/env.sh`, set `BLENDER="$BLENDER_BIN"`, then run:

```bash
.runtime/sam3-segmentation/venv/bin/python -m tools.layout_inspection.semantic \
  --bundle "$BUNDLE" --out "$NEW_MASKS"
"$PI3X_MESH_PY" -m tools.layout_inspection.prepare \
  --bundle "$BUNDLE" --cameras "$REVIEWED_CAMERAS_JSON" \
  --semantic-cache "$NEW_MASKS" --out "$NEW_PREPARED"
```

Process every cached inference frame in both stages; omit `--frames`.
The 32/64-frame tier is chosen during reconstruction. Display cameras do not
reduce geometry inputs; partial semantic caches must be rebuilt. Prompts are configurable
with `--prompts prompts.json`: exactly `person`, `glass`, `mirror` keys, each a
nonempty string list. Default glass prompts include windows, doors and tables.
SAM3 uses all detected instances, independently per frame. Zero detections are
recorded explicitly and still need visual review. Reusing an existing output
checks provenance; stale/partial caches are rejected. Preparation without a
semantic cache puts all samples in semantic_unknown. Thresholds default to SAM3
0.3; the TSDF core uses Pi3X sigmoid confidence 0.1 and 0.03 predicted-metre
voxels. Source measurement triangles retain confidence 0.5 and maximum edge 0.15 m.
The default `tsdf-context` reference preserves all finite positive-depth non-person
background observations, including low-confidence and glass/mirror regions, in
separate layers. Use `--mesh-method grid` for an explicit legacy comparison.

Then open a saved authored scene with background Blender:

```bash
"$BLENDER" --background /absolute/model.blend --python tools/layout_inspection/render_blender.py -- \
  --reference /absolute/prepared/layers.npz \
  --cameras /absolute/pi3x/cameras_reviewed.json \
  --inputs /absolute/pi3x/inputs.npz \
  --config /absolute/inspection_config.json --out /absolute/new-inspection
```

See [editable configuration example](../../examples/layout_inspection.json).
Copy it and adjust explicit camera locations/targets, `ortho_scale` (metres across
the square image), `crop_xyz_m`, and selected native `source_frames` for the scene.
Both geometries use the same six crop planes and camera within each view.
Set `source_frames` to 3-5 native cached frames covering early/middle/late times;
the generic example must be adapted to your input. For large meshes set
`retain_view_geometry: false`: every view is rendered, while the saved copy keeps
only the last view geometry and all inspection cameras. The hybrid default shows
core plus background; `reference_layers: ["static"]` requests a core-only diagnostic.

Feature edges are built directly as bulk line-tube mesh arrays, then rasterized
by Workbench. This avoids creating and converting a Blender Curve object for
every scene part. It preserves boundary/crease filtering and hidden X-ray edges;
there is no ray tracing in this inspection path. Merely extracting visible edges
from a shaded image would lose the deliberately unoccluded X-ray evidence.

The renderer caches model clay meshes and feature edges within one invocation.
Views reuse an identical clipped mesh, or the uncut mesh when their crops both
contain the object. Different cut planes or edge settings require new geometry.
The cache is scoped to the current evaluated scene/frame; it does not import old
candidate geometry or visual judgments. Reference geometry still follows each
view's exact crop. Per-view `timing` in `inspection.json` and `INSPECTION_TIMING`
log records separate model preparation, reference preparation and rendering,
including model cache hits. Profile these measured stages before changing GPU
counts, sampling geometry or weakening inspection coverage.

`model_to_world` is explicit and needs `model_transform_reason`; identity is correct
only if authoring already used the reviewed reference basis. Do not fit this matrix
to improve apparent agreement. Scale corrections require a physical calibration
and consistent upstream geometry/camera updates. The tool rejects reference-camera
transform mismatch. A provisional Pi3X metric scale is not a measured room scale.

`edge_width_m` and `edge_angle_degrees` control orange model feature edges. Coplanar
triangulation edges are suppressed. Static Pi3X uses full source RGB vertex colors
with a flat display; model-only panels use clay studio shading. The saved inspection
copy has independent collections for model clay, model edges and every reference
semantic/validity layer. Enable the desired row collection and layers to inspect.
The source scene and original materials are preserved in the distinct output copy.

Outputs include top/front/side reference, model, X-ray/depth overlays and uncertainty panels;
selected native-camera renders and cached source RGB; a saved `.blend`; and
`inspection.json` with exact config, cameras, transforms and input hashes. Each
camera row shares projection, crop and metric scale. Source views use the selected
camera's native intrinsics and exact source timestamp, without interpolation.
Before a room exists, the reference builder also exports 3-5 source-RGB overlays
of the initial Pi3X geometry, with cyan core and amber context. See the
[overlay contract](../PI3X_GEOMETRY_REFERENCE.md#source-camera-overlays); label these
separately from the authored model-edge comparisons.

### X-ray layout review and depth review

For detailed geometry inspection, use `*_overlay_xray.png`: an isolated transparent orange
edge pass is composited above the rendered reference. Reference walls, tabletops
and uncertain stretched surfaces cannot hide the retained model edges. This is
the detailed panel in `inspection/report.html`; start whole-scene review with
the semantic overview in `outlines/comparison.html`.

Use `*_overlay_depth.png` separately to review depth and reference occlusion.
The existing `*_overlay.png` keeps its original depth-tested meaning and is an
identical compatibility copy. `*_edges.png` records the transparent edge pass.
`inspection.json` labels all modes, inputs and common view settings. Native-view
reference panels render colored Pi3X geometry; original cached RGB is a separate
panel, not the background of the mesh overlay.

Both modes retain identical feature-edge filtering, cameras, transforms and crop
planes. X-ray does not restore geometry outside the height slice, detect missing
objects, or establish correct depth. Check the report's explicit crop and model-only
panel when a part is absent. For an obstructed area, use a shared height slice or
`reference_layers: ["static"]` as a labelled additional diagnostic; retain the full
reference/uncertainty view so missing coverage is not interpreted as empty space.
The saved inspection Blender copy retains the depth view and toggleable collections;
the X-ray PNG is a separate composite, not a changed viewport depth setting.

Orange/red lines can therefore already be X-ray: color does not identify the
occlusion mode, and X-ray here does not mean a translucent solid model. When
explaining a panel, name its actual background and edge/outline mode. For a
disputed pair, show the colored selected-pair view on original source RGB and a
matched plan; a dense single-color panel alone is poor evidence for the user.


### Full reference display limits

Vertex-colored surfaces interpolate sampled RGB and may contain duplicate surfaces
from different views. They are not texture-baked photogrammetry. Semantic misses
remain possible even when a mask cache passes provenance checks. Geometry-invalid
finite points are shown as magenta markers in their own layer (up to 10,000 by
default, with recorded display subsampling). In hybrid references, unsupported
context points have a separate default 20,000-point display limit; the full NPZ
and background PLY preserve every observation. Display patches do not change
retained source measurement triangles. Orthographic crop cuts do not fill newly exposed cross-sections. The
renderer evaluates the authored model at `model_frame` (default 1); source-camera
comparisons concern the static layout, not animation validation. Inspect masks and
actual rendered results before treating an automated pass as useful evidence.


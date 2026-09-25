# Measurements from the full reference mesh

Use the unified reconstruction entry to create the 32/64-frame reference first.
Measure retained static mesh surfaces, author the editable room in the same basis,
then compare room and reference in matched orthographic and native source views.
Historical scene-specific trials are excluded from this distribution.

With claimed output paths, run:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.measure_mesh \
  --mesh /absolute/reference/mesh/layers.npz \
  --config /absolute/surfaces.json --out /absolute/new-measurements
```

The configuration contains `surfaces`, each with `id` and a `regions` list. Every
region has a native `source_frame` and `polygon_uv` in the cached processed-image
pixel grid. Multiple source views can contribute to one surface. The tool selects
vertices participating in retained static triangles and saves exact supporting
vertex IDs, mesh hash, source selection PNGs, plane parameters and fit residuals.
It does not read the old sampled display cloud or reconnect rejected triangles.

The default reference now embeds a separate TSDF core and visible background in
`display_*` arrays. These arrays are for inspection, not this measurement API.
`measurement_valid` retains strict static eligibility independently of the lower
fusion threshold and unfiltered background. Source vertex IDs and retained source
triangles keep the existing measurement contract. See the
[accepted geometry reference](../../../../docs/PI3X_GEOMETRY_REFERENCE.md).

Example schema (coordinates must be selected for the actual source):

```json
{"surfaces":[{"id":"table_top","plane_threshold_m":0.025,
 "normal_hint_world":[0,0,1],"max_normal_angle_degrees":20,
 "regions":[{"source_frame":203,"polygon_uv":[[218,323],[271,305],[296,305],[239,334]]}]}]}
```

`normal_hint_world` is an optional orientation prior, not a measured normal.
Use the reviewed world up for floors/tabletops and source-supported directions
for walls/roof slopes. Unconstrained dominant-plane fitting can choose a nearby
wall instead of a roof; a source-room trial observed this failure.
A spatial ROI alone does not identify an object. Reject mixed surfaces or refine
selection using source masks/corners and triangle normals. Do not relax thresholds
merely to make a failed request produce a number.

The output bounds describe visible inlier support, not complete furniture bounds.
Report hidden-corner and room-completion assumptions separately. Repeated views
can bias vertex-weighted statistics; automatic cross-view object association,
area-balanced sampling and confidence-calibrated uncertainty are not implemented.
Automatic object-boundary estimation and scene-specific spatial-ROI prototypes
are outside this interface.

Keep one mesh version and world transform across measurement, model and comparison.
When using convenient room axes, store the rigid room-to-world mapping explicitly
and map the authored room through it; do not independently register cameras to
improve apparent agreement. The raw reference remains uncalibrated predicted metres.

For large reference inspections, set `retain_view_geometry: false` in the render
config. All views are rendered from the complete input; the saved inspection copy
retains the last view's geometry and the inspection cameras. This bounds memory
without reducing inference/mesh frames. Default true preserves historical behavior.
The renderer caches NPZ members once and bulk-transfers triangle data to Blender.

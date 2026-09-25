# Furniture surface measurement API

Use `aha3d.workflow.furniture` to measure **horizontal rectangular
surfaces** such as tabletops, countertops or cabinet tops from a cached Pi3X
bundle. It returns their XY dimensions, center, yaw, surface height and optional
surface-to-surface clearance in the existing aligned coordinate system. It does
not infer furniture thickness, chair facing, hidden full-object bounds or usable
walking clearance around chairs. Room files are not edited by the measurement API.

## Quick start

Claim the output path, source `kimodo_blender/env.sh` and set `PYTHONPATH="$PWD/src"`. NumPy and Pillow in the existing Kimodo environment
are sufficient; no model loading or GPU is needed for cached geometry.

```bash
"$KIMODO_ENV/bin/python" -m aha3d.workflow.furniture \
  --bundle runs/open_plan_group_walk_g0055/aligned_v1 \
  --config scenes/open_plan_group_walk_g0055/workflow/furniture_measure_20260910/table_only.json \
  --out NEW_CLAIMED_OUTPUT_DIRECTORY
```

That scene-specific example belongs to reference 32. Choose source pixels for a
different scene instead of copying its selections. The output directory must not
exist. A batch keeps successful measurements, records rejected requests and exits
with status 2 if any request failed.

Python callers can load the dense bundle once and reuse it:

```python
from aha3d.workflow.furniture import MeasurementSession, sam3_selector

session = MeasurementSession("runs/open_plan_group_walk_g0055/aligned_v1")
request = {
    "id": "table",
    "source_frame": 207,
    "floor_reference": "aligned_v1 fitted floor; uncalibrated Pi3X",
    "selector": {"corners_uv": [[370, 299], [446, 250], [551, 249], [585, 327]]},
    "height_range_m": [0.55, 0.95],
    "boundary_note": "Far-left corner partly occluded and inferred."
}
result = session.measure(request)
surface = result["authoring_surface"]
# surface contains center_xyz_m, size_xy_m, yaw_deg and its measurement basis.
# Select the appropriate surface for your parameterized Blender builder.
```

The example's coordinates are **processed-image integer-center pixels**, matching
the Pi3X image size and intrinsics. `source_frame` is the original video frame ID,
not an index into the sparse bundle. Use the raw/aligned bundle with rigid
`world_transform`; this first interface retains uncalibrated predicted metres.
It does not consume the separately rescaled export of `measure.py`.

## Interchangeable selectors

| Selector | Input | Returned boundary |
| --- | --- | --- |
| `{"corners_uv": [[u,v], ...]}` | Four convex corners in perimeter order | Corner-defined rectangular surface estimate |
| `{"box_xyxy": [left,top,right,bottom]}` | Integer processed-image box, right/bottom exclusive | Extent of visible plane inliers in the box |

Choose one selector. To combine a mask or box with explicit boundary corners,
put `corners_uv` at the request's top level. The region supplies plane samples;
the corners define the intended rectangle. For a partly hidden corner, retain
that inference in `boundary_note`. A mask selects visible pixels and cannot
establish an unseen edge by itself.

The batch JSON has `schema_version: 1` and an `objects` list of requests. Optional
`clearances: [["table", "island"]]` computes the shortest XY distance between the
two fitted surface rectangles (zero for overlap). This excludes chair backs,
people, object thickness and unobserved geometry; it is not a walkability result.

Each request requires `id`, `source_frame`, `floor_reference` and `selector`.
Optional `height_range_m` narrows the surface search when known floor alignment
and previous measurements support a height band. Default filters are
`confidence_min: 0.6`, `plane_threshold_m: 0.025`, `min_inlier_fraction: 0.35`,
`max_tilt_deg: 15`. They are adjustable fit heuristics, not accuracy guarantees.
Weak/degenerate planes, mismatched cameras, invalid pixels and mismatched masks
are rejected rather than silently repaired.

## Reuse SAM3 masks

The installed [SAM3 runner](../../../../tools/object_pilot/segmentation/README.md)
accepts images, text and optional selection boxes on the GPU. For this
API, run it on the cached **processed frames** so no mask resizing is necessary.
The 32 segmentation input (historical or external input; omitted from this bundle)
is an actual two-object example. Text and box candidates are both retained.

```python
request["selector"] = sam3_selector(
    "runs/open_plan_group_walk_g0055/furniture_measure_20260910/sam3/manifest.json",
    "table207", variant="box_0"
)
# Optional: retain corners when the surface boundary is already identified.
request["corners_uv"] = [[370, 299], [446, 250], [551, 249], [585, 327]]
result = session.measure(request)
```

Omitting `variant` uses the runner's selected candidate. Selection confidence or
box overlap does not prove the intended surface was isolated: examine the mask
overlay when choosing a candidate. A companion review can record the chosen mask and remaining occlusion. Direct mask paths resolve relative to the config file (or Python `base_dir`).

## Geometry and outputs

The tool filters invalid/low-confidence/depth-edge points, fits a dominant near-
horizontal plane with RANSAC and SVD, then intersects boundary camera rays with
that plane. All selectors use this same construction. The minimum-area XY
rectangle is a rectangular-surface hypothesis. No axis alignment to an existing
manually authored room is imposed.

Pi3X point and camera predictions can disagree. The report includes their
reprojection residuals and the raw point extent alongside the ray/plane result.
Neither low plane residual nor same-view reprojection establishes physical scale
or full-clip camera accuracy. Different-view selections can be compared in a
batch, but automatic multi-view association/fusion is not implemented.

Outputs:

- `report.json`: measurements, fit support, source/calibration provenance,
  selector and boundary interpretation, consistency diagnostics and failures.
- `authoring_surfaces.json`: center, XY size and yaw for downstream builders;
  each entry retains `observed_surface_extent` or `corner_defined_rectangle_estimate`.
- `MEASUREMENTS.md` and per-object PNGs: compact dimensions and projected rectangles.
- `request.json`: exact selections and parameters used for the run.

For scene 32 input convenience, actual masks, runtimes and interpretation, read
the interface comparison (historical or external input; omitted from this bundle).
These are candidate measurements; they do not replace the accepted scene geometry.

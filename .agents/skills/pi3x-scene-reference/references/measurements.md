# Cached measurements and diagram configuration

`scripts/measure.py` reads a reference bundle without loading Pi3X. Run it with
a NumPy/Pillow Python environment. The input is read-only and the
output directory must not exist. Paths are explicit and may live in any claimed
project output area; no helper assumes a home-office scene or task directory.

```bash
python .agents/skills/pi3x-scene-reference/scripts/measure.py \
  --input /absolute/path/to/reference-bundle \
  --config /absolute/path/to/measurements.json \
  --output /absolute/path/to/new-measurement-output
```

Pass `--cameras /absolute/alignment/cameras.json` to use the final room basis.
The reader transforms source-linked samples consistently with measurement points
and cameras; it leaves the original bundle unchanged.

Omit `--config` for grid-only top/front/side references and camera timestamps.
This helps inspect a new reconstruction before naming semantic points. For a
real existing example, pass `assets/home_office_measurements.json` from this
skill with the project's `tasks/pi3x-investigation-20260908/pilot_24` bundle.
That example's points belong only to its stated source frame.

## Configuration

```json
{
  "selection_method": "Analyst chose visible surface samples; verify in overlays",
  "floor_reference": "Estimated floor alignment reviewed for this reference",
  "grid_m": 0.5,
  "landmarks": [
    {"id": "left", "label": "Left surface endpoint", "source_frame": 100, "pixel_uv": [80, 120]},
    {"id": "right", "label": "Right surface endpoint", "source_frame": 160, "pixel_uv": [220, 110]}
  ],
  "measurements": [
    {"id": "width", "label": "Visible horizontal span", "kind": "horizontal_distance", "points": ["left", "right"]}
  ]
}
```

The numbers above illustrate the schema; select actual pixels from the current
bundle before execution. IDs are unique short alphanumeric names starting with
a letter; hyphens/underscores are allowed. `source_frame` is a native frame ID,
not the index into the selected tensor. `pixel_uv` uses integer indices in the
processed RGB image. Points can belong to different source frames, with each
frame's own overlay and timestamp preserved.

Supported measurement kinds:

| Kind | Definition | Default diagram |
| --- | --- | --- |
| `horizontal_distance` | XY Euclidean distance between two points | Top |
| `distance_3d` | XYZ Euclidean distance between two points | All; label says 3D |
| `median_height` | Median Z of named surface samples above the stated floor | Front and side |
| `vertical_distance` | Absolute Z difference between two points | Front and side |

Height above floor needs `floor_reference` or an exported automatic floor
hypothesis. Do not supply a fictitious floor merely to satisfy validation. The
older pilot bundle needs an explicit floor description because it stores the
floor-fit evidence in `analysis.json`, separately from `cameras.json`.

Optional settings:

- `color_mode`: `rgb` (default) uses observed `reference_samples.npz` colors;
  `gray` preserves the legacy neutral display. A cache without colors must
  explicitly request gray. No texture/color is synthesized.
- Per-view `clip_xyz_m`, for example `{"z":[0.08,1.6]}` in a top view, selects
  displayed samples only. Intervals are in the original predicted metres and
  follow any uniform calibration factor. Named landmarks, dimensions and camera
  exports do not change. Choose intervals from this scene; these example heights
  are not universal furniture bounds. Empty slices are rejected.
- `confidence_min` (default 0.5) and `patch_span_max_m` (default 0.12 predicted m)
  filter selected endpoints. A 3x3 patch must fit entirely inside the image.
  These are quality heuristics, not an uncertainty estimate. Inspect rejected
  points and choose an appropriate surface sample rather than blindly lowering
  thresholds.
- `polylines`: lists of landmark IDs to connect. They represent sampled geometry;
  do not imply precise object boundaries or fill hidden regions.
- `camera_labels`: number of timestamp labels on top views, 0 to 20 (default 5).
- Per-point `label_offset_px: [dx,dy]`: source-image label offset in processed
  pixels, for resolving annotation collisions.
- `views`: optional `top`, `front`, `side` objects. Each may specify `bounds` as
  `[[axis0_min,axis0_max],[axis1_min,axis1_max]]` in original predicted metres,
  a list of `measurements`, `dimension_offsets` keyed by measurement ID (display
  pixels), and `point_label_offsets` keyed by point ID (display pixels).
  `camera_label_offsets` optionally maps source frame IDs to top-view label offsets.

Default bounds use central observed cloud extents plus every selected point and
camera center. They are display extents, not room dimensions. All diagrams use
the same metres-to-pixels scale. Up to six dimensions appear per page; additional
ones receive more pages. Inspect labels after generation, especially close points.

When points share a pixel, RGB drawing selects the nearest observed depth:
top looks down from positive Z, front from negative Y, side from negative X.
This is a point raster, not a watertight surface renderer. Hidden surfaces,
moving-person fragments and sparse samples remain possible. A display slice is
not a semantic object mask. The view report records its filter and point count.
For presentation revisions, compare exported dimensions/landmarks and cameras
with the previous run; the [piano validation](../../../../docs/lessons/colored-reference-leg-guidance.md)
demonstrates exact invariance without repeating model inference.

## Scale calibration

```bash
python .agents/skills/pi3x-scene-reference/scripts/measure.py \
  --input /absolute/path/to/reference-bundle \
  --config /absolute/path/to/measurements.json \
  --known-distance width --known-length-m 1.50 \
  --scale-source 'Measured physical span between the named endpoints' \
  --output /absolute/path/to/new-calibrated-output
```

This illustrates the interface; 1.50 m is not a known dimension of an arbitrary
scene. Use the actual cue, and label an assumed standard dimension or synthetic
test explicitly in `--scale-source`. The script computes
`scale = supplied length / predicted measurement`, then rescales all points,
dimensions and camera translations. Rotations and timestamps stay unchanged.
Other dimensions remain independently unvalidated. A factor of exactly one still
records that a cue was supplied; the UI does not infer calibration from factor alone.

## Outputs and agent reading

Start at `MEASUREMENTS.md` for people or `measurements.json` for agents. The latter
contains definitions, units, calibration provenance, point coordinates, frame/
pixel IDs, quality diagnostics, view bounds and source-overlay filenames.
CSVs provide dimensions, landmarks and timestamped camera positions. PDF/PNG
views share the same IDs and values. `config_snapshot.json` preserves the request.

`cameras.json` preserves the source alignment as `source_world_transform` and
records `scale_after_source_world_transform` separately. For a raw point X, use
`scale * (R @ X + t)` from that source transform. For an aligned camera pose,
scale only its translation, not its rotation or homogeneous bottom row. Camera
intrinsics refer to the processed image size.

Checks recompute dimensions from exported XYZ, compare CSV/JSON, verify camera
identity/scaling and decode every PNG. Inspect the PDF and source-point diagrams
separately; the helper's `validation.json` does not certify visual quality or
physical measurement accuracy. Synthetic point tracking, occlusion tests and
automatic furniture segmentation are outside these helpers.

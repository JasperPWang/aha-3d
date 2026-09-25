# Floor and wall alignment

The reference builder uses SAM3 floor/wall masks and reliable Pi3X points to
propose one rigid room basis: floor normal → +Z, floor → Z=0, dominant wall-floor
intersection → X. Geometry and cameras move together; scale and actual wall
angles stay unchanged. Plane fits require broad support across multiple views.

## Run

New references use this automatically. For cached predictions, generate masks
with `semantic --structure` on the GPU, then fit on CPU:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.structural_alignment \
  --bundle /absolute/pi3x --semantic-cache /absolute/structural-masks \
  --cameras /absolute/pi3x/cameras.json --out /absolute/new-alignment
```

Use the resulting `cameras.json` consistently for meshing, overlays and
`measure.py --cameras`. The builder records this path in `reference_build.json`.
Explicit builder `--cameras` or `--alignment preserve` retains an existing basis.
Legacy masks need regeneration for structural mode; source files are unchanged.

## Review

Inspect `alignment.json` and the source/support images: amber marks SAM3 masks;
cyan marks sampled plane inliers. Check surface identity, coverage, reflections
and agreement across views. Geometry checks do not establish floor/wall identity.

Optional `--review` selects reviewed masks using `bundle`, `semantic_cache`,
`reviewer`, and `floor`/`wall` lists of `{source_frame, observation}`. Use actual
paths, frame IDs and observations; empty lists reject that class. The builder
accepts the same file via `--alignment-review`. Source paths, frame IDs, timing,
shapes and geometry are checked; SHA-256 is not used by the alignment step.

Weak floor evidence returns camera-up coordinates with **no accepted floor**.
Weak wall evidence retains floor alignment with camera-right yaw. All fits remain
hypotheses pending visual review; metric scale remains predicted and uncalibrated.
Thresholds and diagnostics live in [the fitter](../tools/layout_inspection/structural_alignment.py),
with behavior covered by [tests](../tests/test_structural_alignment.py).

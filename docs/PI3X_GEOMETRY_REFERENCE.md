# Pi3X initial geometry reference

The default reference combines a **TSDF structural core and retained source
context**. It supports editable Blender room authoring; it is an approximate
monocular geometry reference, not a finished room or measured ground truth.
Deliver top/front/side views together with **3-5 native source-camera overlays**,
using five by default. Geometry uses every cached inference frame.

This command uses Pi3X, SAM3 and Open3D. It is the reference part of the
[Static installation level](INSTALLATION.md#installation-levels). Blender is
also required to turn the reference into an editable static scene. Human
reconstruction and robotics motion have separate installation levels.

## Runtime

For a first new-video static reference, install Pi3X, SAM3 and Open3D:

```bash
bash tools/setup.sh --level static --plan
bash tools/setup.sh --level static
export PI3X_PY="$PWD/.runtime/pi3x-inference/venv/bin/python"
export PI3X_MESH_PY="$PWD/.runtime/pi3x-mesh/venv/bin/python"
export PI3X_UPSTREAM="$PWD/external/Pi3"
```

Omit `--level static` to have the installer ask which level to use. The selected
Static route prepares separate Pi3X inference, SAM3 segmentation and Open3D
mesh/overlay environments. Install Blender separately for the editable static
scene. The Human level adds PMPose, GVHMR and source-person skinning; the
Robotics level adds Kimodo.
The `reference` extra pins Open3D 0.18.0, NumPy 1.26.4 and OpenCV (headless) 4.11.0.86;
the object outline and source-fit review steps need OpenCV in this same environment.
Helpers never install packages. Existing compatible runtimes can be selected
with `--pi3x-python`, `--semantic-runtime`, `--semantic-python` (default
`SAM3_PYTHON`, else the runtime's `venv/bin/python`) and `--mesh-python`.

The code install does not supply model weights. Follow the
[Pi3X checkpoint guide](install/pi3x.md#download-authorized-weights). With
authorized access to [facebook/sam3](https://huggingface.co/facebook/sam3),
download and register its checkpoint using:

```bash
.runtime/sam3-segmentation/venv/bin/python \
  tools/object_pilot/segmentation/prepare_runtime.py \
  --runtime .runtime/sam3-segmentation
export PI3X_CHECKPOINT="$PWD/.runtime/pi3x/checkpoint/model.safetensors"
```

The SAM3 setup creates `checkpoints/sam3.pt` and `runtime.json` in its runtime.
SAM3 segmentation is distinct from SAM 3D Body. The deployed Open3D runtime
was used for validation; this clean installation recipe has not been rerun on
every platform.

| Runtime input | Default | Override |
| --- | --- | --- |
| Inference Python | Current Python interpreter | `PI3X_PY` or `--pi3x-python` |
| Pi3 checkout | `external/Pi3` | `PI3X_UPSTREAM` or `--upstream` |
| Mesh/overlay Python | `.runtime/pi3x-mesh/venv/bin/python` | `PI3X_MESH_PY` or `--mesh-python` |
| SAM3 runtime root | `.runtime/sam3-segmentation` | `--semantic-runtime` |
| Model file | Explicitly required for new video | `--checkpoint` |

Run commands from the repository root. Follow [machine rules](../MACHINE.md)
and [task coordination](COORDINATION.md); select new claimed output directories.
New inference or uncached masks require the GPU. Reusing both dense
predictions and full semantic masks needs only the CPU.

## Build the reference

For a continuous source shot, on the GPU:

```bash
"$PI3X_PY" -m tools.layout_inspection.build_reference \
  --video /absolute/reference.mp4 \
  --upstream "$PI3X_UPSTREAM" --checkpoint "$PI3X_CHECKPOINT" \
  --mesh-python "$PI3X_MESH_PY" \
  --num-frames 32 --reference-views 5 --out /absolute/new-reference
```

This runs inference, SAM3 for every selected frame, a shared floor/wall alignment
hypothesis, TSDF/context meshing and source-camera overlays. See
[structural alignment](STRUCTURAL_ALIGNMENT.md) for mask review, fit diagnostics
and explicit fallbacks. Outputs are `pi3x/`, `masks/`, `alignment/`, `mesh/`, `source_views/`
and `reference_build.json`. The final status still requires visual review.
Orthographic/reference-room comparisons are a separate
[Blender inspection stage](LAYOUT_INSPECTION.md).

Use the 32-frame default or 64-frame tier across both endpoints of one shot.
Shorter videos use every native frame. The low-level reconstruction helper's
`--frame-indices` accepts an ascending unique selection matching that tier and
including both endpoints. Do not use three display cameras as mesh inputs.

To rebuild an existing complete bundle with full-frame masks, on CPU:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.build_reference \
  --bundle /absolute/pi3x --cameras /absolute/pi3x/cameras_reviewed.json \
  --semantic-cache /absolute/full-frame-masks \
  --mesh-python "$PI3X_MESH_PY" --num-frames 32 \
  --reference-views 5 --out /absolute/new-reference
```

Match `--num-frames` to the cached tier. Explicit `--cameras` preserves the
established rigid world basis. Without it, the default proposes a new floor/wall
basis and requires masks containing floor and wall. Use `--alignment preserve`
to retain the bundle's `cameras.json` with legacy caches. Consume the final camera
path recorded in `reference_build.json`; never mix old samples with a new basis.
Without `--semantic-cache`, the builder runs SAM3 and still needs a GPU. Cache
hashes, raster, native frame coverage and camera basis are validated. Empty
detections are valid processed masks; absent or partial masks are not safe background.

The lower-level `prepare` command accepts legacy complete caches, including old
24-frame inference. Such a rebuild is not a new 32-frame inference. Both semantic
preparation and meshing must consume all cached frames; omit `--frames`.
Existing outputs are not rewritten.

## Geometry and background contract

| Layer or operation | Default policy |
| --- | --- |
| TSDF core | 0.03 predicted-metre voxels; truncation four voxels; static semantics, depth-edge eligibility and finite sigmoid confidence strictly greater than 0.1; rejected depth pixels set to zero before integration |
| Retained background | Every finite, positive-camera-depth non-person observation; no confidence cutoff |
| Visible context triangles | Same strict confidence threshold as fusion, then native source adjacency where core ray support is missing, depth disagrees, or material/semantic status is uncertain; depth/shape guards and one-pixel overlap |
| Unsupported context | Only confidence-eligible source points shown when triangles cannot be formed; raw observations remain archived |
| Measurement surfaces | Retained static source triangles, confidence at least 0.5 and maximum triangle edge 0.15 predicted m |
| Person, glass, mirror, unknown | Separate labels; people excluded from static core/background, uncertain materials retained as approximate context |

`--human-mask-radius` defaults to **3 processed-image pixels**. Each frame's
person mask is dilated independently with a Euclidean disk before integration;
there is no temporal dilation. Use `0` for the original mask or compare `5` for
a wider margin. The exclusion applies to fusion, visible context triangles,
fallback points and measurement support. Source triangles cannot use the added
guard band. Original person labels and raw background observations are preserved,
so the margin is not recorded as a new semantic detection. `human_exclusion` in
`layers.npz` records the effective mask, and the geometry manifest records radius
and per-frame original/expanded counts. Overlays preserve source RGB across the
expanded mask and export both original and effective masks. Existing outputs
must be rebuilt into a new directory to apply this change.

`--fusion-confidence` controls both fusion and visible context; `--voxel-size`
changes the core. `--confidence` and
`--max-edge` control source measurement support. Lower fusion thresholds do not
relax measurement eligibility. TSDF uses uniform eligible observation weights,
not calibrated confidence weighting. It uses camera-Z depth with `depth_scale=1`
and no fixed 3 m sensor clipping distance.

For noisy references, first inspect the TSDF core alone using
`reference_layers: ["static"]` in the Blender inspection configuration. The
default visible context retains source observations that disagree with the core,
so its overlapping surfaces can remain noisy even when fusion is clean. A first
comparison can use `--human-mask-radius 3 --fusion-confidence 0.3 --voxel-size 0.03`
against the existing `0.1` confidence cutoff. Then vary the mask radius to `5`
or voxel size to `0.05` independently. These are diagnostic settings, not validated
quality improvements: larger margins/thresholds reduce coverage and coarser
voxels lose detail. Truncation stays at four voxel widths. Persistent doubled
surfaces require depth/pose consistency review rather than stronger mesh smoothing.

The pinned upstream [Pi3X example](https://github.com/yyfz/Pi3/blob/9fa3ddb3f8d53041f8b2738df404f62223bbaa7b/example_mm.py#L114)
applies `sigmoid(raw_conf) > 0.1`, followed by a depth-edge mask. The saved
`predictions.npz` contains raw logits; `layers.npz` confidence contains sigmoid
scores. A raw-logit cutoff of 0.1 would instead mean a sigmoid cutoff of about
0.525. Nonfinite raw confidence is ineligible. Rejected context cannot return
through the one-pixel dilation or fallback points. Manifests record confidence
space, strict comparison and per-frame accepted/rejected counts. Older references
must be rebuilt into a new output directory to apply this display filter.

The schema-2 `mesh/layers.npz` contains original source arrays plus
`measurement_valid`, `fusion_eligible`, `context_eligible`, `finite_depth`, `background_valid`,
`human_exclusion`,
embedded `display_*` vertices/colors/faces/roles, source indices and fallback-point
indices. Its hash binds both measurement and display geometry. Fused source
index `-1` means no exact source pixel; source-pixel indices are provenance,
not physical feature tracks. `background_all_finite.ply` exports the complete
background with RGB, confidence, native frame/pixel identity and semantic labels.

Blender inspection shows core and confidence-filtered non-person context by default, with separate
glass/mirror/unknown/context-point collections. `reference_layers: ["static"]`
selects a core-only diagnostic. Display crops and recorded point subsampling
do not delete observations from the NPZ or complete PLY. Use
`retain_view_geometry: false` to render every full-input view but keep only the
last view geometry and all inspection cameras in the saved inspection copy.
Legacy schema-1 references retain their previous rendering defaults.

For source-linked dimensions, use the
[mesh measurement interface](../.agents/skills/pi3x-scene-reference/references/mesh-measurements.md).
It selects original static source triangles and strict measurement eligibility;
the TSDF/context display mesh does not supply measurement support. Visible
surface extents do not establish completed or hidden furniture bounds.

## Source-camera overlays

`--reference-views 5` selects distinct cached observations near evenly spaced
source times, including both endpoints; three or four can be requested. Check
that the views expose useful walls, openings and furniture. For manual selection
or an existing mesh, run on CPU:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.reference_views \
  --reference /absolute/reference/mesh/layers.npz \
  --cameras /absolute/pi3x/cameras.json --inputs /absolute/pi3x/inputs.npz \
  --view-count 5 --out /absolute/new-source-views
```

Optional `--source-frames` takes 3-5 ordered native cached IDs spanning
early/middle/late times. The automatic selector records the shortfall if fewer
than three observations exist. It never invents or interpolates cameras.

Each view includes exact processed source RGB, projected source-colored geometry,
and an overlay: **cyan is TSDF core, amber is retained context**. Default opacity
is 32%, with stronger silhouette/depth-jump contours rather than every triangle
edge. No-hit pixels and source-person-mask pixels retain source RGB. Missed
person regions can still contain geometry; masks need inspection. Untriangulated
fallback points are not projected. Unchanged RGB does not mean known empty space.

`source_overlays.jpg` is the contact sheet. `reference_views.json` records the
reference/input/output hashes, native IDs, timestamps, intrinsics, poses and
legend. Per-view projection NPZ files preserve camera-Z depth, geometry role,
overlay visibility, contours and person masks. Camera, raster, world basis and
scale remain shared; there is no independent per-view fitting.

Once an authored room exists, also deliver 3-5 native-camera **model-edge
comparisons** through Blender inspection, with source RGB alongside. Label
whether an overlay shows initial Pi3X geometry or authored model edges.
Orthographic views reveal global layout; these source views expose visible
alignment, occlusion and scale inconsistencies.

## Classical reconstruction comparisons

TSDF is a signed-distance representation; voxel grids describe spatial storage.
TSDF usually produces a triangle mesh through Marching Cubes. These are not
mutually exclusive final output formats. The optional
[study exporter](../tools/layout_inspection/geometry_study.py) compares native
grids, relaxed/adaptive grids, TSDF at 0.03/0.06 m, occupied voxel boundaries,
ball pivoting and Poisson using fixed cached predictions and cameras:

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.geometry_study \
  --bundle /absolute/pi3x --cameras /absolute/pi3x/cameras.json \
  --semantic-cache /absolute/full-frame-masks --out /absolute/new-study
```

Grids preserve native adjacency but can overlap across frames. TSDF combines
repeated observations but pose/depth disagreement can blur or erase surfaces.
Voxel boundaries are blocky; ball pivoting depends on normals and sampling;
Poisson may close unseen regions. The hybrid default keeps a compact core and
retains approximate context for authoring. `--mesh-method grid` remains available
in the production builder/prepare commands for explicit legacy comparisons.

The [Curless-Levoy paper](https://graphics.stanford.edu/papers/volrange/) describes
volumetric fusion; [Open3D integration](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html)
documents pose/depth conventions. See the original
[ball-pivoting paper](https://research.ibm.com/publications/the-ball-pivoting-algorithm-for-surface-reconstruction)
and [screened Poisson paper](https://www.cs.jhu.edu/~misha/Fall13b/Papers/Kazhdan13.pdf)
for the point-based alternatives.

Historical trials used one 32-frame living-room cache and all 24 observations
of a legacy dining cache; generated scene artifacts are excluded from this
distribution. Coverage and depth agreement against the same Pi3X predictions
measure consistency, not independent accuracy. Confidence is not a calibrated
error bar. Depth remains in uncalibrated predicted metres unless a physical cue
establishes a uniform correction applied consistently to geometry and cameras.

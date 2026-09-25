# Reconstruction and runtime

Use the cached measurement path when predictions already exist. New reconstruction
needs a GPU, PyTorch, NumPy, Pillow, OpenCV, safetensors, huggingface_hub and an
explicit Pi3X upstream checkout/checkpoint. Helpers do not install packages,
download weights, submit jobs, or alter shared environments.

## Configure the runtime

Follow the [Pi3X installation guide](../../../../docs/install/pi3x.md) for the
pinned upstream/checkpoint and shared core inference environment. Follow the
[geometry guide](../../../../docs/PI3X_GEOMETRY_REFERENCE.md#runtime) for the
optional Open3D CPU environment and separate SAM3 segmentation runtime.
Set `PI3X_PY`, `PI3X_UPSTREAM` and `PI3X_MESH_PY`, or use the corresponding CLI
options. Keep weights and generated outputs outside the source distribution.

Read `MACHINE.md`, source `kimodo_blender/env.sh` and claim output paths.
Inference and uncached SAM3 masks need the GPU; cached measurement/meshing/overlays
run on CPU. Helpers do not
install packages or download checkpoints. Do not replace the working core's
Torch/NumPy packages with upstream's older pins.

Run:

```bash
"$PI3X_PY" -m tools.layout_inspection.build_reference \
  --video /absolute/path/to/reference.mp4 \
  --upstream /absolute/path/to/Pi3 \
  --checkpoint /absolute/path/to/model.safetensors \
  --num-frames 32 \
  --out /absolute/path/to/claimed/new-reference
```

This is the normal entry point. It runs Pi3X, then SAM3 for every selected frame,
then reference meshing and native-camera overlays; it does not expose a mesh frame
subset. Outputs are `pi3x/`, `masks/`, `mesh/`, `source_views/` and
`reference_build.json`. Zero detections produce valid
empty masks; missing processing is a different condition. Default meshing is
`tsdf-context`: 3 cm TSDF core, source-linked visible background patches, and
complete finite non-person point preservation. Fused/context display arrays and
strict source measurement triangles share one hash-bound `mesh/layers.npz`.

The default `--mesh-python` is `.runtime/sam-3d-objects/venv/bin/python`, which has
the already installed Open3D 0.18.0. It is separate from Pi3X inference; no shared
environment changes are needed. Override the executable on another deployment.
Missing Open3D is an error, not an automatic switch to grid meshing.

`--fusion-confidence` defaults to 0.1; `--voxel-size` defaults to 0.03 predicted m.
The existing `--confidence` remains the 0.5 source-measurement/floor-sampling
threshold. Background has no confidence cutoff. Explicit `--mesh-method grid`
retains the previous mesher for comparisons. The
[accepted geometry contract](../../../../docs/PI3X_GEOMETRY_REFERENCE.md) records
the tested behavior and limitations.

To reuse existing inference, replace `--video`, `--upstream` and `--checkpoint`
with `--bundle /absolute/pi3x` and optionally `--cameras /absolute/cameras_reviewed.json`.
Set `--num-frames` to match the cached 32/64 tier. This regenerates full-frame masks
and mesh in a new output directory. Rendering and layout review follow separately.

If a matching full-frame semantic cache already exists, add
`--semantic-cache /absolute/masks`; its hashes, raster and complete frame coverage
are checked by the mesher. Reusing both bundle and masks needs only the CPU.
Without a reused cache, SAM3 still needs the GPU.

The low-level reconstruction helper remains an internal stage.
Use the configured runtime's Python rather than assuming system `python` has
the dependencies. `--frame-indices selection.json` accepts an ascending JSON list
of native frame IDs matching the selected tier and including both endpoints. The default
255,000-pixel limit matches the tested upstream preprocessing. Resize is whole
image, no crop. The helper preserves decoded presentation timestamps and rejects
missing/nonmonotonic timestamps rather than inventing a new video cadence.

## Input selection and limits

Inspect a contact sheet and video metadata first. Use overlapping views with
camera translation where possible. Split cuts before reconstruction; the helper
does not implement automatic shot detection, motion segmentation or full-rate
camera interpolation. Use 32 frames by default or the 64-frame tier across the full shot, including
both endpoints. Shorter videos use every native frame. These tiers are the
user-selected coverage policy, not a claim of optimal quality.

Reference meshing and semantic preparation must use every cached inference frame:
omit `--frames` in both layout-inspection commands. A three-frame `source_frames`
list selects comparison cameras only. Regenerate partial semantic caches before
meshing. Both TSDF fusion and context extraction consume every cached frame.
Early/middle/late cameras select inspection views only. The default renderer shows
core and background context; `reference_layers: ["static"]` is an explicit
structural-core-only diagnostic view, not the normal initial-reference display.

In addition to orthographic views, deliver 3-5 source-camera overlays.
`--reference-views 5` is the unified builder's default; 3 or 4 are available.
The final CPU stage uses every mesh frame and selects only its display cameras
near evenly spaced source times. It preserves native RGB pixels, K, poses and
timestamps and never interpolates or fits a new camera. If fewer than three
cached observations exist, it exports those available and records the shortfall.
Check for redundant/occluded views; the standalone `reference_views` command can
take an explicit ordered `--source-frames` selection spanning the clip. See the
[overlay contract](../../../../docs/PI3X_GEOMETRY_REFERENCE.md#source-camera-overlays).

The helper is image-only. It does not consume dataset camera poses, calibration,
depth or motion masks as model conditioning. Upstream supports additional
modalities, but adapting that path needs interface and scale verification.
Exclude moving/reflected/unreliable regions from static fitting as appropriate;
the default confidence/edge filter does not establish that content is static.

The low-level inference export uses a preliminary geometric floor hypothesis.
The reference builder then uses [SAM3 floor/wall alignment](../../../../docs/STRUCTURAL_ALIGNMENT.md).
Consume its final camera path; camera-up fallback does not establish floor height.

## Bundle and validation

`inputs.json` records source hash, native frame IDs, timestamps and processed
image size. `inputs.npz` retains RGB and timing. `predictions.npz` preserves
world/local point maps, rays, raw confidence, metric factor, camera poses,
recovered intrinsics and the depth-edge filter. `reference_samples.npz` retains
aligned sampled points with source-pixel indices. `cameras.json` records the
alignment, sparse poses, intrinsics and timestamps. `run_report.json` records
versions, hashes, runtime and floor/scale status.

Outputs already contain Pi3X's predicted metric scale. The alignment is rigid;
metric correction belongs to the measurement stage. Source-pixel IDs are not
physical feature tracks. Confidence is not a centimetre error bound.

The helper checks full source decoding, finite outputs and proper camera rotations.
Those checks do not validate geometry. Inspect top/front/side views and source
frames. For camera/layout adoption, compare independent static image landmarks
across views; a point's own-view reprojection alone is insufficient. A match to
another estimated camera path may assess consistency after alignment, not
physical metric accuracy. Historical pilot artifacts are excluded from this distribution.

## Camera integration

Pi3X camera matrices are OpenCV camera-to-world (right, down, forward). Preserve
the same world transform for points and camera centers. A Blender camera-axis
conversion is `T_blender = T_aligned_cv @ diag(1,-1,-1,1)`; validate actual
landmark projections, camera sensor fit and principal-point representation.

The pinned intrinsic-fit helper uses integer-index pixel centers and centered
principal point `((W-1)/2,(H-1)/2)`. Upstream's conditioning ray helper uses
`+0.5` pixel centers. Keep conventions explicit when introducing conditioning.

For camera playback, interpolate translations and use rotation SLERP at the
requested output timestamps, preserving cuts. Define behavior beyond the first/
last observation explicitly. This skill exports sparse camera observations;
it does not claim a validated Blender animation or synthetic point-track export.

## Reusable playback and static feature analysis

Use `python -m aha3d.workflow.camera` for explicit full-rate interpolation
and `python -m aha3d.workflow.crossview` for independent masked ORB
comparisons. Commands, schemas and limits live in the
[scene workflow guide](../../../../docs/SCENE_WORKFLOW.md#camera-and-independent-static-cross-view-checks).
The camera helper preserves off-center principal points, performs pixel-center
conversion before resize, and rejects unsupported observation intervals unless
holding is explicitly selected. The Blender ensemble checks actual representable
intrinsics; pixel aspect is fixed while lens/shifts can be keyed. Dense NPZ arrays
are loaded once per analysis, avoiding per-correspondence decompression.

Use cached inference for layout/label changes; source-specific floor polygons and
static masks still require interpretation.

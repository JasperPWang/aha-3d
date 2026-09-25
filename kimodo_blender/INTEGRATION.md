# Kimodo → SMPL-X body → Blender → synthetic tracks

Source inspection recorded on September 8, 2026, at upstream commit
`1aece8c124d73d255ceff5086d983b844c9f4e94` in `upstream/`.
The working pipeline is documented in [RUNTIME.md](RUNTIME.md).
It has run Kimodo inference, SMPL-X skinning and a five-second, 24 fps room
render on one RTX PRO 6000 (96 GB). The raw-NPZ route below is a separate adapter.

## Intended use

Infer approximate actions and a plausible path from a reference, then generate
similar motion. The objective is not fitting the real person's poses, shape or
identity. Kimodo-SMPLX-RP-v1 produces motion for 22 body joints; it does not
directly produce the final body surface. Fingers use the mean hand pose and the
face stays neutral in the deployed workflow.

1. Identify actions such as walking, turning and stopping, with approximate timing.
2. Choose feasible starting position, facing, turns and endpoint in the actual room.
3. Describe the action in text and add timed `root2d` route constraints only where
   needed. Let the model generate gait, arm swing and body turns. For required
   contact, prefer sparse native Kimodo end-effector targets; see the
   [motion control policy](../docs/MOTION_CONTROLS.md). The first version's external
   arm IK and timed facing edits are retired.
4. Inspect candidates for action, route, speed, continuity and furniture clearance;
   adjust the prompt, constraints or seed when needed.
5. Resample body rotations to the requested output timestamps **before skinning**,
   generate a fixed-topology SMPL-X mesh cache, then import it into Blender.
6. Export synthetic tracks from the final body mesh and camera. They describe the
   generated animation, not the real person in the reference.

Contact targets, when required, use the actual Blender scene coordinates.
`constraints.walk_example.json` illustrates the format; it was not extracted
from the user's footage. It describes a five-second forward walk, a right curve
and roughly one second of standing. Frame indices are zero-based at native
30 fps. Ground points are `[x,z]` offsets in metres; this bridge maps Kimodo
negative X to Blender positive X.

```powershell
kimodo_gen 'A person walks forward, curves gently to their right, and comes to a stop.' --model Kimodo-SMPLX-RP-v1 --duration 5 --seed 42 --constraints '.\constraints.walk_example.json' --output '.\motions\walk'
```

Repeating the endpoint at several final timestamps encourages stopping; inspect
the result for a natural turn and a stable stop.

## Bridge and recorded validation

Generation and skinning run in the independent environment. Blender imports a
per-frame fixed-topology mesh cache, requiring neither PyTorch nor playback
handlers. The five-second, 24 fps example uses 120 body frames.

Recorded checks cover source/output inspection, coordinate conversion, rotation
SLERP, mesh animation import and point export. An analytic tetrahedron test
verified 120 frames, body placement, camera projection, stable IDs and animation
after reopening; its maximum projection difference from Blender was approximately
0.000040 pixels. Resampling from 30 to 24 fps preserved five seconds.

The deployed body example used the existing SMPL-X Blender asset: 10,475 vertices,
22 joints and 120 frames. It checked floor contact, integer-frame furniture
triangle intersections, complete video decoding, and reopened mesh agreement with
the tracks. Outputs are in `output/walking_whitebox/`. Occlusion visibility was
not generated.

| File | Role |
| --- | --- |
| `export_body_cache.py` | Native Kimodo NPZ → resampled motion → official SMPLXSkin → mesh cache in Blender coordinates |
| `import_body_blender.py` | Mesh cache → baked shape keys, with optional camera point tracks |
| `validate_bridge_blender.py` | Blender integration check using an unlicensed analytic tetrahedron fixture |

The baked scene supports rendering and annotation. The separately retained
`walk_aisle_body_24fps.blend` keeps a rig and pose correctives for editing.
An Alembic adapter is a possible future option for long sequences with many
shape keys; it is not implemented by this guide.

## Optional raw-NPZ skinning route

The working pipeline uses `export_body_addon.py` and the installed body asset.
The following requirements apply only to the separate `export_body_cache.py` route:

1. Authorized access to `nvidia/Kimodo-SMPLX-RP-v1` on Hugging Face.
2. Authorized access to `meta-llama/Meta-Llama-3-8B-Instruct`; authenticate locally
   with `hf auth login` without putting credentials in project files.
3. The licensed **SMPL-X with removed head bun (NPZ)** asset. Place
   `SMPLX_NEUTRAL.npz` at
   `kimodo_blender/upstream/kimodo/assets/skeletons/smplx22/SMPLX_NEUTRAL.npz`.

That licensed raw NPZ is not included with the integration scripts. The working
pipeline uses authorized weights, an independent `kimodo` environment and a
validated Blender body asset instead; reuse an existing installation of those.

The installation notes inspected at the pinned source revision specified Python
3.10+ and GPU PyTorch 2.0+. The original Windows machine had Python 3.8 in
Anaconda base, so the suggested experiment used a separate environment:

```powershell
conda create -n kimodo python=3.10
conda activate kimodo
# Install a suitable GPU PyTorch build for that machine, then:
Set-Location 'C:\path\to\repo\kimodo_blender\upstream'
python -m pip install -e .
hf auth login
```

The base Kimodo installation is sufficient; optional `[all]` dependencies for
SOMA and visualization are unnecessary for this bridge. Native Windows also
needs the MotionCorrection CMake/C++ build. The inspected source had Windows
branches, but this session did not validate that build. Linux/Docker generation
with NPZ transfer to Windows Blender was an alternative under consideration.

For an RTX 3070 Laptop with 8 GB, the original notes proposed CPU text encoding.
Upstream reported a GPU-memory reduction from approximately 17 GB to below 3 GB
in that mode. Those were upstream figures; local runtime, RAM and GPU-memory
requirements were not benchmarked in the Windows experiment.

## Historical Windows command examples

These commands were not the executed body pipeline. They require a prepared
environment, authorization and the raw body model.

```powershell
conda activate kimodo
Set-Location 'C:\path\to\repo\kimodo_blender'
$env:TEXT_ENCODER_DEVICE = 'cpu'
New-Item -ItemType Directory -Force -Path '.\motions' | Out-Null
kimodo_gen 'A person walks forward naturally and comes to a stop.' --model Kimodo-SMPLX-RP-v1 --duration 5 --seed 42 --output '.\motions\walk'
python '.\export_body_cache.py' --motion '.\motions\walk.npz' --out '.\motions\walk_body_24fps.npz' --fps 24
```

Import into a separate room copy, preserving its 24 fps camera/cabinet animation:

```powershell
& 'C:\path\to\blender.exe' -b 'C:\path\to\repo\scenes/living_room_kitchen_g0025/blender\walkthrough_smooth_whitebox\living_room_smooth_whitebox.blend' --python-exit-code 1 --python '.\import_body_blender.py' -- --cache '.\motions\walk_body_24fps.npz' --out '.\motions\room_with_body.blend' --tracking '.\motions\walk_tracks.npz' --person-id 1 --offset 0 0 0 --yaw 0
```

`--offset` is in Blender world metres; `--yaw` is in degrees around Z. Zero
placement is only an interface example and makes no furniture-clearance promise.
The importer requires a distinct output `.blend` and rejects mismatched frame rates.

Kimodo exports both native `walk.npz` and `walk_amass.npz`. Pass the native file
to the cache exporter. At the inspected revision, the upstream AMASS export kept
16 shape coefficients, whereas skinning used the full `beta.npy`; coefficients
after index 15 were not all zero. Preserve full shape parameters and pose
correctives to reproduce the official surface. Do not assume the two paths
produce identical meshes without checking.

## Synthetic track schema

Keep each body's shape, topology and IDs fixed while changing its pose. Export
the known mesh directly instead of re-estimating a body from rendered frames.

| Information | Fields |
| --- | --- |
| Person identity | `person_id`, also used as the Blender object index |
| Surface correspondence | `vertex_ids`, fixed `faces` |
| Surface tracks | `vertices_world[T,V,3]`, `vertices_uv[T,V,2]` |
| Joint tracks | `joints_world[T,22,3]`, `joints_uv[T,22,2]` |
| Camera | Per-frame `K`, OpenCV `world_to_camera_cv` |
| Depth | Camera Z for vertices/joints, not a full image depth map |
| Framing | `vertices_in_frame`, `joints_in_frame`; frustum checks only |
| Timing | `time_seconds`, `blender_frames`, `fps` |

The pixel origin is the top-left image boundary; pixel centres are
`(i+0.5, j+0.5)`. Convert conventions when integrating systems that use integer
pixel centres. Current projection assumes a perspective camera without lens
distortion or postprocessing image transforms. Geometry is sampled at integer
animation frames; a single timestamp does not describe an entire motion-blurred
exposure.

Future occlusion labels could use depth/instance renders and depth comparisons,
or ray tests. Retain 3D trajectories for points hidden by furniture or the body
itself and label them accordingly. Current `in_frame` fields are not visibility.
Dense surface samples could use fixed face IDs plus barycentric coordinates.

The scope excludes real-video person detection, identity association and SMPL-X
fitting. Current exporters reproduce Kimodo's standard body. Supporting a new
shape requires recomputing rest joints and checking retargeting and floor contact;
scaling the visible mesh alone would invalidate existing joint annotations.
Clothing or other separate meshes require their own stable point correspondence.

## Room interaction

Kimodo does not read Blender rooms or furniture positions. Translate requested
interactions into root routes and, only when needed, native end-effector constraints.
Author targets in the scene, then convert them to the same Kimodo coordinate
system and scale as the route. Account for the root information carried by hand
constraints; avoid fixing it throughout an otherwise free gesture.
Align target times with cabinet, drawer and chair animation.
Check path clearance, palm contact and foot grounding. The deployed walking
example is the baseline; explicit furniture-contact workflows need further validation.

## Sources recorded during integration

- [Kimodo source and low-memory mode](https://github.com/nv-tlabs/kimodo).
- [SMPL-X model card](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1).
- [Body model installation](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation_smpl.html).
- [Installation and text-encoder authentication](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html).
- [Timed route and pose constraints](https://research.nvidia.com/labs/sil/projects/kimodo/docs/user_guide/constraints.html).
- [Pinned SMPL-X skinning implementation](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/kimodo/viz/smplx_skin.py).
- [Pinned AMASS export and coordinate conversion](https://github.com/nv-tlabs/kimodo/blob/1aece8c124d73d255ceff5086d983b844c9f4e94/kimodo/exports/smplx.py).
- [Optional Meshcapade Blender add-on](https://github.com/Meshcapade/SMPL_blender_addon).

The original source review recorded Apache-2.0 for Kimodo code and noncommercial
research conditions for the SMPL-X model weights, with separate body-asset access
and license terms. Restricted assets and credentials are not bundled with these scripts.

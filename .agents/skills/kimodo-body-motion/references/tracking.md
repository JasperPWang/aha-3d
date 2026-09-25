# Synthetic body tracking data

The shared implementation is `src/aha3d/blender/body.py:export_tracking`.
It samples the final evaluated mesh, object transform and camera at integer output
frames. Each run's `stages/assemble/tracks.json` describes conventions alongside
`tracks.npz`; `camera.npz` also records calibration for scenes without a body.

With `T` frames, `V` vertices and `J` joints:

| Field | Shape / meaning |
| --- | --- |
| `vertices_world`, `joints_world` | `[T,V,3]`, `[T,J,3]`, metres, Blender Z-up world |
| `vertices_uv`, `joints_uv` | `[T,V,2]`, `[T,J,2]`, image pixels |
| `vertices_depth`, `joints_depth` | `[T,V]`, `[T,J]`, signed OpenCV camera Z in metres |
| `vertices_in_frame`, `joints_in_frame` | Boolean near/far and image-boundary test |
| `K` | `[T,3,3]`, intrinsics at the actual rendered resolution |
| `world_to_camera_cv` | `[T,4,4]`, OpenCV +X right, +Y down, +Z forward |
| `vertex_ids`, `faces` | Stable mesh vertex IDs and triangle index connectivity |
| `joint_names` | Body joint order; use the recorded names |
| `person_id` | Integer identity of the generated actor |
| `fps`, `time_seconds`, `blender_frames` | Sample rate, sample times, scene frame numbers |
| `image_size` | `[width,height]` |

Current generated SMPL-X output has 10,475 vertices, 20,908 faces and 22 body
joints. A replay without a joint cache exports zero joints. Do not assume SMPL's
different topology. Load archives with `numpy.load(path, allow_pickle=False)`.

Pixel coordinates are measured from the top-left image boundary; pixel centres are `(i+0.5,j+0.5)`. Depth is camera Z, not Euclidean distance from the camera. `in_frame` does **not** provide visibility through furniture, self-occlusion, transparency or lens distortion. If visible tracking is requested, add a matching evaluated-scene depth/raycast visibility pass and store a separate visibility field.

`stages/assemble/body_cache.npz` includes vertices/joints and any
`vertical_ground_correction_m`, before the room object's final placement.
`tracks.npz` contains final world-space placement. Do not apply placement twice.

The exporter checks vertex count, triangle connectivity and vertex IDs at every
frame. Preserve topology/order deliberately. After retargeting, sculpting, adding
body modifiers or editing the rig, regenerate mesh and joint caches together;
cached joints do not automatically follow arbitrary new deformations.

The baked animation is exact at sampled frames under the exporter assumptions. It does not reconstruct an observed real human and does not certify subframe physics or motion-blur correspondence.

# Kimodo and Blender runtime

This source distribution excludes installed environments, weights, the body
asset, Blender executables and generated examples. Configure your own authorized
runtime on one Linux workstation using [setup](../docs/SETUP.md) and follow the
[runtime policy](../MACHINE.md).

The source deployment recorded Python 3.11, PyTorch 2.7.1/CUDA 12.8,
Transformers 5.1.0, Blender 5.2.1 for rooms and Blender 4.5 for the SMPL-X add-on,
on one 96 GB RTX PRO 6000. Kimodo revision: `1aece8c124d73d255ceff5086d983b844c9f4e94`.
These are provenance, not a newly validated install in this bundle.

## Per-shell environment and profile

Run `source kimodo_blender/env.sh` in each shell. It loads ignored
`kimodo_blender/env.local.sh` first and respects `KIMODO_ENV`, `KIMODO_UPSTREAM`,
`KIMODO_CHECKPOINT`, `HF_HUB_CACHE` and other cache overrides. Level 3 adds
Kimodo to Level 1 Static's Pi3X environment. SAM 3D Body is an optional sparse
pose adapter.

`python tools/configure_runtime.py` writes the ignored `configs/runtimes/local.json`
(template: [local.example.json](../configs/runtimes/local.example.json)); recipes
select `"runtime": "local"`. Unresolved `${...}` templates are rejected.

```bash
python kimodo_blender/download_models.py --model g1   # G1 snapshot and text encoders
python kimodo_blender/check_runtime.py --model g1     # CUDA, imports, model access
```

## Run and diagnose

After initializing the generic workspace in [examples](../examples/README.md):

```bash
bash tools/indoor plan new_scene --recipe walk --motion-only
bash tools/indoor run new_scene --recipe walk --motion-only
bash tools/indoor status --live
```

Batches run in a detached local background worker, one task at a time on the
GPU. `runs/batches/<id>/` holds `job.sh`, `batch.log`, per-task `<i>.log`,
`<i>.log.exit` (exit code) and `submission.json` (`job_id`, `pid`, `runs`).
`status --live` reports whether worker pids are alive and each task's exit code.
A started worker is not success: inspect exit codes and stage reports before
claiming completion. Record batch folder and log paths in the task handoff; stop
only your own workers (`kill PID`). For missing models, inspect configured paths
without printing authentication data.

FFmpeg from the selected environment:

```bash
"$KIMODO_ENV/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'
```

Every Blender process must configure its Cycles GPU devices, including when
reopening a saved scene. The shared GPU helper selects OptiX and reports missing
devices rather than silently using CPU.

## Motion and skinning

For a five-second result at 24 fps, preserve **120 output frames**. Generate at
native model cadence, then resample rotations with SLERP before skinning. Do not
change playback FPS without resampling. The generic input recipe is under
`examples/new_scene/recipes/walk.json`; no completed room is supplied.

The working skinning path expects the installed locked-head SMPL-X Blender
extension and its body asset, with all 300 shape parameters and pose correctives.
The alternative raw-NPZ exporter needs a separately authorized body file.
On a 24 GB GPU, the Llama text encoder is the main memory risk; upstream reports
CPU text encoding (`TEXT_ENCODER_DEVICE=cpu`, slower) reduces its GPU memory
from about 17 GB to under 3 GB. This mode is untested in this project.
Saved assembled animation is baked for playback without Kimodo or an add-on.

The source deployment used CMake 3.31.6's native executable to avoid a Python
wrapper/build-isolation issue; `tools/setup_core.sh` handles this and installs
only into the selected `KIMODO_ENV`.

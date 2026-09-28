# aha-3d

Install and run on one Linux workstation (Ubuntu 22.04/24.04 or Windows WSL2)
with one NVIDIA GPU; read the [runtime policy](../MACHINE.md) first. Use the
[fixed Git checkout workflow](GIT_WORKFLOW.md) for development and task-end
synchronization.

Keep this full source checkout together and install it in editable mode. The
Python wheel alone does not contain the Blender libraries, skills or config files.
[Installation levels](INSTALLATION.md#installation-levels) define the selected
runtime set; download only the models required for your stages.

Run `bash tools/setup.sh` to choose Level 1, 2 or 3 before installation.
For Level 1 Static, the selector installs Pi3X, SAM3 and Open3D code in separate
environments. Install
[Blender](install/blender.md) for the editable room and obtain the Pi3X and SAM3
checkpoints as in the [geometry guide](PI3X_GEOMETRY_REFERENCE.md#runtime).
For Level 2 Human, additionally install the separate
[PMPose and GVHMR environments](install/human-motion.md) and
[Blender SMPL-X skinning](install/blender.md). Level 3 Robotics extends Static
with [Kimodo and its native G1/text dependencies](install/kimodo.md). SAM 3D Body remains
optional for sparse pose guidance.

## 1. Prerequisites

- NVIDIA driver with CUDA 12.8 support (`nvidia-smi` works). On WSL2, install the
  Windows NVIDIA driver only; do not install a Linux display driver inside WSL.
- Python 3.11, git, FFmpeg, unzip, a C++ compiler (GCC 12) and, for GVHMR/PMPose
  native extensions, a CUDA 12.8 toolkit.
- Disk space for environments, checkpoints (tens of GB), caches and renders.

## 2. Clone and create the environment

```bash
git clone https://github.com/KevinXu02/aha-3d.git && cd aha-3d
```

Choose the installation level interactively:

```bash
bash tools/setup.sh
```

For noninteractive installation, select a level explicitly. To inspect the
Robotics plan and then install it:

```bash
bash tools/setup.sh --level robotics --plan
bash tools/setup.sh --level robotics
export KIMODO_ENV="$PWD/.runtime/pi3x-inference/venv"
source kimodo_blender/env.sh
```

[The shared core installer](install/core.md), called by the level selector,
adds Kimodo to Static's Pi3X Python 3.11 environment. Set
`PI3X_REFERENCE_ENV` before running the selector to use another dedicated
environment. Use `--with-sam3d` only for optional sparse pose guidance.
GVHMR and PMPose use separate environments; see
[GVHMR](install/gvhmr.md) and [human motion](install/human-motion.md).

The shared core installer does not prepare SAM3 segmentation or Open3D. The
level selector prepares them for a first `build_reference --video` run. Later
rebuilds of the same Pi3X bundle can reuse a complete source-matched semantic
mask cache. SAM3 segmentation is distinct from optional SAM 3D Body.

For source tools only (asset search, recipe inspection, unit tests), Python 3.11+,
NumPy, SciPy, Pillow and imageio-ffmpeg suffice:
`python -m pip install -e '.[test]'` in a dedicated environment.
`python tools/asset_index.py tree` requires only Python's standard library.

## 3. Per-shell environment

Source `kimodo_blender/env.sh` in each shell before using `bash tools/indoor`.
It adds the checkout's `src/` to `PYTHONPATH`, puts `KIMODO_ENV/bin` on `PATH`
(default `.venv` at the checkout root) and sets model caches under `.runtime/`.
It respects supplied paths. Put machine defaults (for example `KIMODO_ENV`,
`BLENDER_BIN`, cache locations) in ignored `kimodo_blender/env.local.sh`, which
`env.sh` loads first.

## 4. Blender and model files

Blender asset libraries were saved with Blender 5.2.1. Use a compatible Blender
version. SMPL-X skinning uses a separately installed Blender 4.5 extension and
its authorized locked-head body asset. Neither Blender executable is bundled;
see [Blender/SMPL-X](install/blender.md).

Follow the [Pi3X](install/pi3x.md) guide for the Static checkpoint. Level 3
also needs the [Kimodo G1 and text models](install/kimodo.md). For optional
sparse pose guidance, follow [SAM 3D Body](install/sam3d-body.md).
[THIRD_PARTY.md](../THIRD_PARTY.md)
lists upstream sources. Kimodo upstream is pinned to
`1aece8c124d73d255ceff5086d983b844c9f4e94`. Level 3 requires its G1
model and Llama/LLM2Vec dependencies; generated human motion additionally needs
the Kimodo SMPL-X model and Blender SMPL-X asset. Acquire these through your own
authorized access. Authenticate outside source files; do not copy another user's
token, credential cache or gated body/model assets.

Pi3X takes explicit `--upstream` and `--checkpoint` paths. SAM 3D Body takes an
upstream, checkpoint and MHR asset. The optional SAM 3D Body adapter uses the
Robotics core environment when installed there.
The optional SAM3 object segmentation runner is described in [object segmentation](OBJECT_GENERATION.md).

## 5. Configure the runtime

For motion recipes, fill the machine-local profile with actual installed paths.
Static `build_reference` takes its runtimes directly and does not need this
Kimodo profile. For native G1, point the checkpoint at the G1 directory; the
`--skin-blender` field may point at the same Blender executable as `--blender`:

```bash
python tools/configure_runtime.py \
  --blender /path/to/blender-5.2/blender \
  --skin-blender /path/to/blender-5.2/blender \
  --kimodo /path/to/kimodo \
  --checkpoint /path/to/Kimodo-G1-RP-v1 \
  --threads 16 --gpu 0      # optional; defaults: all cores, GPU 0
```

The helper validates executable and source paths and writes ignored
`configs/runtimes/local.json` (schema version 2: `python`, `blender`,
`skin_blender`, `env_script`, `upstream`, `checkpoint`, `threads`, `gpu`). Recipes
select `"runtime": "local"`. The tracked
[template](../configs/runtimes/local.example.json) shows the fields; templates
containing `${...}` are not ready to run. A `NAME.local.json` overrides a tracked
`NAME.json` without editing it.

`INDOOR_THREADS` overrides the profile's thread count; an existing
`CUDA_VISIBLE_DEVICES` selects the GPU. Every invocation records an
`INDOOR_RUN_ID` (generated as `local-<host>-<pid>-<timestamp>` when unset and
inherited by child processes) for provenance.

## 6. Check, test and run a first scene

For Robotics:

```bash
python kimodo_blender/check_runtime.py --model g1
python -m unittest discover -s tests -v
```

`check_runtime.py --model g1` checks CUDA execution, Kimodo imports and native G1
model access without printing tokens. Use `--model smplx` for Kimodo generated
human motion. Human reconstruction uses its own
[verification commands](install/human-motion.md#verify-before-a-new-run). Static
reference verification is in the [geometry guide](PI3X_GEOMETRY_REFERENCE.md#runtime).
Then follow the [relevant examples](../examples/README.md) and
[project skills](../TOOLS_AND_SKILLS.md).
Historical scene IDs and output paths in deeper technical lessons are examples,
not files supplied by this bundle.

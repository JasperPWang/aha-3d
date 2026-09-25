# aha-3d

Install and run on one Linux workstation (Ubuntu 22.04/24.04 or Windows WSL2)
with one NVIDIA GPU; read the [runtime policy](../MACHINE.md) first. Use the
[fixed Git checkout workflow](GIT_WORKFLOW.md) for development and task-end
synchronization.

Keep this full source checkout together and install it in editable mode. The
Python wheel alone does not contain the Blender libraries, skills or config files.
[Component installation](INSTALLATION.md) lists every component; download only
the models required for your stages.

## 1. Prerequisites

- NVIDIA driver with CUDA 12.8 support (`nvidia-smi` works). On WSL2, install the
  Windows NVIDIA driver only; do not install a Linux display driver inside WSL.
- Python 3.11, git, FFmpeg, unzip, a C++ compiler (GCC 12) and, for GVHMR/PMPose
  native extensions, a CUDA 12.8 toolkit.
- Disk space for environments, checkpoints (tens of GB), caches and renders.

## 2. Clone and create the environment

```bash
git clone https://github.com/KevinXu02/aha-3d.git && cd aha-3d
export KIMODO_ENV="${KIMODO_ENV:-$PWD/.venv}"
bash tools/setup_core.sh --plan
bash tools/setup_core.sh
source kimodo_blender/env.sh
```

[The shared core installer](install/core.md) prepares Kimodo, Pi3X and SAM 3D
Body in one Python 3.11 environment (a venv by default; `--env PATH` selects a
dedicated conda or venv prefix). GVHMR and PMPose use separate environments; see
[GVHMR](install/gvhmr.md) and [human motion](install/human-motion.md).

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

Follow the [Pi3X](install/pi3x.md), [SAM 3D Body](install/sam3d-body.md) and
[Kimodo](install/kimodo.md) guides for checkpoints. [THIRD_PARTY.md](../THIRD_PARTY.md)
lists upstream sources. Kimodo upstream is pinned to
`1aece8c124d73d255ceff5086d983b844c9f4e94`. Acquire its SMPL-X model,
Llama/LLM2Vec dependencies and the Blender SMPL-X asset through your own
authorized access. Authenticate outside source files; do not copy another user's
token, credential cache or gated body/model assets.

Pi3X takes explicit `--upstream` and `--checkpoint` paths. SAM 3D Body takes an
upstream, checkpoint and MHR asset. Both use the shared core environment.
The optional SAM3 object segmentation runner is described in [object segmentation](OBJECT_GENERATION.md).

## 5. Configure the runtime

Fill the machine-local profile with actual installed paths:

```bash
python tools/configure_runtime.py \
  --blender /path/to/blender-5.2/blender \
  --skin-blender /path/to/blender-4.5/blender \
  --kimodo /path/to/kimodo \
  --checkpoint /path/to/Kimodo-SMPLX-RP-v1 \
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

```bash
python kimodo_blender/check_runtime.py
python -m unittest discover -s tests -v
```

`check_runtime.py` checks CUDA execution, Kimodo imports and model access without
printing tokens. Then follow the [generic examples](../examples/README.md) for a
first motion-only scene, and the relevant [project skills](../TOOLS_AND_SKILLS.md).
Historical scene IDs and output paths in deeper technical lessons are examples,
not files supplied by this bundle.

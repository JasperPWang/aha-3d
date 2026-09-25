# One shared core environment

Kimodo, Pi3X, SAM 3D Body and the source/preview tools share one Python environment.
Their source checkouts and model directories remain separate so model identity is
clear; a separate directory does not mean a separate Python installation.

The common baseline is Python 3.11, Torch 2.7.1/cu128, torchvision 0.22.1 and
Transformers 5.1.0. The SAM deployment already inherited Kimodo's packages; the
consolidated recipe makes that common stack explicit. The package constraints are
in [constraints-core.txt](../../constraints-core.txt), and adapter additions are
in [requirements-core.txt](../../requirements-core.txt).

## Install once

From the checkout root:

```bash
export KIMODO_ENV="${KIMODO_ENV:-$PWD/.venv}"
bash tools/setup_core.sh --plan
bash tools/setup_core.sh
source kimodo_blender/env.sh
```

The default is `.venv` (or the supplied `KIMODO_ENV`). Use `--env /your/path` to
select another dedicated project environment. The script installs into that
chosen environment, obtains clean pinned checkouts, preserves the Torch/Transformers
constraints, installs the batch integration and runs CPU imports. It downloads no
model weights. Existing source checkouts at another
revision or with edits cause a clear error instead of a reset.

The cu128 wheel supports current NVIDIA GPUs (Ada, Hopper, Blackwell) with a
CUDA 12.8-capable driver; it was recorded on an RTX PRO 6000. For another
GPU/driver, use a matching official wheel and record that change in the
constraints before testing. Package resolution and CPU imports do not establish model inference,
body deformation or reference quality. Fresh installation was not rerun as part
of this documentation update; the executed validation scope is in
[validation](../VALIDATION.md).

## Add the model files you need

All adapters use the same `KIMODO_ENV/bin/python`:

| Component | Source checkout | Model setup |
| --- | --- | --- |
| Kimodo | `kimodo_blender/upstream` | [Motion/text weights](kimodo.md#authorized-weights-and-body-assets) |
| Pi3X | `external/Pi3` | [Reference checkpoint](pi3x.md#download-authorized-weights) |
| SAM 3D Body | `external/sam-3d-body` and `external/dinov3` | [SAM checkpoint and MHR](sam3d-body.md#authorized-checkpoint-and-mhr-download) |

Acquire authorized model files only for stages you will use. Keep them outside
Git. The install guides define per-model path variables and use the shared Python
environment; those variables do not create more environments.

## Components with different runtimes

Blender uses its bundled Python and the matching licensed body extension. The
existing skinning adapter expects a Blender 4.5 SMPL-X extension, while the asset
libraries were saved with Blender 5.2.1; see [Blender compatibility](blender.md).

Experimental
[object-generation tools](object-tools.md) keep their upstream-specific compiled
dependencies; they are not part of the default core install.

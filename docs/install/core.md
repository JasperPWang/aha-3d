# One shared core environment

Kimodo, Pi3X and the source/preview tools share one Python environment. The
optional SAM 3D Body reference adapter can use that same environment when
explicitly requested. Their source checkouts and model directories remain
separate so model identity is clear.

The common baseline is Python 3.11, Torch 2.7.1/cu128, torchvision 0.22.1 and
Transformers 5.1.0. The optional SAM installation adds its adapter-only packages
to that stack. Package constraints are in [constraints-core.txt](../../constraints-core.txt),
and default dependencies are in [requirements-core.txt](../../requirements-core.txt).

## Add Robotics to Static

Choose Level 3 with the installation selector from the checkout root:

```bash
bash tools/setup.sh --level robotics --plan
bash tools/setup.sh --level robotics
export KIMODO_ENV="$PWD/.runtime/pi3x-inference/venv"
source kimodo_blender/env.sh
```

The selector installs Static and then adds Kimodo to Pi3X. Omit `--level` for an
interactive question, or pass the explicit level for scripts. To add sparse
video-pose guidance, run `bash tools/setup.sh --level robotics --with-sam3d`
in the same environment before following
the [SAM 3D Body guide](sam3d-body.md). The flag installs pinned SAM/DINOv3 source
checkouts and adapter-only packages; it does not download weights.

The low-level [`setup_reference.sh`](../PI3X_GEOMETRY_REFERENCE.md#runtime) installs Pi3X
without Kimodo and adds separate SAM3 and Open3D runtimes. The command above
reuses Static's Pi3X environment while preserving those separate runtimes. If
Static used `PI3X_REFERENCE_ENV`, the selector reuses that path. SAM 3D Body
remains opt-in.

The low-level core script requires the selected level from `tools/setup.sh`
before it can install packages. The selector passes Static's Pi3X environment
as `--env`; set `PI3X_REFERENCE_ENV` before invoking it to choose a different
dedicated project path. The script installs into that environment, obtains
clean pinned checkouts, preserves the Torch/Transformers
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
| Kimodo | `kimodo_blender/upstream` | [G1/text weights](kimodo.md#authorized-g1-and-text-weights) |
| Pi3X | `external/Pi3` | [Reference checkpoint](pi3x.md#download-authorized-weights) |
| SAM 3D Body (optional) | `external/sam-3d-body` and `external/dinov3` via `--with-sam3d` | [SAM checkpoint and MHR](sam3d-body.md#authorized-checkpoint-and-mhr-download) |

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

# Component installation

Use one shared core environment for Kimodo, Pi3X, SAM 3D Body and source tools.
GVHMR uses its own environment because its validated PyAV pin conflicts with Kimodo.
The core installer does not install GVHMR; follow [its guide](install/gvhmr.md).
Model files remain separate downloads; obtain only the weights needed for your
workflow. Keep the checkout intact.

| Intended work | Install | Guide |
| --- | --- | --- |
| Install core model code together | One Python 3.11 environment | [Shared core installer](install/core.md) |
| Search assets, inspect recipes, record requests | Python 3.11+ source tools | [Base setup](SETUP.md#2-clone-and-create-the-environment) |
| Load assets, build rooms, animate cabinets or cameras | Compatible Blender | [Blender](install/blender.md) |
| Infer reference geometry/cameras from a video | Pi3X checkout, checkpoint and GPU environment | [Pi3X](install/pi3x.md) |
| Reconstruct visible source-video people (default) | GVHMR/SAMURAI and separate PMPose runtime, body models and weights | [Full human-motion stack](install/human-motion.md), [GVHMR BEDLAM2](install/gvhmr.md) |
| Generate new or changed human actions | Kimodo and text encoder; add SMPL-X/Blender for skinning | [Kimodo](install/kimodo.md), [body asset](install/blender.md) |
| Review sparse source-person poses for motion guidance | SAM 3D Body, pinned DINOv3, checkpoint and MHR | [SAM 3D Body](install/sam3d-body.md) |
| Optional object segmentation | SAM 3 | [Object tools](install/object-tools.md) |

## First setup

All components install on one Linux workstation (Ubuntu or WSL2) with one NVIDIA
GPU; see the [runtime policy](../MACHINE.md). Run `bash tools/setup_core.sh` once
to prepare `.venv` with the core model code. The [shared core guide](install/core.md)
explains paths, pins and installation checks. Follow each component guide for
model downloads and smoke commands. Install Blender separately for scene
authoring and SMPL-X skinning.

Use an isolated environment; do not upgrade another project's Torch or replace
an existing body add-on to make a new setup fit.

After installing the components for a full motion/scene run, register the actual
executable and model paths with `tools/configure_runtime.py` as shown in
[runtime setup](SETUP.md#5-configure-the-runtime), source `kimodo_blender/env.sh`,
then run `python kimodo_blender/check_runtime.py` and the unit tests. The tracked
runtime JSON is a template, not an installed environment. Inference adapters such
as Pi3X also accept explicit paths in their own commands.

## What the checks establish

Environment/version and CPU import checks verify setup and adapter interfaces.
Loading a checkpoint or running a GPU smoke example provides separate evidence;
neither establishes reference fidelity, motion quality or whole-clip consistency.
The guides distinguish historical local validation from newly documented install
steps. This documentation update does not install model runtimes or download
weights. The bundle's executed checks are listed in [validation](VALIDATION.md).

Model/body assets are obtained through the recipient's authorized upstream access.
Store authentication outside the checkout and logs. See
[distribution status](../DISTRIBUTION.md) and [external dependencies](../THIRD_PARTY.md).

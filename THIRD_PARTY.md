# External dependencies

This source bundle excludes third-party checkouts, installed packages,
model checkpoints, licensed body assets and authentication state. Integration
adapters remain project code; they require the dependencies below separately.
Consult each upstream's current terms before acquiring or redistributing it.

Concrete installation steps and verification boundaries are in
[component installation](docs/INSTALLATION.md).

| Component | Source | Role |
| --- | --- | --- |
| GVHMR BEDLAM2 | [upstream](https://github.com/mkocabas/GVHMR_BEDLAM2) | Separate motion runtime; revision `cac2d9dacc6b4b6f145ca02c2e6e616719fff916` |
| SAMURAI | [upstream](https://github.com/yangchris11/samurai) | Source actor masks; external model library |
| BBoxMaskPose/PMPose | [upstream](https://github.com/MiraPurkrabek/BBoxMaskPose) | Mask-conditioned 2D keypoints; separate environment |
| PyTorch3D | [upstream](https://github.com/facebookresearch/pytorch3d) | GVHMR CUDA support; selected v0.4.0 rotation functions included with BSD notices |
| Kimodo | [upstream](https://github.com/nv-tlabs/kimodo) | Motion model code; recorded revision `1aece8c124d73d255ceff5086d983b844c9f4e94` |
| Kimodo SMPL-X | [model](https://huggingface.co/nvidia/Kimodo-SMPLX-RP-v1) | External checkpoint |
| Llama 3 and LLM2Vec | Kimodo's upstream setup/download configuration | External text encoder and adapters |
| SMPL-X body | [project](https://smpl-x.is.tue.mpg.de/) | Authorized body asset, not bundled |
| Blender SMPL-X extension | [original SMPL-X extension](https://gitlab.tuebingen.mpg.de/jtesch/smplx_blender_addon) | The adapter requires `bl_ext.user_default.smplx_blender_addon`; see [compatibility](docs/install/blender.md) |
| Blender | [project](https://www.blender.org/) | Asset authoring, assembly and rendering |
| Pi3/Pi3X | [upstream](https://github.com/yyfz/Pi3) | Image-only reference geometry/cameras |
| SAM 3D Body | [upstream](https://github.com/facebookresearch/sam-3d-body) | Sparse pose references; MHR model supplied separately |
| SAM 3 | [upstream](https://github.com/facebookresearch/sam3) | Optional object segmentation |
| Blender MCP | [upstream](https://github.com/ahujasid/blender-mcp) | Optional interactive Blender connection; vendored add-on excluded |

PyTorch, NumPy, SciPy, Pillow, FFmpeg, CUDA and other installed dependencies keep
their own licenses. Reusable asset manifests preserve source
provenance. Project-authored code and assets are Apache-2.0; third-party code
and assets are not relicensed.

## Packaged motion helpers

The owner-authored tracker, camera, adaptation and v2 optimization helpers are
tracked in [the world-motion backend](tools/gvhmr/world_backend/README.md).
They were previously untracked additions in a neighboring PromptHMR checkout;
the owner confirmed their independent authorship. No upstream PromptHMR
implementation is included. The rotation compatibility module contains selected official PyTorch3D v0.4.0
functions with the complete upstream BSD license in the file, preserving legacy
numerical behavior. See [motion installation](docs/install/human-motion.md)
for runtime separation, known source-version gaps and external model inputs.

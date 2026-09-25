# Distribution validation

## Pi3X geometry update: 2026-09-12

The portable checkout passed 30 focused tests with Open3D enabled and no skips,
plus package, documentation-link, asset-index and generated-catalog checks.
A complete cached 32-frame reference was rebuilt through the published entry
with five native-camera overlays. All 8,123,784 finite non-person observations
were retained, including 1,446,203 below confidence 0.5. Strict measurement support
matched the previously validated reference. Source RGB, cameras, timestamps,
artifact hashes and untouched person/no-hit overlay pixels were checked; all
16 output images decoded and the five-view contact sheet was inspected.

See [Pi3X reference checks](pi3x_reference_checks.json) for the runtime, test
selection and evidence hashes. This validates cached rebuilding in the deployed
runtime. It does not establish a clean installation, a new inference result,
independent geometric accuracy, or a new authored-room/Blender validation.

## Earlier distribution and asset checks

Validation date: 2026-09-11. Source and packaging checks ran on CPU only; this
release does not claim a fresh model installation or GPU run.

- The original source snapshot passed 143 CPU tests both before and after
  relocation. Eight unchanged Blender libraries loaded with Blender 5.2.1,
  containing 11 furniture/plant collections and 31 registered material assets,
  with no linked datablocks or unpacked file textures.
- One existing Python 3.11 environment imported Kimodo, motion_correction,
  Pi3X and SAM 3D Body in the same process: Torch 2.7.1, torchvision 0.22.1,
  Transformers 5.1.0. No model was constructed or weights loaded. The old
  isolated Pi3X environment lacked torchvision; the shared installer includes it.
- The 17 source demo clips then listed passed complete decoding and timestamp
  checks. Those listings have since been removed; no footage is bundled.

Final release checks are recorded in [release checks](release_checks.json).
The initial [source validation](validation.json) and [Blender asset inspection](asset_load_validation.json)
remain scoped to the unchanged source and library payloads. Historical scene
lessons do not constitute new evidence for this distribution.

The shared installer has been statically reviewed and its plan exercised. Fresh
dependency resolution, checkpoint loading, CUDA inference, rendered appearance
and complete reference-to-scene execution were not rerun for this release.

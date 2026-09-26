# aha-3d

Reusable Blender assets, seven project skills and a video-to-room pipeline with
estimated source motion and generated new actions. Reference videos, completed
scene reconstructions, generated motion, renders and model weights are excluded;
supply your own footage under `references/`.

Source-video people default to **GVHMR BEDLAM2 -> room alignment -> Blender import**.
These are approximate monocular estimates, not ground-truth tracking. Room modeling
continues through Pi3X references and editable Blender assets/geometry. Kimodo
handles new or deliberately changed actions, with optional SAM guidance.
See the [GVHMR installation guide](docs/install/gvhmr.md) and
[new skill](.agents/skills/gvhmr-body-reconstruction/SKILL.md).

## Included

| Directory | Contents |
| --- | --- |
| `src/aha3d/` | Pipeline stages, configuration, Blender assembly, camera alignment, approximate motion, reference diagnostics and synthetic tracks |
| `assets/` | Eight registered libraries: 11 furniture/plant collections and 31 procedural material assets; searchable catalog, orientation metadata |
| `.agents/skills/` | All seven project skills, their scripts, references and RoomKit asset previews |
| `tools/` | Asset discovery/export, procedural asset builders, variants, coordination and experimental object-tool adapters |
| `references/` | Empty location for your own reference videos and annotations (ignored by Git) |
| `examples/` | Generic configurations and usage examples |
| `configs/` | Cabinet layouts, request presets and runtime configuration templates |
| `tests/` | CPU tests and optional Blender integration checks |
| `docs/` | Component installation guides, workflow contracts, skills guidance and historical technical lessons |

## Start

Browse the [generated catalog](docs/catalog/README.md) for assets, skills,
pipeline stages and demos. Open `docs/catalog/index.html` locally for searchable
cards and video previews; the page works offline.

The pipeline targets one Linux workstation (Ubuntu or WSL2) with one NVIDIA GPU;
see the [runtime policy](MACHINE.md). End to end:

```bash
git clone https://github.com/KevinXu02/aha-3d.git && cd aha-3d
export KIMODO_ENV="${KIMODO_ENV:-$PWD/.venv}"
bash tools/setup_core.sh --plan
bash tools/setup_core.sh                 # Kimodo, Pi3X, SAM 3D Body, source tools
source kimodo_blender/env.sh             # in every shell
python tools/configure_runtime.py --blender /path/to/blender-5.2/blender \
  --skin-blender /path/to/blender-4.5/blender \
  --kimodo "$KIMODO_UPSTREAM" --checkpoint "$KIMODO_CHECKPOINT"
python kimodo_blender/check_runtime.py
python -m unittest discover -s tests -v
```

Supply Blender and the model checkpoints yourself; download only the files you
need using the [installation guide](docs/INSTALLATION.md). GVHMR uses a separate
compatible environment; `setup_core.sh` does not install it. [Setup](docs/SETUP.md)
covers each step, including a lightweight source-only installation; asset
browsing needs only Python's standard library (`python tools/asset_index.py tree`).

For a new task, put your own reference input under `references/`, start a new
workspace under `scenes/<scene-id>/`, and use `runs/<scene-id>/<run-id>/` for
outputs. [examples/README.md](examples/README.md) shows a five-second motion
recipe and an asset-only Blender inspection command.

## Skills and assets

Maintain the human interface from source catalogs and skill metadata:

```bash
python tools/asset_index.py build
python tools/build_catalog.py build
python tools/build_catalog.py check
```

The generated [catalog](docs/catalog/README.md) links back to the asset registry,
skill instructions and pipeline code. Edit those sources, then rebuild the page.

Keep the checkout intact: skills use sibling project code and documentation.
See [the skill index](TOOLS_AND_SKILLS.md) and [asset catalog](assets/INDEX.md).
Each asset library is a regular local file; the bundle contains no symlinks into
the original project. Scene-extracted chairs and vases are included as normalized
reusable libraries, without the full scenes that originally contained them.

Furniture collections are distinct from materials. The count of 31 refers to
registered RoomKit material assets; other libraries also contain their own
embedded material dependencies. Historical unextracted scene candidates are
absent from this catalog.

## Scope and evidence

Use [minimal motion controls](docs/MOTION_CONTROLS.md), preserve exact timing,
resample rotations before skinning, and inspect contact, clearance and framing.
Synthetic track `in_frame` flags test the camera frustum, not occlusion.

The portable setup and asset checks are recorded in
[validation](docs/VALIDATION.md). They do not establish a fresh model installation
or end-to-end GPU inference run. Historical lessons retain their scope; source
scene/run evidence is omitted.

Project-authored code, skills and assets are licensed under the
[Apache License 2.0](LICENSE); [distribution notes](DISTRIBUTION.md) describe its scope.
[External dependencies](THIRD_PARTY.md) and licensed model files are acquired separately.

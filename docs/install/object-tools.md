# Optional object segmentation (SAM 3)

SAM3 object extraction is optional for ordinary room authoring. Prefer the
[text asset index](../../assets/README.md) and editable Blender geometry.
Successful mask export does not establish metric scale, correct placement or
completeness. See [object segmentation](../OBJECT_GENERATION.md).
Standalone Pi3X inference and Kimodo do not require SAM3. The first new-video
[Pi3X reference build](../PI3X_GEOMETRY_REFERENCE.md#build-the-reference)
requires SAM3 semantic inference; later rebuilds can reuse a complete
source-matched mask cache.

## Component matrix and source pins

| Component | Purpose | Separate environment and upstream requirements |
| --- | --- | --- |
| [SAM 3](https://github.com/facebookresearch/sam3) | Image masks for objects and first-video room references | The pinned source declares Python 3.11 support; the first-video installer uses a private Python 3.11 venv with Torch 2.7.1/cu128. |

The source deployment retained this revision. Clone it
from the bundle root, then inspect its pinned installation instructions:

```bash
mkdir -p external
git clone https://github.com/facebookresearch/sam3.git external/sam3
git -C external/sam3 checkout --detach 660a5e9e1b8b4c02c0ad97229b88a09a6e4ff5b7
```

This is a source pin, not a complete dependency lock. Do not install its
dependencies into the Kimodo environment.

## Installation routes

For a first-video reference, `bash tools/setup.sh --level static` installs SAM3 in a
standalone environment. For SAM3 code alone, run
`bash tools/object_pilot/segmentation/bootstrap.sh --standalone --no-checkpoint`.
The bootstrap checks out the documented source pin and installs the image API
dependencies. It does not alter the Kimodo environment. The historical
inherited-environment setup remains available without `--standalone`.

Request access to [facebook/sam3](https://huggingface.co/facebook/sam3) with your
own account. Run `.runtime/sam3-segmentation/venv/bin/python
tools/object_pilot/segmentation/prepare_runtime.py --runtime
.runtime/sam3-segmentation` to download checkpoint revision
`3c879f39826c281e95690f02c7821c4de09afae7`, check image API imports and
write `runtime.json`. The installer records `source_revision.txt` first.

## Adapter registration and smoke prerequisites

SAM 3 does not use `configure_runtime.py`: select their own Python executable
and explicit runtime/report arguments. Set `PYTHONPATH` to the selected upstream
checkout when it was not installed editable. Run `python -m pip check` and the
following imports in the corresponding environment before loading weights:

```bash
# SAM 3 environment
python -c 'from sam3.model_builder import build_sam3_image_model; from sam3.model.sam3_image_processor import Sam3Processor'
```

| Wrapper | Required local inputs in addition to installed code |
| --- | --- |
| `tools/object_pilot/segmentation/run.py --manifest INPUT.json --out NEW_OUT --runtime RUNTIME` | `RUNTIME/checkpoints/sam3.pt`, `RUNTIME/runtime.json`; manifest `objects` entries with `id`, `label`, `image`, and optional native-pixel `selection_bbox_xyxy`. |

The runtime metadata files above are real dependencies, not optional documentation.
Do not fabricate provenance records to get past a missing-file error. Retain model
snapshot revisions, source pins and environment/build reports from your own
installation. After a smoke run, review source agreement, scale/orientation,
completeness, contact and framing before accepting any object into a scene.

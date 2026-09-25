# Optional object segmentation (SAM 3)

This component is optional. Prefer the [text asset index](../../assets/README.md)
and editable Blender geometry for ordinary room work. Successful mask export does
not establish metric scale, correct placement or completeness.
See [object segmentation](../OBJECT_GENERATION.md). It is not a
prerequisite for Pi3X or Kimodo.

## Component matrix and source pins

| Component | Purpose | Separate environment and upstream requirements |
| --- | --- | --- |
| [SAM 3](https://github.com/facebookresearch/sam3) | Image masks for selected objects | Current upstream documents Python 3.12+, Torch 2.7+, CUDA 12.6+. The inherited Python 3.11 pilot is a local compatibility exception, not the portable default. |

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

For SAM 3, create a dedicated Python 3.12 environment, install a matched CUDA
Torch/torchvision pair following its pinned README, and run `python -m pip install
-e external/sam3`. Request access to [facebook/sam3](https://huggingface.co/facebook/sam3)
with your own account. The bundle's `tools/object_pilot/segmentation/prepare_runtime.py
--runtime .runtime/sam3-segmentation` downloads checkpoint revision
`3c879f39826c281e95690f02c7821c4de09afae7`, checks image API imports and writes
`runtime.json`. Before running it, create that runtime directory and record
`git -C external/sam3 rev-parse HEAD` into its `source_revision.txt`. The inherited
bootstrap uses a Python 3.11 environment with system-site-packages and deliberately
pinned overrides; it is the historical pilot setup, not the clean upstream route.

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

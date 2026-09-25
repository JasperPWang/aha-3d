# SAM3 object extraction

The image segmenter generates visible-object masks from source frames.
It is distinct from SAM 3D Body. Usage and mask review are described in the
[object segmentation guide](../../../docs/OBJECT_GENERATION.md).

With claimed output paths, use `prepare_inputs.py --frames-only` with source
video paths, native frame indices, IDs and short labels such as `chair`. Optional
`selection_bbox_xyxy` specifies native-pixel left/top/right/bottom bounds to pick
one instance. This path requires no manually drawn silhouette.

On the GPU run:

```bash
bash tools/object_pilot/segmentation/run.sh \
  --manifest YOUR_SOURCE_FRAME_MANIFEST --out YOUR_NEW_MASK_DIRECTORY
```

`--prompts` optionally reads a JSON mapping of object ID to a text phrase. Text
candidates are ranked by overlap with the selection box, or by confidence if no
box is supplied. Box-prompt alternatives are retained for review. The initial
pilot's old polygon fields are supported only to derive an instance-selection
box; their mask pixels never guide SAM3.

Inspect the exported overlays/cutouts, record selected variants and limitations,
then pass the reviewed mask manifest into `prepare_inputs.py --masks-manifest`. The raw segmentation manifest is marked pending review; keep a companion
review record and mark the prepared generation manifest with its reviewed status. Masks describe visible pixels and do not reconstruct occluded object boundaries.

Runtime: `.runtime/sam3-segmentation/venv`, official pinned source/weights,
Torch 2.7.1+cu128. Actual image inference passed on H200 with Python 3.11; upstream
README requests Python >=3.12, so broader Python/API compatibility is not claimed.
NumPy serialization casts bfloat16 scores/boxes/masks to float32. The base Kimodo
environment remains read-only. Weight access is independently gated and was
successfully granted for this user's pilot.

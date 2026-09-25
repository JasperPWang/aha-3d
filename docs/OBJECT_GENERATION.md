# Object segmentation for room authoring

Status: an earlier object-generation pilot (SAM 3D Objects and TRELLIS.2) was
completed and then deferred; its generation adapters are not included in this
release. Room generation continues through registered asset reuse and Blender.
The retained SAM3 segmentation runner prepares reviewed object masks from source
frames for furniture measurement and layout review. It is not invoked
automatically by the shared scene workflow.

## Tool roles

| Component | Role | Local entry |
| --- | --- | --- |
| SAM3 | Text/box-prompted visible-object masks from selected source frames | [Segmentation runner](../tools/object_pilot/segmentation/run.py) |

SAM3 is distinct from SAM 3D Body, the separate sparse human-reference component.
For generated people, continue using the [motion policy](MOTION_CONTROLS.md).

## Choose and prepare objects

First search the [text asset index](../assets/README.md#text-discovery). Reuse an
appropriate registered asset or extract a suitable candidate when that is cheaper
and allowed by the task's source restrictions. Keep simple room surfaces and
dimension-sensitive cabinetry parameterized. Generated meshes are candidates for
complex static furniture and decor; moving doors, drawers and contact geometry
still need appropriate separate parts and pivots.

Select clear frames with enough visible object pixels. Prefer one reconstruction
per object and use other views for review. Do not regenerate each video frame and
assume its meshes are temporally consistent. Record cropping, occlusion and source
resolution as input limitations. Segmentation selects visible pixels; it does not
reveal hidden surfaces.

New runs can start directly from source frames and optional selection boxes (historical or external input; omitted from this bundle).
No manual mask is required: use `prepare_inputs.py --frames-only`, then
`segmentation/run.sh --manifest FRAME_MANIFEST --out NEW_MASK_DIRECTORY` on the
GPU. The source manifest needs `id`, `label`, `source_video`, and native
`source_frame`; optional `selection_bbox_xyxy` uses original-image pixels and
identifies a particular instance among several matches. With no box, the highest
confidence text candidate is selected and still requires visual review.

The pilot originally used explicit selections (historical or external input; omitted from this bundle)
and text prompts (historical or external input; omitted from this bundle).
Its original polygon masks were rejected during visual review and must not be
used as approved model inputs. Their bounding boxes guide instance selection.
SAM3 saves text and box alternatives and a candidate manifest. Review the actual
overlays and cutouts before promoting a mask to model input.

Run all image preparation, model work, tests and rendering locally under the
[machine rules](../MACHINE.md), with [claimed output paths](COORDINATION.md).
The existing Pi3X environment supplies OpenCV for common preparation:

```bash
source kimodo_blender/env.sh
.runtime/pi3x/venv/bin/python tools/object_pilot/prepare_inputs.py \
  --config PATH_TO_SOURCE_SELECTION.json \
  --masks-manifest PATH_TO_REVIEWED_SEGMENTATION_MANIFEST \
  --out NEW_CLAIMED_INPUT_DIRECTORY
```

The resulting manifest has an `objects` array with stable `id`, full-resolution
`image` and `mask`, and `crop_rgba` paths. Masks and crops keep the visible
source pixels; no inpainting or background-generation step is introduced.

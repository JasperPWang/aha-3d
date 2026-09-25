# Optional source-fit measurements

Use when source masks or landmarks can clarify a visible mismatch. Model highlighting
does not require segmentation. Return to [layout review](../LAYOUT_INSPECTION.md)
for coverage and acceptance.

Choose diagnostics based on the error and available evidence. Try inexpensive
alternatives on ambiguous cases instead of treating one threshold or segmentation
method as mandatory. Boxes/center/extent deltas are useful for coarse layout;
mask IoU detects shape differences but is sensitive to cushion semantics and
occlusion; boundary distance locates displacement; convex support envelopes reduce
internal-mask noise but bridge real concavities. Use source-linked landmarks,
orthographic mesh footprints, dimensions and relational checks when segmentation
is unreliable. Collision checks establish none of these source correspondences.

For an optional SAM3 experiment, prepare a manifest with `objects` entries
containing `id`, exact source `image`, `source_frame`, `label` and optional
`selection_bbox_xyxy` selected from source RGB independently of the model. Run the existing
`tools/object_pilot/segmentation/run.py --manifest INPUT --out NEW_MASKS` in the
SAM3 environment. Inspect text and box candidates for identity, part coverage,
occlusion and background leakage. Never select the mask that best agrees with
the reconstruction. Record a review JSON with `manifest_sha256` and `selections`
keyed by record ID: `variant`, `object_id`, `mask_sha256`, `review_note`; an optional
`alternative_variant` requires `alternative_mask_sha256`.

```bash
"$PI3X_MESH_PY" -m tools.layout_inspection.source_fit \
  --geometry /absolute/export/model.npz --metadata /absolute/export/model.json \
  --outlines /absolute/outlines/objects.json --sam3 /absolute/masks/manifest.json \
  --review /absolute/mask-review.json --out /absolute/new-source-fit
```

The tool compares exact native pixel grids using isolated and first-hit visible
model masks, box and mask overlap, center/extent deltas, symmetric boundary
mean/P95 distances, convex support envelopes and reviewed alternative prompts.
Controlled mask perturbations demonstrate sensitivity to known position, size
and shape changes. An independent 2D translation/scale search is diagnostic only;
it never edits geometry or cameras. Any eventual correction must use consistent
multi-view geometry and preserve source camera/timing, not per-view warps.

The current 12-pixel boundary and 0.65 raw IoU heuristics are uncalibrated triage
settings for review, not universal acceptance standards. Raw failures remain
visible, while disagreement between prompt-based envelope checks requests
segmentation review. Agreement across prompts is useful evidence, not independent
ground truth. Poor cameras, clipping, unmodeled occluders and systematic mask errors
still require judgment. A high score never automatically accepts a scene.

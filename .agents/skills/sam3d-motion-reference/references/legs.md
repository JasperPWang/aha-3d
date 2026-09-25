# Full-body review and experimental leg guidance

SAM's MHR70 observations already contain hips, knees, ankles, heels and toe tips.
The historical adapter displayed arms and compiled hand constraints only. That
scope did not establish that leg predictions were unstable. Inspect the actual
source, visibility, pose plausibility and adjacent times before deciding usage.

## Reuse observations before inference

With the Pi3X or Kimodo NumPy/Pillow environment:

```bash
python -m aha3d.motion.observations \
  --person-id "$PERSON_ID" \
  --observations "$CACHED_OBSERVATIONS" "$EXTRA_SAME_PERSON_OBSERVATIONS" \
  --pi3x "$ORIGINAL_PI3X_BUNDLE" --out "$NEW_REVIEW_OUTPUT"
```

One input needs no merge identity, but leg compilation requires a reviewed person
ID. Use `--person-id` even for one legacy input when preparing it for the compiler.
With multiple inputs the ID is required. It is a caller-reviewed association,
not model identity tracking. Explicit ID conflicts, duplicate frames and changed
source/camera/keypoint contracts are rejected. Add `person_id` to new SAM selection
files; inference records it. Never silently replace a cached observation.
Model/checkpoint identity must also match; a merged bundle cannot attribute
mixed model estimates to the first input's version metadata.

Review `contact_*.jpg`, enlarged paired `crops_*.jpg`, individual overlays and
`review.json`. Cyan is anatomical left; orange is anatomical right. Crops preserve
source/overlay alignment and aspect ratio. Review records remain unreviewed until
an actual analyst authors a separate selection. In-frame flags and camera
projection agreement do not establish visibility or pose accuracy.

A later floor-aligned
camera export differs from the raw bundle even for the same source. Do not bypass
that guard. Reuse the original camera basis or explicitly generate observations
against a reviewed new basis. Rendering or drawing changes need no SAM inference.

## Select sparse useful directions

```json
{
  "schema_version": 1,
  "person_id": "person_a",
  "native_fps": 30,
  "native_frames": 240,
  "world_to_kimodo_rotation": [[1,0,0],[0,0,1],[0,-1,0]],
  "events": [
    {"source_frame": 180, "side": "right", "reviewed": true,
     "visibility": "visible", "review_note": "Replace with actual source/adjacent-frame observations"}
  ]
}
```

This illustrates schema only. Choose actual events and duration. Optional
`source_start_seconds` and event `target_time_seconds` map source PTS onto the
native 30 fps clock. Do not equate the source frame number with native time.
The proper world rotation must map world Z up to Kimodo Y up. Image-bound,
projection, identity, timestamp and review guards run before compilation.
The body basis uses the hip line and nominal world up; a wrong world-up estimate
can bias recovered directions. Clothes hide true joint centers even when legs
are visible. Occluded piano-side legs are not reliable control inputs.

```bash
python -m aha3d.motion.legs \
  --observations "$REVIEW_OUTPUT/observations.json" \
  --pi3x "$ORIGINAL_PI3X_BUNDLE" --selection "$REVIEWED_LEG_SELECTION" \
  --baseline "$NATIVE_BASELINE_NPZ" --route "$ROOT_ROUTE_JSON" \
  --out "$NEW_GUIDANCE_OUTPUT"
```

Compile on CPU in the installed Kimodo environment, with the installed upstream
on `PYTHONPATH`. The helper retargets thigh/shin directions to the baseline body's
proportions **before generation**. It keeps baseline root position, smooth root,
heading and global ankle orientation at each key; SAM body depth and toe twist
are not applied. Its output contains native `left-foot`/`right-foot` constraints.
These also constrain ankle/foot positions, ankle rotation, root height, smooth
root XZ and heading. Check every extra field and foot-height delta in `report.json`.
Only compatible `root2d` routes may be merged; conflicting overlapping keys fail.
This is neither post-generation IK nor a full-body pose transplant.

## Compare before adopting

Put `constraints.json` in a new recipe's `body.constraints`, retain the matched
baseline prompt/durations/seed/route, and use the standard `--motion-only` stages.
Changed constraints may affect the whole generated clip, including unconstrained
joints and times. Do not claim that preserved key root values freeze the full path.

Reusable CPU helpers in `aha3d.motion.legs`:

- `compare_motions(baseline_joints, candidate_joints, reviewed_keys, training_keys)`
  reports body-relative thigh/shin angular agreement separately at keyed events
  and withheld source times. Entire keyed times are excluded from withheld data.
  SAM agreement is not ground-truth motion accuracy. Native foot speed near its
  own low-height quantile and knee/ankle acceleration are explicitly labeled proxies.
- `compare_meshes(baseline_vertices, candidate_vertices, baseline_joints, fps, scale)`
  uses fixed vertex IDs from baseline ankle/sole neighborhoods for both variants.
  Check matching topology, vertex IDs and timestamps before calling. It applies
  one baseline-derived constant floor offset to both, then reports clearance,
  penetration, airborne frames and near-floor horizontal sole speed. The 4 cm
  near-floor threshold is a heuristic; toe roll and contact phase are not inferred.

Inspect actual SMPL-X A/B renders. Compatible skinned caches may be passed to the
shared mesh preview request/`finish` helper to avoid skinning again. Preserve
rational output timing and full decoding. A studio preview does not validate room
contacts. If promoted, assemble a new scene and check all actors, furniture and
camera again. Per-frame grounding must not hide a failed ungrounded comparison.

Actual piano results and adoption decision belong in the
[validated lesson](../../../../docs/lessons/colored-reference-leg-guidance.md).
Keep native feet experimental until evidence supports the intended action.

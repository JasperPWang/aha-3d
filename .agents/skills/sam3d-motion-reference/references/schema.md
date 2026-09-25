# Selection and output contracts

The same selection file can select SAM frames and later compile reviewed events.
Example values below are illustrative, not measurements or selected footage.

```json
{
  "schema_version": 1,
  "native_fps": 30,
  "native_frames": 450,
  "source_start_seconds": 0,
  "world_to_kimodo_rotation": [[-1,0,0],[0,0,1],[0,1,0]],
  "events": [
    {
      "source_frame": 120,
      "bbox_xyxy": [100,20,300,370],
      "side": "right",
      "reviewed": false,
      "review_note": ""
    }
  ]
}
```

`source_frame` refers to the original video's decoded frame ID and must exist in
both Pi3X RGB and cameras. `bbox_xyxy` encloses one person in **processed Pi3X
pixels**, not original-resolution pixels. Select actual boxes after viewing the
frames. Both hands at the same source frame must share the same box/person.

After viewing the exported SAM overlays and checking limb/facing plausibility,
set `reviewed: true` and record what was checked in `review_note`. The compiler
refuses unreviewed events. A review flag is analyst provenance, not a confidence
score or an extra permission requirement.

`side` is `left` or `right`. Optional `target_time_seconds` explicitly retimes an
event within the target clip. Otherwise use source presentation timestamp minus
`source_start_seconds`; native index is nearest frame at 30 fps. Duplicate same-hand
native frames and events rounding past the last frame are rejected. Sparse source
frame numbers must never be mistaken for native Kimodo frame numbers.

The example rotation maps reference-world coordinates `(x,y,z)` to Kimodo
`(-x,z,y)`. It is only an axis example: incorporate the actual room/recipe yaw.
The compiler requires a proper rotation mapping world +Z to Kimodo +Y. Scale and
translation are unnecessary for direction-only guidance and are not estimated.
It uses the already aligned Pi3X `c2w`, without applying `world_transform` again.

Optional per-event `facing_xz` overrides the target room heading while preserving
body-relative arm directions. Optional `root_xz_m` is an **authored smooth-root
position in Kimodo coordinates**, not a raw Pi3X pelvis coordinate. Baseline root
height is retained. Both hands at a shared native frame must agree on facing and
root override. Review the inferred hip-based heading for turned/occluded bodies.

Unsupported event fields fail instead of silently pretending to support a
contact target. Exact contact requires additional input-pose fitting, which this
adapter does not implement. Wrist local rotation comes from the baseline;
retargeting its parent arm changes wrist world orientation without recovering
SAM wrist twist.

## Observation artifact

Raw per-frame model outputs are in `raw/`; review overlays are in `overlays/`. Inference warps the Pi3X RGB/K into a centered equal-focal camera for SAM's full
path, preserving rays, then inverse-warps predicted pixels. It checks reprojection. The raw SAM camera translation is applied once. No estimated world root is compiled.

The initial implementation uses SAM MHR70 landmarks, resolving joint names rather
than treating their indices as SMPL-X joints. Confidence/occlusion are not supplied
by this public output contract. `in_frame` only describes image bounds.

`constraints.json` contains native `left-hand`/`right-hand` constraints plus any
provided root2d route. Each native record contains frame indices, local axis-angle
rotations, root positions and smoothed root. Loading it runs Kimodo skeleton FK. No rendered motion or collision validation is implied.

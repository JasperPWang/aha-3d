# GVHMR BEDLAM2 source-person workflow

Source-video people default to GVHMR estimation, same-shot room alignment, and
import into the authored Blender scene. Room modeling remains Pi3X-assisted
Blender modeling with existing furniture/material assets. Pi3X reference surfaces
do not replace the final room. Kimodo remains useful for new/changed actions and
documented fallback; SAM is optional sparse guidance for generation.

Start with the [skill](../.agents/skills/gvhmr-body-reconstruction/SKILL.md) and
[installation guide](install/gvhmr.md). Source provenance is pinned to
[GVHMR BEDLAM2](https://github.com/mkocabas/GVHMR_BEDLAM2/tree/cac2d9dacc6b4b6f145ca02c2e6e616719fff916).
No body models, weights, runtime environments or generated scenes are distributed.

## Local pilot evidence and limits

The original deployment (one 96 GB RTX PRO 6000) ran reference 30 end to end: 246 frames at 30 fps,
8.2 seconds, moving-camera DPVO preprocessing, full SMPL-X mesh export and a
saved/reopened Blender animation. Native and aligned results are approximate
monocular estimates; fine fingers, wrist/foot detail, occlusion and multi-person
identity handling are not established by this one pilot. These historical outputs
are excluded from the portable repository; installing the guide is not a new GPU
validation on the recipient's machine.

## Room alignment and Blender pilot

The source-room pilot used 24 same-video Pi3X frames and manually reviewed static
carpet patches. A single whole-clip similarity yielded body scale 0.96387 and
root path 2.666 m. Residuals against GVHMR's own camera-space joint estimates were
8.12 px median / 18.93 px p90, not ground-truth accuracy. Soles remained 2.7-6.8 cm
above the reference plane. Contact refinement was intentionally low priority.
Blender verification checked all 246 frames: maximum vertex difference 1.2e-7 m,
maximum intrinsic representation difference 0.58 px. Both videos fully decoded.

`tools/gvhmr/align_room.py` consumes `motion_native.npz`, a Pi3X bundle, and raw
body models; it validates matching source hashes and currently requires the
1280x720 / 30 fps pilot convention. Select a reviewed floor transform for each
new shot; optional `cameras_reviewed.json` takes precedence over `cameras.json`.
`tools/gvhmr/inspect_result.py` exports native parameters from inference outputs.
Run each helper with `--help` inside the configured environment for its arguments.

**The pilot `import_room_blender.py` clears the scene and builds a reference-mesh
demonstration.** Its `room_reference.npz` is a separately authored diagnostic
triangle/color cache, not an automatic output of the generic Pi3X helper. Do not
run its build mode on a modeled room. Instead use
[`import_cache`](../src/aha3d/blender/body.py) or the
[ensemble workflow](SCENE_WORKFLOW.md#parameterized-room-and-multi-person-assembly)
on a saved authored room and write a distinct output. Apply the recorded mapping
from Pi3X coordinates to the authored room to both body vertices and joints.
Keep source camera calibration separate from the requested delivery camera.

Preserve duration; resample rotations/translations before skinning when FPS changes.
Keep baked playback self-contained and verify all actors/cameras after reopening.
The helper scripts are staged adapters; `tools/indoor` has not gained an automatic
GVHMR backend selector. Whole-clip review and alignment remain scene-specific work.

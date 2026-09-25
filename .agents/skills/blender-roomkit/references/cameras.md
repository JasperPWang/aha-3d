# Source cameras and room/person assembly

Read when importing or exporting recovered cameras, or assembling a room with
people. Camera animation requires requested or established scope; static source
comparison cameras do not.

## Import and calibration

Use the [shared ensemble workflow](../../../../docs/SCENE_WORKFLOW.md#parameterized-room-and-multi-person-assembly).
Preserve evaluated lens, shift, image dimensions, pixel aspect, timestamps and
world/scale provenance. OpenCV-to-Blender camera axes are `diag(1,-1,-1,1)`.
Compare independent static landmarks at several timestamps; self-reprojection
alone does not establish agreement with the source.

Run the shared CPU camera preflight before expensive combined work. The importer
uses a fixed median pixel aspect, keys lens/shifts and checks residuals against
explicit tolerances. Both pixel-aspect axes must be normalized because Blender
clamps values below 1; do not directly assign a subunit `pixel_aspect_y` or loosen
tolerances to hide the resulting error. Preflight supplements evaluated Blender
checks rather than replacing them.

For imported source cameras, use evaluated `stage.camera_export` with
`ensemble.camera_check`. The legacy `render_clip.py` exporter supports only
perspective, horizontal sensor fit, square pixels and zero shift. Do not alter a
source camera to satisfy that restriction. Choose the exporter before a long
render; if rendering already succeeded, recover only the export tail.

For requested playback, declare output timestamps, translation interpolation,
rotation SLERP and endpoint/cut policy. Preserve source timing and validate all
output frames with the full perspective projection.

## People and final assembly

Use [GVHMR](../../gvhmr-body-reconstruction/SKILL.md) for visible source people;
Kimodo is for requested new/changed actions or documented fallback. Contact or
trajectory refinement requires an explicit request. Review room layout and the
requested camera before expensive body integration when practical.

The ensemble imports declared caches, retains source caches and checks every
person after saving. It does not author room geometry. Compare furniture facing,
footprints and usable circulation before people routes; preserve whole-clip body
scale/alignment and camera basis. Use the staged workflow for room/assemble/verify
configuration and [rendering](../../../../docs/RENDERING.md) for final output.

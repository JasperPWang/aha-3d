# Animation and rendering

Read only the section needed for requested animation or rendering. Resolve the
helper filenames below under the skill's `scripts/` directory. Run them with
Blender Python, `--python-exit-code 1` before `--python`, and arguments after `--`.
Use distinct outputs; the examples do not set mandatory duration or FPS.

## Animation JSON

```text
blender -b source.blend --python-exit-code 1 --python /path/to/skill/scripts/animate_scene.py -- --config recipe.json --out animated.blend
```

```json
{
  "seconds": 5,
  "fps": 24,
  "width": 1920,
  "height": 1080,
  "render_mode": "clay",
  "rigs": [
    {"name":"Door hinge", "parts":["Door panel","Door handle"], "pivot":[0,0,0.5], "axis":"Z", "angle_degrees":-90},
    {"name":"Drawer slider", "parts":["Drawer front","Drawer box"], "pivot":[1,0,0.8], "axis":"Y", "travel_m":-0.30}
  ],
  "motions": [
    {"object":"Door hinge", "property":"Open", "poses":[[0,0],[0.2,0],[4.4,0.8],[4.958333,0.8]]},
    {"object":"Drawer slider", "property":"Open", "poses":[[0,0],[0.5,0],[4.5,0.7]]}
  ],
  "camera": {
    "points":[[3,-4,1.7],[1,-4,1.7],[-1,-3.5,1.7],[-3,-3,1.7]],
    "look_start":[0,1,1.5],
    "look_end":[0,1,1.5],
    "lens":24,
    "sensor_width":36,
    "ramp_seconds":0.55
  }
}
```

Omit `rigs` when suitable controls exist. Inspect the actual property:
`roomkit_open_property` identifies `Open` or `open_amount`; older scenes may use
`Auto open` with master `Demo=1`. Preserve unlisted animation. Use
`clear_keyed_paths()` for selected channels, never `animation_data_clear()` on a
driven controller. Hinges need physical pivots and grouped moving parts; cabinets
need a hollow interior before opening. See [cabinet construction](assets.md#cabinets).

Pose times are seconds from frame 1, with quintic easing between poses. At 24 fps
for 5 seconds, 120 frames sample 0 through 4.958333 seconds. Place a completed
opening pose by the last sampled time. Check evaluated intermediate transforms,
actual opening clearance and the requested pace, not just keyed properties.

The camera path is arc-length-resampled cubic Bezier with cosine speed ramps and
quaternion interpolation between endpoint look directions. Inspect middle frames:
it need not keep a fixed target centered. Check walls, doors and furniture along
the full path; helpers do not provide general collision avoidance. The helper
creates a new camera and rebinds existing timeline markers; preserve cuts instead
when multiple shots are requested. For recovered cameras, read [source cameras](cameras.md).

## Rendering and resuming

```text
blender -b animated.blend --python-exit-code 1 --python /path/to/skill/scripts/render_clip.py -- --out preview --mode clay --scale 50 --stills 1,61,120
blender -b animated.blend --python-exit-code 1 --python /path/to/skill/scripts/render_clip.py -- --out clip --mode material --ffmpeg /path/to/ffmpeg
```

- Clay defaults to Workbench, retaining real materials.
- Material defaults to EEVEE with Raytracing disabled; actual scene lighting is needed.
- `--engine cycles` requests path-traced quality; CPU Cycles requires explicit
  intent and `--cycles-device CPU`. Configure devices in every render process;
  a saved GPU scene does not retain process-local preferences.
- `--stills` selects previews only. Adapt frame numbers, resolution, FPS and
  duration to the request; H.264 yuv420p requires even width and height.

Route task-specific rendering through `roomkit.configure_render`. Use
[render settings](../../../../docs/RENDERING.md) for pipeline/device options,
executables and graphics-context setup. Use Blender 5.2.1 for RoomKit's 5.2
assets; retain the separate Blender 4.5 SMPL-X exporter. Workbench/EEVEE need a
usable graphics context even with `-b`; do not silently replace a failed fast
render with CPU Cycles.

Preflight FFmpeg and camera export before a full clip. The legacy exporter requires
perspective, horizontal sensor fit, square pixels and zero shift; use the evaluated
pipeline exporter for [source cameras](cameras.md#import-and-calibration).

Follow [render execution](../../../../docs/RENDER_EXECUTION.md) for job waiting.
Resume requires matching job settings, including engine/samples/device.
Inspect actual stills, then verify complete PNG/frame counts, requested duration
and full MP4 decoding. `render_clip.py` writes timing/validation JSON and supported
camera calibration; a successful exit alone does not complete visual review.

## Calibration and validation

Exported matrices use OpenCV axes (right, down, forward) in metres and actual
rendered resolution. See [source cameras](cameras.md) for the full perspective
exporter. `demo_scene.py` is a helper integration example checking imported assets,
intermediate hinge/slider transforms and camera matrices; it renders one material
still, not a complete reconstruction or clip.

## Pi3X cameras and multiple generated people

For room/person assembly, preflight and source motion selection, read
[source cameras and people](cameras.md#people-and-final-assembly).

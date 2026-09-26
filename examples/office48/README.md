# Office demo scene

![Whitebox render of the office reconstruction](../../docs/media/office48_whitebox.gif)

A room reconstruction produced by the full agentic workflow from a 10-second
source video of a home office with a vaulted, beamed ceiling. It is the
"with the harness" office example on the
[project page](https://kevinxu02.github.io/real2sim-indoor-site/).

`whitebox.blend` (Blender 5.2) contains the editable room and the camera
recovered from the video:

- 401 objects: walls, beamed ceiling, windows, glazed door, trestle desk,
  swivel and guest chairs, ladder shelf, side cabinet, chandelier and props.
  Objects are named by role, such as `furniture/...` and `architecture/...`.
- The source camera animated over frames 1–303 at 30 fps, 1280×720.
- One neutral material. There are no image textures, linked files or people.

## Open and render

```bash
blender examples/office48/whitebox.blend
```

To render a single frame without the UI (frame 152 here), writing outside the
repository:

```bash
blender --background examples/office48/whitebox.blend \
  -o /tmp/office48/frame_#### -F PNG -f 152
```

Replace `-f 152` with `-a` to render the full shot. The scene uses Cycles; lower
`cycles.samples` for quick previews.

## What is and is not included

The source video is third-party footage and is not distributed. The textured
version of this scene is also withheld because its window views use image
crops from that video. Pi3X reference geometry, measurement records and the
agent's build scripts belong to the source run and are not included.

## Known limits

Recorded when the scene was reviewed:

- Metric scale is predicted from the video, not measured; there is no known-length
  calibration.
- The entrance side, hidden in the video, is an inferred completion.
- Small props, shelf contents, ceiling-beam joints, trestle carving and guest-chair
  backs are simplified.
- The placement check still flags approximations: the side cabinet overlaps the
  window-sill extent by about 4.5 cm, and the swivel chair has a support gap of
  about 2.3 cm above the rug. Most other flags are attached trim and construction
  interfaces.
- The camera is recovered and interpolated from the video, not survey-calibrated.

# Office demo scene

[![Whitebox render of the office reconstruction; click to play the video](../../docs/media/office48_whitebox.jpg)](../../docs/media/office48_whitebox.mp4)

A home office with a vaulted, beamed ceiling, reconstructed by the agentic workflow
from a 10-second video. It is the office example on the
[project page](https://kevinxu02.github.io/real2sim-indoor-site/).

`whitebox.blend` (Blender 5.2) contains the editable room and the camera
recovered from the video:

- 401 objects: walls, beamed ceiling, windows, glazed door, trestle desk,
  swivel and guest chairs, ladder shelf, side cabinet, chandelier and props.
  Objects are named by role, such as `furniture/...` and `architecture/...`.
- The source camera animated over frames 1–303 at 30 fps, 1280×720.
- One neutral material; the file is self-contained.

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

Replace `-f 152` with `-a` to render the full shot with Cycles.


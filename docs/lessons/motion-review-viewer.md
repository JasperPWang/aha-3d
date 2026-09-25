# Interactive human and G1 review

The working website embeds RoomKit demos backed by Three.js. Its opening
comparison is video, while its draggable scenes use WebGL. A working website
viewer does not support attributing a different viewer's startup failure to a
browser-wide lack of WebGL. The previous generic startup message made that
unsupported attribution; the maintained viewer now reports the actual error.
The original client-side context failure has not been reproduced conclusively.
During this integration, CLIP 39 reproduced a different startup failure:
`Unknown support: rear_wall`. Five object records named supports absent from
the export. The review importer now records these unresolved edges, retains
world-space geometry, and freezes those children instead of inventing supports.
The original support IDs remain in `source_support_id` and the validation report.

`tools/roomkit_browser/motion_review.py` builds an interactive review portal from
existing RoomKit scene JSON and optional source-frame mesh tracks. It uses the
maintained viewer, template and lossless two-second animation streamer. It does
not fork the renderer or regenerate motion. One iframe is active at a time;
switching releases the old renderer/context before loading the next. Switching
native/v2 within a case preserves the frame and camera. The direct-view link
opens a standalone viewer for diagnosis.

Human tracks have half-open `active_frame_range` intervals in original video
frames. Finite endpoint padding satisfies the shared stream format; the viewer
hides each actor outside its observed interval. Existing generated interactions
without this field retain their stage visibility behavior. G1 uses its existing
rigid-link transforms, generation-stage controls and prescribed lamp state.

Build with the configured NumPy Python and Node.js:

```bash
python tools/roomkit_browser/motion_review.py \
  --manifest /path/to/review-input.json --out /path/to/new-output \
  --node /path/to/node
```

The module docstring specifies the input schema. Existing `.blend` rooms can be
exported read-only with `export_scene.py --auto --no-sha`. Inputs and saved rooms
are preserved. Per-case notes must identify remaining motion-quality limits;
browser operation is separate from motion acceptance.

The 2026-09-20 review serves five source-human clips (13 people, native/v2) and
the latest local-frame corrected G1 lamp example at
<http://localhost:8793/interactive/> after forwarding port 8793.
Only that G1 example has the latest local-frame rerun; the other five G1 examples
were not regenerated. Source videos below each human view have independent
playback, explicitly labeled. Full-rate 30 fps geometry replaces the previous
5 fps rendered inspection panels. Scene cutaways affect viewing only.

Local input manifest and logs:
`tasks/motion-viewer-integration-20260920/`.
Artifacts and verification:
`runs/_tools/all-people-reconstruction/20260920/interactive/`.
`export_validation-r2.json` compares all active vertices of 26 actor/variant tracks
directly against the original mesh arrays without hashes. Browser QA is in
`qa-motion-review.mjs`; `qa-r2/validation.json` records its actual outcome and
screenshots. It exercises loading, interval boundaries, sampled source vertices,
stage switching, rigid G1 tracks, lamp changes, scrubbing, playback, orbit and
mobile width using Chromium/SwiftShader. This environment does not establish
the behavior of a user's GPU/driver. Visual inspection remains separate.

The source website is unchanged. The diagnostic review is not a new selected
room delivery; previously documented placement, foot sliding, numerical-gate and
seat-contact problems remain visible.

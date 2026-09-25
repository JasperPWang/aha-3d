---
name: blender-browser-demo
description: Convert a saved aha3d Blender scene into a standalone interactive browser demo with hold-to-grab furniture, bounding-box movement limits, cabinet controls and existing baked mesh animation. Use for scene-to-web demo requests and repeatable conversion without per-scene viewer edits.
---

# Blender browser demo

Use the maintained project script, not a copied viewer or a scene-specific HTML
patch. Resolve the aha3d repository from the working directory or this
skill's resolved path. The implementation lives in `tools/roomkit_browser/`.

Claim the chosen new run directory before submitting; follow the project's task
coordination and runtime rules; this standalone CPU/browser workflow runs
locally in the foreground. Select a saved `.blend` from the requested
scene's current state. Source files are opened in background Blender and never
saved or overwritten.

```bash
python3 tools/roomkit_browser/demo.py \
  --source scenes/SCENE/blender/scene.blend \
  --out runs/SCENE/browser-RUN --blender /path/to/blender
```

No scene config is required. The command discovers existing semantic roots,
complete legacy furniture empties, native or supported `Open` cabinet controls,
and shape-key/armature mesh animation. It derives overview/plan framing and roof
cutaways, builds self-contained HTML, and runs browser checks. The source frame
range and FPS are preserved; this command never generates a new human action.

Install the Node dependencies and Playwright browser as described in
`tools/roomkit_browser/README.md`.

A finished command is not a delivery. Inspect `run.json`,
`discovery.json`, `validation.json` and `orbit.png`/`plan.png`. A failed run retains
`pipeline.log`; fix the reusable implementation and retry into a new run directory.
Do not silently hand-edit individual scene configs to make automatic QA pass.

Automatic identification is conservative. Unowned loose meshes stay static and
are listed in discovery. Unsupported/nested articulation or changing mesh topology
fails export. Do not claim every object is draggable or that inferred roots have
proven semantic completeness. Preserve existing semantic metadata and support IDs;
new authored scenes should use the project's semantic asset contract for complete
objects. Existing actor animation is replayed, not collision-aware or replanned.

For access, reuse the existing preview server when available. Add
`--serve /absolute/server-root/scene-name.html` to atomically mirror the HTML only
after validation. Claim that exact output too. This flag does not start a server.
When a server is needed, serve the output directory with Python HTTP on an available
remote port and retain the process. Open the remote service address through the app;
never feed an observed browser-local forwarded port back as the remote target.
Confirm HTTP success before delivering the URL. A filesystem path alone is not a
working website link.

For schema, limitations and dependencies, read the project's
`tools/roomkit_browser/README.md`. The grab interaction and AABB limits are shared
viewer behavior, so later conversions inherit fixes without custom HTML editing.

For requested tabletop physics or procedural swaps, add `--tabletop`. This uses
registered asset templates, explicit table support discovery, convex rigid-body
collisions and seeded initial placements. Inspect `tabletop-validation.json` and
`tabletop-original.png` / `tabletop-final.png` as well as ordinary QA. The current
swap scope of this flag is tabletop objects; chair replacement uses `--chairs`. Keep
physics assumptions and source animation limits distinct. See the README's
"Tabletop physics and seeded swaps" section before extending this mode.

The sidebar opens on Scene graph, with live world-bounds layout, assigned support
edges, joint values, linked selection and JSON download. The Controls tab retains
the interaction controls. Inspect scene-graph-validation.json and graph screenshots
when changing hierarchy or layout presentation. Support grouping is not proof of
current physical contact.

For requested whole-chair swaps, use `--chairs` with trusted canonical source
chair roots. It preserves seat count, native asset scale and heading, validates
the current placement against component proxies, all exported human frames,
sampled cabinet motion and relative navigation, then applies the whole set. Chairs sharing a source model receive one matching
alternative of the same declared seating type. Missing type metadata or no
alternative keeps the current layout. Swaps retain current chair anchors, and
chairs remain draggable before and after a swap; never count the source model as a swap.
Inspect chair-validation.json and chairs-*.png. The README documents exact limits;
these checks do not establish ergonomic compliance or continuous contact.

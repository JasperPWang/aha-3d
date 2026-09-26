# Generic input examples

These files are hand-authored configuration examples, not a generated room,
recorded reference or motion result. Configure the runtime first.

Source footage and previews are indexed under [references](../references/README.md).

## New motion workspace

Claim the intended scene and run paths before copying or executing:

```bash
python tools/task_claim.py claim new-scene --owner example-owner \
  --title 'Create a new scene workspace' --paths scenes/new_scene runs/new_scene
cp -r examples/new_scene scenes/new_scene
bash tools/indoor plan new_scene --recipe walk
bash tools/indoor run new_scene --recipe walk --motion-only
```

The motion-only scope generates, resamples and skins without opening a room.
It still needs the configured Kimodo and SMPL-X dependencies. The recipe requests
five seconds at 24 fps (120 output frames). For full assembly, provide your own
`scenes/new_scene/blender/room.blend`, record its provenance in `STATE.md`, and
run without `--motion-only` after reviewing placement and camera.

## Office demo scene

[office48](office48/README.md) is a finished room reconstruction with its recovered
source camera. Open `office48/whitebox.blend` in Blender 5.2; no runtime
configuration is needed.

## Inspect reusable Blender libraries

With `BLENDER_BIN` pointing to a compatible Blender executable:

```bash
"$BLENDER_BIN" --background --factory-startup \
  --python tools/inspect_bundle_assets.py -- --out /tmp/indoor-assets-check.json
```

This appends each declared collection/material from every registered library,
checks dependency locality and records geometry bounds. It saves no source scene
and does not render or judge appearance. Existing Blender integration scripts in
`tests/blender/` exercise placement/articulation separately.

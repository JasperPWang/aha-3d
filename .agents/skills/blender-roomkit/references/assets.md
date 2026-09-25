# Furniture and materials

Read the section for the current operation. Search the project's
[asset index](../../../../assets/INDEX.md) and registered manifests before
building furniture or materials. Resolve current payloads through the registry;
use their dimensions and thumbnails instead of a copied inventory here.

## Placement and replacement

Prefer `roomkit.place_asset(item_id, ...)` for semantic scenes: it resolves a
registered item into a stable tagged root with independent object trees and,
for articulated items, remapped controllers. Use verified source fronts and
`facing_target`/facing intent for upright directional objects. Inspect actual
seat/backrest or mounting-to-spout geometry; footprint yaw cannot resolve front/back.
Unknown orientation needs inspection, not an invented -Y tag. Details:
[orientation](../../../../docs/ASSET_ORIENTATION.md) and
[semantic variants](../../../../docs/SCENE_VARIANTS.md).

Move complete roots. `tag_root` may wrap a mesh in an Empty: use its returned
root rather than transforming the reparented child. `adopt_group` accepts explicit
parts and a reviewed placement matrix; its default pivot is the world origin.
Preserve support relationships, surface roles, materials and internal joints.

After scene placement or model replacement, run the
[placement check](../../../../docs/PLACEMENT_CHECK.md). The layout renderer already
runs it; avoid a duplicate immediately beforehand. Inspect flagged pairs and
source views, repair demonstrated errors and rerun affected checks.
For placement/replacement in a reference reconstruction, also complete the
[per-item X-ray review](../../../../docs/LAYOUT_INSPECTION.md#object-review-default-and-repair-loop)
for changed main items and affected neighbors before advancing.

Validate temporary replacement candidates, then update the current registered
payload under the same stable ID/path and refresh its manifest/registry/catalog
metadata. Preserve native controls; do not retain obsolete libraries solely for
reproducibility. Static extracted assets have baked modifiers and separate editable
parts; resizing needs deliberate geometry edits. Configurable cabinets can be
regenerated from recipes.

The compatibility `import_collection(library, name, location, rotation, scale)`
retains source axes and takes Z rotation in degrees. Repeated imports share the
collection, so mesh edits affect every instance. Make instances real and copy
meshes/materials for unique variants. Resolve `roomkit-v1` through
`aha3d.assets.resolve`; its canonical payload is
`assets/roomkit/v1/roomkit_furniture_materials.blend`.

## Material behavior

- Generated coordinates stretch under nonuniform scaling; apply scale or adapt
  texture Mapping when materially resizing furniture.
- World Position materials (including plaster/floorboards) stay aligned to world
  axes rather than following object rotation; check `world_coordinates` in manifests.
- Rug borders expect rectangular meshes. Television glass and bulbs are intentional
  dark/emissive special cases, not exposure errors.

For seeded PBR maps or Blender/browser material comparison, read
[procedural materials](../../../../docs/PROCEDURAL_MATERIALS.md).

## Cabinets

Pass an explicit [layout or preset](../../../../docs/SCENE_VARIANTS.md#configurable-cabinet-construction)
to `roomkit.cabinet` for drawers, door types, open sections and interiors. Keep all
parts under one placement root, preserve independent native controls and start
closed unless animation is requested. Use the articulated export/import path;
static export discards controls. For keyframes, read [animation](workflows.md#animation-json).

## Extracting another scene

Use `scripts/export_assets.py` on a saved source with a distinct output. Selection
JSON contains `source_frame`, `material_prefix`, `furniture` entries (`root`,
`name`, `catalog`, `description`) and optional `material_catalogs`. Each item needs
verified `orientation` evidence unless its root already has `asset_orientation_json`.
Declare actual front/up, origin and semantics; the exporter normalizes axes and
rejects missing or merely declared orientation.

```text
blender -b source.blend --python-exit-code 1 --python /path/to/skill/scripts/export_assets.py -- --config selection.json --out new-library --previews
```

Static export evaluates descendants at the selected frame, bakes geometry, copies
materials and packs encountered textures. External coordinate-object references
are rejected; inspect unusual nested node groups or rigs for extra dependencies.
For an operable cabinet, use `--articulated` with exactly one furniture root or
`aha3d.blender.articulated.export_articulated`. It retains supported
modifiers/drivers/limits, strips timeline keys and initializes controls closed.
Import with `place_asset` or `import_articulated`, then verify independent controls
and saved-scene reopening before replacing the registered payload.

## Blender UI

Add the directory containing the `.blend` and catalog under Preferences → File
Paths → Asset Libraries. Use the Asset Browser or File → Append. A data-only
library may have an empty scene viewport because its collections are unplaced.

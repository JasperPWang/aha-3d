# Semantic scene variants and operable cabinets

Scope accepted by the user on September 10, 2026: future scenes carry explicit
object/surface semantics, models and materials can be replaced independently,
and cabinet assets retain native independent opening controls. Implementation
and validation evidence are maintained in the integration handoff (historical or external input; omitted from this bundle).

## Authoring contract

Use the [RoomKit skill](../.agents/skills/blender-roomkit/SKILL.md) and search the
asset index (historical or external input; omitted from this bundle) before building furniture or decor. New complete
objects have a stable semantic root. Put all of one chair's geometry below that
root; do not leave seats, legs or newly adapted parts outside its ownership.

- `instance_id`: stable identity of the placed object, independent of its mesh.
- `semantic_class`: slash-delimited category, for example
  `furniture/seating/chairs`, `furniture/storage/cabinets`, or `decor/tabletop/vases`.
- `asset_id`: source library item or generator ID; replacement updates this.
- `support_id`: optional identity of the table, cabinet or other supporting root.
- `surface_role`: purpose of a renderable surface, such as `wall_finish` or
  `floor_finish`. Per-material-slot roles are also supported.

Custom properties in the saved Blender file are authoritative. Exported semantic
JSON is derived, not a second editable registry. IDs survive geometry replacement;
they must be unique when placing or duplicating another instance.

```python
from aha3d.blender.roomkit import box, place_asset
from aha3d.blender.semantics import tag_root, tag_surface, tag_support

chair = place_asset('roomkit-v1/chair-walnut-lounge',
                    location=(1.2, 2.0, 0), rotation=30,
                    instance_id='dining-chair-01', project_root=project_root)
floor = box('Floor', (0, 0, -.06), (6, 5, .12), material=floor_material,
            surface_role='floor_finish')
table = tag_root(complete_table_root, 'furniture/tables', 'table-01')
tag_support(table, xmin=-.8, xmax=.8, ymin=-.4, ymax=.4, z=.75)
vase = tag_root(complete_vase, 'decor/tabletop/vases', 'vase-01',
                support_id='table-01')
```

Always use the returned root from `tag_root`: tagging a mesh or collection instance
wraps it with an Empty while preserving its world transform. For scattered legacy
parts, `adopt_group` requires an explicit complete object list and accepts a
reviewed placement matrix. Object names help author that migration map but are
not an automatic classification guarantee. A replacement root should be at the
asset's contact origin (floor or tabletop), with its front along local -Y.
Follow the [orientation contract](ASSET_ORIENTATION.md): slots need an explicit
authored/reviewed frame, and registered models need item-level source orientation.
`place_asset` normalizes actual source axes before placement. Legacy roots without
reviewed orientation require migration before automated model replacement.

## Independent model and material recipes

The current-quality policy adopted September 13, 2026 keeps asset IDs and paths
stable across reviewed payload improvements. Each recipe still records exact
library hashes. The [refresh tool](../tools/asset_quality_upgrade/README.md)
selects upgraded IDs and protects scene-local geometry/material edits using a
source-content signature. Saved scenes and rendered videos do not change merely
because the registered library was upgraded.

The [variant tool](../tools/scene_variant.py) opens a saved source in background
Blender, preflights selectors and registered assets, applies the recipe, and saves
a distinct `.blend` plus provenance and semantic JSON. Existing outputs are not
overwritten. `needs_extraction` candidates must be normalized and registered first.

```json
{
  "schema_version": 1,
  "seed": 42,
  "models": [
    {
      "selector": {"semantic_class": "furniture/seating/chairs"},
      "asset_id": "roomkit-v1/chair-walnut-lounge",
      "fit": "native"
    }
  ],
  "materials": [
    {"surface_role": "wall_finish", "asset_id": "roomkit-v1/warm-ivory-lime-plaster"},
    {"surface_role": "floor_finish", "asset_id": "roomkit-v1/natural-oak-floorboards"}
  ],
  "clear_material_override": true
}
```

Either operations list may be omitted. A selector may instead specify
`instance_ids: ["dining-chair-01"]`. Class selectors include subclasses. Use
`asset_ids` instead of `asset_id` for seeded choices from an explicit compatible
pool. `fit` must be `native` (asset dimensions under the retained placement
transform) or `uniform_footprint` (uniform geometry scale to fit the old local
footprint). This is not seat-height fitting or an automatic contact solver.

Material parameters support `color` (linear RGB/RGBA) and `roughness`; these
explicitly override the relevant shader inputs, including existing links.
Object-level material slots isolate the selected surface from other users of
shared mesh/material data. Existing texture coordinate systems remain intact;
generic pattern scale/rotation remapping is not implemented. The library's
[coordinate conventions](../.agents/skills/blender-roomkit/references/assets.md#material-behavior)
still apply. `clear_material_override` explicitly reveals materials in a saved
clay scene. It does not itself choose a render engine or lighting.

With claimed output paths, source `kimodo_blender/env.sh`, set
`PYTHONDONTWRITEBYTECODE=1`, then run:

```bash
"$KIMODO_ROOT/tools/blender-5.2.1-linux-x64/blender" -b -t 4 \
  --python-exit-code 1 --python tools/scene_variant.py -- \
  --source SOURCE.blend --recipe VARIANT.json --out NEW.blend --dry-run
```

Remove `--dry-run` to save the variant. Feed the saved result to an ordinary
shared-pipeline recipe as its `source`. Existing pipeline snapshots remain
immutable. A material operation targeting geometry replaced by the same recipe
must be applied in a second recipe to the saved result, where the new surfaces
can be selected unambiguously.

Support-plane bounds and gaps are diagnostic checks; they do not establish full
collision/occlusion clearance. Active-contact or animated furniture replacement
is rejected until an appropriate motion/contact update is supplied. Review
actual floor support, framing and furniture/person contact before rendering a
scene variant for delivery. Random seeds reproduce choices within a fixed recipe
and asset inventory, not arbitrary future library revisions.

## Configurable cabinet construction

[Cabinet recipes](../configs/cabinets/) describe columns left-to-right and sections
bottom-to-top. Column `width` and section `height` are relative weights. Each
section chooses `open`, `door_left`, `door_right`, `double_door`, or `drawers`.
Shelves and dividers accept a count or ordered fractional positions inside that
compartment. Drawer stacks accept a count or bottom-to-top height weights.

```python
from aha3d.blender.roomkit import cabinet

root, controls = cabinet(
    'Kitchen mixed cabinet', location=(1.5, 2, 0), size=(1.6, .65, 1.45),
    material=front_material, interior=inside_material,
    instance_id='kitchen-cabinet-01',
    layout={
        'columns': [
            {'width': 2, 'sections': [
                {'front': 'door_left', 'shelves': [0.35, 0.7]}]},
            {'width': 1, 'sections': [
                {'front': 'drawers', 'drawer_heights': [2, 1, 1]}]}
        ]
    })
```

Convenience presets are `default`, `three_drawers`, `mixed`, and `open_shelving`.
Size describes the carcass; doors and handles protrude forward. Thickness, gaps,
opening angle and drawer travel are configurable. Physically impossible layouts
are rejected before construction: drawer boxes need sufficient height, partitions
need positive usable spacing, and drawers cannot share their moving volume with
fixed shelves. The current generator supports rectangular cabinets with hinged
doors and sliding drawers. Curved cabinetry, sliding/folding doors and appliance
mechanisms require additional generator types.

New layout controllers expose `open_amount` from 0 (closed) to 1 (fully open),
`joint_id`, `joint_type`, and `roomkit_open_property`. Handles move with their
doors; drawers have bottoms, backs and sides; interior shelves remain fixed.
Each cabinet has a separate control hierarchy. Initial pose is closed; creating
an operable asset does not automatically add a camera path or animation.

```python
from aha3d.blender.roomkit import animate_property

animate_property(controls[0], 'open_amount',
                 poses=[[0, 0], [1, 1], [2, 1], [3, 0]], frames=96, fps=24)
```

The controls use native Blender drivers/keyframes and persist without an add-on.
`roomkit.cabinet_controls(root)` discovers them;
`roomkit.set_open(root, amount, joint_ids=None)` adjusts all or selected joints;
`roomkit.animate_open(root, joint_id, poses, frames, fps)` addresses one stable
joint without calculating hinge transforms in a scene-specific script. Semantic
JSON exports include joint records grouped by owner instance ID. These controls
do not prevent adjacent open doors/drawers or room obstacles from intersecting.
Calling `cabinet` without `layout` preserves the historical two-door/one-drawer
geometry and writable `Open` properties. New construction should pass a layout
or preset explicitly. `animate_property(..., 'Open', ...)` also recognizes new
controllers' declared property for compatibility; direct property editing should
use the actual declared property.

## Portable articulated assets

The [articulated exporter/importer](../src/aha3d/blender/articulated.py)
preserves a complete native hierarchy, drivers, limits, custom properties and
self-contained materials. Export strips scene timeline keys from the copied
asset and initializes its controls closed; it does not change the source scene.
Import creates independent object/control trees and remaps their driver targets.
Ordinary shared collection instances are suitable for static furniture but do
not provide independent cabinet controls.

```python
from aha3d.blender.articulated import export_articulated, import_articulated

manifest = export_articulated(root, new_library_directory,
                              asset_name='RK Cabinet - Mixed Storage')
instance = import_articulated(library_path, 'RK Cabinet - Mixed Storage',
                              location=(3, 0, 0), instance_id='cabinet-02')
```

For a registered articulated item, use `place_asset` so source identity and
semantics are resolved automatically. The static exporter also accepts
`--articulated` with a one-root selection JSON. Publish the reviewed current
library payload after export/import, independent-control, reopen and visual
checks, and update its manifest and registry checksum. Unsupported external driver/material/object dependencies are rejected;
the exporter is intentionally limited to self-contained Empty/mesh furniture rigs.

## Demonstration and evidence

The demo scene state (historical or external input; omitted from this bundle) links the current
saved scenes, stills and validation. It is an authored functionality fixture,
not a reconstruction from reference video. Original scene revisions used to
extract a chair or vase remain read-only and keep their original status.

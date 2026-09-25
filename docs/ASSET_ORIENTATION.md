# Asset orientation and scene facing

Scope: the user's September 10, 2026 request to fix coordinate declarations and
audit frequent seating/faucet assets. Unified workflow intake and full workflow
variant integration are separate deferred work. Implementation and validation
are recorded in the task handoff (historical or external input; omitted from this bundle).

## Actual source frame versus desired scene facing

An asset declares its actual local front, up axis and placement origin. The
registered `place_asset` path rotates this source frame into canonical **front
-Y, up Z**, then applies scene placement to a stable semantic root. All lengths
are metres. A raw footprint's long-axis yaw, especially yaw modulo 180 degrees,
does not determine which side is the front. Review visible backs, seats, doors
or spout extension in the source when declaring direction.

Seating front is where a seated person faces. Cabinet front is the door/access
side. Faucet front is the horizontal direction from mounting stem toward the
spout; the downward outlet tangent is a different direction. A rotationally
symmetric vase has no unique horizontal front.

The pure [contract module](../src/aha3d/orientation.py) validates:

```json
{
  "schema_version": 1,
  "front_axis": "X",
  "up_axis": "Z",
  "symmetry": "none",
  "origin": "mount_center",
  "semantic_front": "spout",
  "status": "reviewed",
  "evidence": "Source-linked audit with mounting and outlet landmarks and reviewed previews"
}
```

- Signed X/Y/Z front and up axes must be perpendicular. The mapping is a proper
  rotation, never a reflection. A +X source front requires -90 degrees about Z;
  a +Y source front requires 180 degrees.
- `symmetry` is `none` or `continuous_z`. The latter means rotational symmetry
  about the declared up axis, and requires `front_axis: null`, `semantic_front:
  "none"`. Canonical output is Z-up.
- `origin` is `floor_center`, `mount_center` or `source_root`. Floor-based static
  exports center XY bounds and place minimum Z at zero. Mount/source exports keep
  the declared root origin; author a mounting root before exporting world-space
  faucet curves. Articulated exports preserve their declared physical root,
  including the generator's carcass floor center rather than handle/open bounds.
- `semantic_front` is `seating`, `spout`, `door`, `generic` or `none`.
- `status` is `unknown`, `declared`, `authored` or `reviewed`. Automated placement
  and export require `authored`/`reviewed` with nonempty evidence. Authored means a
  generator or explicit construction defines the geometry; reviewed means the
  actual source has been inspected. A status string is not an automatic geometry
  recognition result. Keep the source and rendered evidence behind the claim.

## Storage, registration and migration

New exports store item-level `orientation`, original `source_orientation`, and
`asset_orientation_json` on the native root/collection. There is no inferred
front from a legacy library-wide `forward` string. The static and articulated
exporters accept an explicit orientation or an existing root declaration;
missing/unverified declarations fail before publishing an asset.

Existing versioned libraries remain immutable. The separate
[review registry](../assets/orientation_reviews.json) binds each reviewed item to
its exact library version and datablock name. The index derives effective item
orientation from this review or a new manifest and checks for stale review data.
It does not copy a generic `forward: -Y` into verified metadata. Rebuild the
[asset index](../assets/README.md#text-discovery) after editing canonical reviews.

In Blender, `tag_orientation(root, metadata)` records the actual frame without
moving geometry. It is useful after explicitly reviewing a legacy complete
object, but is not itself a coordinate conversion. Never relabel a +X model -Y
to make a check pass. Export and reimport to normalize, or deliberately migrate
the placement root while preserving geometry and native joint transforms.

## Place and check facing

```python
from aha3d.blender.roomkit import place_asset, face_towards
from aha3d.blender.orientation import facing_report

chair = place_asset('roomkit-v1/chair-walnut-lounge',
                    location=(1.5, 0, 0), facing_target=(0, 0, 0),
                    instance_id='chair-east', project_root=project_root)
# A target object may instead be a table/sink root with a stable instance_id.
face_towards(chair, table_root)
report = facing_report(chair)
```

`rotation` remains degrees around Z; an omitted rotation means zero. Specify
either rotation or a facing target. Facing targets are explicit world points or
semantic objects; they are not automatically inferred from nearby furniture.
Object-target relations use stable IDs and are saved as `facing_target_json`.
Changing a target's location can invalidate an existing placement: the report
detects this; no automatic driver is added. Semantic exports include the declared
frame, relation and available facing check.

The yaw helper preserves world location/scale and child rig locals. It requires
upright positive uniform transforms, compatible ancestors, and a static root;
it rejects reflected/sheared/nonuniform or animated/constrained placement roots,
coincident horizontal targets, missing/duplicate target identities and targets
inside the rotating asset. Tilted wall mounts need an explicitly reviewed full
transform. Symmetric assets have no `face_towards` operation.

The low-level `import_collection` compatibility helper retains source coordinates
and manual rotation semantics; registered reviews or explicit metadata describe
its actual local front. It can use an explicit facing target, but does not
canonicalize its source geometry. Prefer `place_asset` for new semantic scenes
and replacement slots. Unregistered raw imports remain unverified unless the
caller supplies a trustworthy declaration.

## Replacement and review

Model replacement requires a verified canonical source slot and verified target
asset. Directional symmetry, origin and semantic-front meanings must remain
compatible. The target's source axes are normalized before footprint fitting;
stable placement matrices/IDs and declared facing relations are retained.
Review an old slot explicitly before migrating it; names and bounding rectangles
cannot establish orientation. Existing active-contact and animated replacement
restrictions still apply.

Inspect actual top and oblique views with labeled local axes/front arrows during
an asset audit. Inspect scene-facing intent, support and useful circulation after
placement. A valid orientation matrix does not establish collision clearance,
camera visibility, seating fit or reference similarity.

The [audit tool](../tools/audit_asset_orientation.py) loads immutable registered
collections at zero yaw and isolated copies of the two source faucets. Its
configuration (historical or external input; omitted from this bundle) names exact source parts and
front/back or mounting/outlet landmarks. Run Blender, tests, hashing and renders
locally; the [runtime rules](../MACHINE.md) apply.

## Audited baseline and executable example

The September 10 eight-item review (historical or external input; omitted from this bundle)
confirms front -Y for the sofa, lounge chair, counter stool, extracted dining
chair and cabinet. The ceramic vase has no unique horizontal front. The source
g0025 faucet extends +X, while g0055 extends -Y. These actual frames are distinct
from the intended direction after scene placement.

The g0055 saved source additionally has its spout facing away from the sink
center: horizontal front dot toward the inset is about -0.970. Its new
registered copy uses a mounting root. The original source placement is retained;
g0025 remains a scene candidate because its lever is disconnected.

The [demonstration script](../tools/asset_orientation_demo.py) builds four seats
around one table, a sofa, two independently operable cabinets and a mounted
faucet facing a sink. It replaces one chair while retaining the semantic target,
saves and reopens the scene, and checks all eight relations. The
delivery handoff (historical or external input; omitted from this bundle) links the
editable Blender output, render inspection and test evidence. This synthetic
example validates the placement interface; historical scene yaws still require
their own explicit intent and review.

## Minimal placement and pre-render exception list

Use one directional placement entry for generated/custom roots and registered
assets. The caller supplies source-observed intent; the asset supplies its actual
local front. Work in final world coordinates, after room parenting/transforms:

```python
from aha3d.blender.roomkit import cabinet, place_root, place_asset

root, controls = cabinet('Sink cabinet', location=(3.7, 2.2, .08))
place_root(root, facing_target=(2.7, 2.2, .08))  # reviewed room-side point
# The cabinet helper also accepts facing_target or facing_direction directly.
# A custom chair must first have an inspected/authored local orientation tag.
place_root(chair, facing_direction=(.92, .39, 0))  # observed world heading
faucet = place_asset('faucet-simple-v1/faucet-simple-gooseneck',
                    location=(3.9, 2.2, .94), facing_target=(3.6, 2.2, .8))
```

`place_root` preserves size, children and native controls; `location` optionally
sets the world mounting/root position. Supply exactly one `facing_target` or
`facing_direction`. Directions are nonzero horizontal world vectors, normalized
and retained in `facing_target_json`; they preserve observed skew and survive
translation without inventing a table-center relation. Target points remain fixed
world points; object targets resolve stable instance IDs. Recheck intent if the
room basis changes. Unknown source orientation must be inspected before placement.
Direct legacy rotations remain supported but do not declare source intent.

`configure_render` now calls `scene_facing_report(scene)` once during render setup.
It prints only exceptions as `FACING_REVIEW` and retains the full report in
`scene['facing_preflight_json']`. Agents should resolve those exceptions using
existing representative previews before full rendering. This is an advisory list,
not an automatic correction, extra approval gate or per-object render loop.
Call the report again if transforms change after setup. Direct `bpy.ops.render`
without the shared render setup does not invoke it; no per-frame handler is added.

The report distinguishes `fail` (declared intent violated), `no_target` (known
front but no scene intent), `unverified` (missing/untrusted orientation), and
`invalid` (malformed relation or unsupported transform). Directional semantic
classes, including unregistered chairs/cabinets/faucets, are checked; imported
geometry under its placement root is not counted twice. Other explicit orientation
metadata is also checked, with symmetric assets marked not applicable. Untagged
geometry cannot be classified, and unknown room intent is never inferred from
current rotation. A clear report only establishes consistency of declarations at
the current frame, not source similarity, panel completeness or animation validity.
The existing material/clay previews remain the visual check; no new arrows or
per-object reports are required. Timing data is kept out of render signatures.

Local regression evidence (September 12, 2026): eight new Blender behavior tests,
13 existing Blender orientation tests and nine pure orientation/render-config
tests passed. On the breakfast-nook room with 904 objects, 17 eligible roots were
checked in about 1.8 ms median over five warm calls, excluding Blender startup and
file loading. The old scene first reported missing intent; supplying reviewed
room-side directions without rotating geometry exposed all three reversed
sink-wall cabinets at approximately 180 degrees. The corrected four placements
passed, while other undeclared roots remained explicit exceptions. Evidence is
under `runs/breakfast_nook_kitchen_g0039/facing-preflight-v1/report.json` locally;
this is a targeted regression, not automatic source-facing inference or a broad
performance benchmark.

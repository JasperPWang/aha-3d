# Blender browser demos

Convert a saved Blender scene to a self-contained interactive HTML page. Shared
viewer behavior includes hold-to-lift dragging, conservative swept bounding-box
movement limits, Escape cancellation, layout reset, cabinet controls, roof
cutaway, orbit/plan views, and playback of existing baked mesh animation.

Architectural semantic roots (walls, floors, ceilings, roofs, windows, doors,
structural groups and built-ins) remain fixed, including in older scene exports.
Owned wall/floor/ceiling surfaces also lock their group and its support ancestors.
Selection and joint controls remain available; furniture retains its existing
movement policy. `qa-structure.mjs` checks fixed structure with real pointer input.

## Setup and conversion

Requires Python 3, Blender with NumPy (validated with Blender 5.2.1), Node.js 20+
and Chromium through Playwright. Dependencies are pinned in the lockfile.
From the repository root:

```bash
npm ci --prefix tools/roomkit_browser
cd tools/roomkit_browser
npx playwright install chromium
cd ../..
python3 tools/roomkit_browser/demo.py --source /path/to/scene.blend \
  --out runs/my-scene/browser-demo --blender /path/to/blender
```

Blender can also be selected through `BLENDER_BIN` or PATH. Output directories
must be new. No scene-specific config is needed. The script automatically
recognizes existing semantic roots, complete legacy furniture empties, supported
Open controllers and shape-key/armature animation. It preserves source timing,
uses an authored perspective camera when available, and computes fallback/plan
views from world bounds. Source files are never saved or overwritten.

The conversion runs locally in the foreground on CPU. A finished command is not a
completed conversion; inspect its exit code, output and QA report.

## Results and access

The output contains `demo.html`, `scene.json`, `run.json`, `discovery.json`,
`validation.json`, `pipeline.log`, and orbit/plan/mobile screenshots. Success is
recorded as `validated` only after browser checks pass. QA checks all exported
actor-frame position hashes, joint movement, playback advance and mobile sizing.
Inspect the screenshots separately to assess visual framing and grouping.

Serve the result with `python3 -m http.server 8766 --bind 127.0.0.1 --directory
runs/my-scene/browser-demo`, then open the local server's demo.html page. For remote
hosts, forward the server port or use your application's remote browser support.
The HTML has no runtime CDN dependencies. Modern WebGL and DecompressionStream
support are required. Optionally pass `--serve /existing/server-root/demo.html`
to atomically mirror validated HTML into an existing server. It does not start a
server or make a remote port reachable automatically.

## Scope and metadata

Existing `instance_id`, `semantic_class`, `asset_id`, `support_id`, `joint_id`,
`joint_type` and `roomkit_open_property` metadata take precedence. Consult the
project's [semantic asset contract](../../docs/SCENE_VARIANTS.md) for new scenes.
Unknown loose geometry remains static and is listed in discovery. Name/hierarchy
inference is conservative, not proof that every object is correctly grouped.
Animated meshes keep their original placement and preserve parent animation.

Dragging lifts objects visually by 14 cm after a 160 ms hold, then returns them
to their support height on release. Swept world-axis bounding boxes constrain
horizontal movement, including large pointer jumps. Boxes can block concave gaps;
this is not rigid-body physics. Existing source overlaps can escape but must not
deepen along the tested axis. The visual lift, cabinet opening and animated
people do not participate in collision response. Furniture edits do not replan
human motion. Browser edits are temporary and do not save back to Blender.

The blue selection outline follows the authored frame of the largest furniture
component and encloses its actual vertices. Simulated tabletop props use their
live rigid-body frame, including tilt. Scene-graph coordinates and conservative
furniture movement limits remain world-axis bounds; the selection outline is
only a visual aid.

Exports retain evaluated geometry, generated RoomKit PBR recipes and their UVs.
Other source shaders still use simplified base colors; arbitrary Blender graphs
are not translated. Nested/instanced articulation and changing animated topology
are unsupported. Existing motion is replayed, never regenerated or claimed as
source-person ground truth. Vertex animation can make output HTML large.

`export_scene.py --auto` is the Blender-side entrypoint; `build.mjs` builds HTML;
`qa-generic.mjs` checks arbitrary exports. The other QA scripts exercise specific
source-deployment fixtures and require those external scenes/exports, which are
not distributed. The [skill](../../.agents/skills/blender-browser-demo/SKILL.md)
routes subsequent scene conversion requests to these same scripts.

Thin rug/carpet/floor-finish meshes within 8 cm of an object's resting
support height are treated as passable covers, including named rug trim and
fringe. Elevated or thick covers remain obstacles. This prevents decorative floor
geometry from blocking horizontal layout edits without disabling furniture or
wall collision. `qa-rug.mjs` exercises this case using the real-room fixture.

## Tabletop physics and seeded swaps

Add `--tabletop` to the same conversion command to export a tabletop playground.
It requires a complete semantic table root with a measurable horizontal top.
The exporter checks that top-face triangles cover a convex footprint within 3%;
rotated and round tables retain their actual footprint for placement and slab
collision. The support is fixed while its objects are simulated.
Missing or unsupported support geometry fails clearly; this option does not
silently turn arbitrary furniture into a table.

The viewer starts with the source tabletop objects. **Swap all tabletop objects**
chooses a new seed, asset combination and collision-free initial arrangement.
**Rebuild** repeats the input seed; **Reset this seed** restores its starting poses;
**Original table** restores the exported source arrangement. The seed is stored in
the URL fragment for sharing. Hold an object to lift it with a constrained dynamic
body, move the pointer, and release to drop it. Escape cancels the grab. Physics
can be paused independently of human animation, and **Nudge objects** applies a
small impulse to demonstrate object interactions.

The bundled cannon-es 0.20.0 solver uses Z-down gravity, fixed 1/120-second steps,
friction, angular motion and sleeping bodies. Browser builds use at most 10 solver
iterations and four catch-up steps per display frame; excess elapsed time is
dropped rather than accumulating a physics backlog, so simulation slows below
30 display FPS. Active-body AABB filtering skips static/static and sleeping/sleeping
pairs. Resting props use Cannon's sleep-speed threshold of 0.12
for 0.8 seconds; once all props sleep, display ticks skip physics until
a grab, impulse or moved support wakes them. Basket collision tiers use 12-sided bases and 12 wall segments, independent
of the unchanged display meshes. Every tabletop object has a reduced convex
proxy sampled from extremal vertices of its exported visual geometry (at most 38
vertices before hull construction). Mass is concentrated near the base of each
vessel or arrangement. Environment collision uses per-mesh convex proxies sampled from 26 local extreme
directions and transformed with the mesh, preserving rotation, scale and shear.
Coplanar faces are merged for stable resting contacts; proxies update when furniture
translates. Zero-volume planes are excluded. Roof, animated people, cabinet
joints and rug ornament meshes are excluded from this solver. These are interactive
approximations: flowers and vase move as one rigid arrangement; vessels have no
hollow collision interior; there is no breakage, cloth, liquid or person contact.
Dimensions and masses are authored approximations, not calibrated measurements.

Six registered assets supply rounded/porcelain vases, fern, hydrangea,
silver platter and stemmed vessel variants, alongside the source arrangement.
Their asset IDs, library hashes, orientation metadata and normalized geometry are stored in `tabletop.templates`.
Source `.blend` files and asset libraries are opened without saving. Materials
retain source base colors (or the midpoint of a directly linked color ramp);
arbitrary source shader graphs remain outside this lightweight viewer. The
Material lab generates new supported PBR textures; see below.

The output also retains the viewer source snapshot and hashes, Git revision and
dirty state in `run.json`. Bundled dependency license notices remain in the HTML.

`seeded-layout.js` generates versioned tabletop placements from scope, support ID
and seed. One centerpiece and smaller accents use nonoverlapping circumscribed
footprints. The seed reproduces initial assets/poses, not arbitrary later user
interactions or bit-identical physics across platforms. Chair swaps use an
independent optional scope described below; other furniture is not replaceable.

`qa-tabletop.mjs` checks 200 seeds for reproducibility, support bounds and initial
overlap, then exercises the actual browser controls, repeated body replacement,
settling, impulses, pause, pointer lift/drop and a fall from the table to the room
floor. Results are recorded separately in `tabletop-validation.json`, alongside
source-animation and cabinet regression checks in `validation.json`. Screenshots
still require visual inspection; automated success alone does not validate views.

## Live scene graph and layout

The right sidebar opens on **Scene graph**. It groups semantic objects by assigned
support (for example table → vase/candlesticks) and includes cabinet joint nodes
and an aggregate of unowned static room geometry. This is separate from render
parenting and transient physics contact. No semantic grouping is invented for
unowned meshes.

Select an object node or an object in the canvas to synchronize highlighting and
the JSON inspector. Center, size and min/max coordinates come from current world
geometry bounds; legacy Blender roots at the origin do not falsely report zero
layout coordinates. The panel refreshes at 5 Hz while visible. A falling object
keeps its assigned support edge, while its position, height above the support and
footprint state change. These bounds descriptions do not certify physical contact.

Swap updates nodes, seed and initial placement records. **Export JSON** downloads
the current graph, edges, layout, joint openings and physical state, without mesh
payloads or writing into Blender. **Controls** retains the seed, physics, human
playback and cabinet controls. `qa-scene-graph.mjs` verifies hierarchy, actual world
coordinates, linked selection, live movement, fallen-object state, swaps, JSON
export, joint updates and mobile sizing.

## Constrained chair replacement

Add `--chairs` (optionally alongside `--tabletop`) to enable **Swap all chairs**. Source chairs
must be complete semantic roots with trusted canonical -Y-front/Z-up floor-center
frames, positive uniform scale and identifiable seat parts. Source headings are
retained; explicit facing intent is retained when supplied. The mode
retains the seat count, identities and headings, and uses native asset dimensions.
Chairs remain interactive before and after replacement: hold to lift, drag to
move, release to place, Escape to cancel. Tabletop colliders refresh after a
chair settles. Swapping preserves current placement anchors, including manual
drags; a non-fitting model is rejected instead of shifting the chair.

Each slot and candidate carries local width/depth/height, seat height/width/depth,
arm height when present, an orientation record and per-part collision bounds.
The candidate pool is discovered from registered chair-category assets with
trusted orientation metadata. No scene names or fixed asset lists select it.
Metadata is measured from
evaluated geometry; named seat parts must be inspected in the asset review.
The actual library hash is retained, including when current assets are upgraded.

The versioned `chairs-grouped-v3` seed stream is independent of tabletop generation.
Slots sharing the original catalog `family_id` form a replacement group across
the scene. Every seat in that group must receive the same alternative asset.
Candidates must match the explicitly curated `seating_type` (for example dining,
lounge or accent) in `assets/catalog_sources.json`; unknown types are rejected,
not inferred from size or object names. The original asset and its model-family
aliases are excluded. Add types when registering new assets; these are reusable
asset semantics, not room-specific configuration. A group with no common
alternative keeps the whole current layout. The inspector and exported report
include type, source model, group membership and compatible alternatives.
Style selection can restrict all groups to one asset when its type is eligible
for every source group. Individual candidates are
filtered by size/seat height, tested at the current XY anchors and checked against
current room geometry and tabletop objects. The full set is searched before any
live meshes are replaced. Failed requests keep the previous layout and URL seed;
the visible fit report records why candidates were rejected. Original chairs can
be restored separately from the tabletop. Renderer geometry and tabletop static
colliders are refreshed together after a successful chair replacement.

The shared `source-relative-v2` policy derives limits from each source chair:
width <= 1.20x source width, depth <= 1.35x, overall height <= 1.50x; seat height
within 18% of the source seat; no automatic translation;
no scaling; fixed heading. Rear access reserves half the source depth
behind the chair against fixtures and other chairs. These are a conservative
variation policy, not ergonomic or building standards. All limits and their
derivation are shown in the graph JSON. Walkability checks preserve
the largest original reachable component on a .12 grid with a .15 navigation
radius, except cells occupied by the new chairs. This is a discretized relative
connectivity check, not an accessibility-code certificate or full human seating
simulation. Floor top triangles, bounds and support elevation are read from floor meshes and
source chair anchors. Multiple support levels require separate navigation layers
and currently fail export. No zero-height ground assumption or per-scene offsets
are used. Search is bounded to 3,000 partial states and 20 complete arrangements;
failure reports lack of an accepted plan within this budget, not impossibility.

Collision proxies keep separate chair legs, seat and back to preserve table-under
clearance. They are conservative local component boxes, tested with yaw-aware SAT
against upright oriented room boxes, with world AABB fallback for tilted or sheared
parts. Floor corners and navigation probes must lie on the exported floor surface;
empty corners of a rotated floor bounds box are excluded. Human motion uses triangle-conservative .12-high slice
boxes for every exported frame; it does not certify intermediate-time contact.
Cabinet movement uses 21 sampled opening poses. Clearances may reject geometrically
valid placements because the proxies overestimate occupied volume.

Scene graph groups chairs with the nearest table whose convex footprint intersects
their forward ray, otherwise in a seating group. This includes seats near the ends
of long tables. These are source-facing assignments; moving a table does not
replan its chair slots. It records floor support
and table facing as distinct edges, and exposes specifications, limits and the accepted
chair seed. Exported layout contains the latest acceptance/rejection report.
`qa-chairs.mjs` exercises repeatable seeds, mixed/single-style replacements,
oversized/live-obstacle rejection without partial mutation, floor anchors, typed graph relations,
scope-independent seeds, original restore and desktop/mobile views. Inspect
`chair-validation.json` and `chairs-*.png` after browser QA.

`qa-chairs.mjs HTML OUT [PLACEMENT_FIXTURE_JSON]` can test a previously arranged
layout without modifying the exported source arrangement. The fixture contains
explicit slot placements and is recorded in the report. `qa-chair-interaction.mjs`
uses the same optional fixture and real pointer input to check post-swap lifting,
dragging, release, Escape and preservation of a manually moved anchor on swap.

## Progressive loading and offline export

Every build produces `demo-fast.html` for HTTP Gallery browsing and `demo.html`
for single-file offline sharing. The fast entry depends on its adjacent
`demo-fast-assets/` directory; `demo-fast.html.json` lists every dependency and
its initial-load subset. Do not move the entry alone. `--serve` continues to
mirror the offline file only.

The fast viewer loads gzip scene JSON (including original actor first-frame
geometry) and a content-addressed viewer script, then becomes interactive.
Animation uses lossless little-endian float32 gzip segments of about two seconds.
Play/seek fetches the needed segment; playback prefetches the following segment.
A bounded memory cache retains roughly three segments per actor. Failed requests
show Retry, and buffering pauses animation time. Frame count, FPS, world positions,
collision bounds, and chair placement constraints are unchanged.

The Gallery server caches content-addressed resources for one year. Compressed
`.gz` resources are decoded explicitly by the viewer; serve them as ordinary
binary files, without an additional `Content-Encoding: gzip` header. The fast
entry needs HTTP and WebGL; use the offline HTML when opening from `file://`.
`qa-streaming.mjs FAST_HTML OUTPUT_DIR` checks zero animation requests before
interaction, failed-request recovery, browser poses at representative boundaries,
and every decompressed frame against the original exporter SHA-256 evidence.
Its ready time is local QA timing, not an estimate of remote user bandwidth.

Fast exports also defer non-source tabletop replacement meshes until a swap
actually selects them. Original tabletop physics remains immediately available.
All requested models load before applying a replacement; a failure leaves the
current layout intact. Escape, reset, restore-original, or beginning a tabletop
drag cancels a pending replacement. Retry by clicking Swap again. Geometry
metadata and collision hulls remain in the initial scene for deterministic plans.

Legacy cabinet metadata using `joint_type=slide` is normalized to `slider` in
memory. Export still checks five native Blender poses against browser joint
interpolation, and never saves this metadata change back to the source scene.

Large baked clips use adjacent binary actor sidecars during export once their
combined Base64 payload exceeds 64 MiB. The fast demo compresses them into the
same lossless two-second segments. The standalone offline HTML embeds each
actor separately and decodes directly into binary buffers, avoiding a combined
animation JSON string. Source frames, vertex precision and playback rate are
unchanged; offline playback still loads the full animation into memory.

Auto-discovery retains the authored camera when its view cone includes
the room center; otherwise it uses the generated room overview. Browser QA
allows 120 seconds for screenshots on shared CPU software rendering.

For animated-human scenes, a camera aimed at every visible animated mesh center
is also retained when tall architecture puts the overall room center outside its
view cone. Hidden actors do not vote. This preserves a useful authored close view
without changing static-room overview framing; check actual body framing visually.

## Completing legacy interaction metadata

`prepare_interactions.py` authors an explicit JSON recipe into a distinct saved
Blender file. Recipes pin the original source SHA-256, enumerate complete object
members, and declare seating frames/types with evidence. Existing geometry is
compared at the source first, middle and final frames before saving. This step
is separate from automatic discovery and must be visually reviewed before
selection. It never overwrites the source file.

```bash
blender --background --python-exit-code 1 --python tools/roomkit_browser/prepare_interactions.py -- \
  --source /path/to/source.blend --recipe /path/to/reviewed-recipe.json --out /path/to/new/scene.blend
```

Batch planning accepts both `--tabletop` and `--chairs`. Each flag requests its
strict export and specialized QA; it does not convert unrelated geometry into
a support or change an object's seating type to obtain an alternative. A scene
with only counter stools can have tabletop physics while lacking chair-library
alternatives. Full room furniture dynamics and collision-aware human motion
remain outside these controls.


A minimal metadata recipe has this shape (object names are exact Blender names):

```json
{
  "source_sha256": "SHA256_OF_SOURCE_BLEND",
  "groups": [{"name": "Table interaction root", "id": "table-1",
    "class": "furniture/tables", "objects": ["Top", "Base"]}],
  "chairs": []
}
```

Use `root` instead of `name` to update an existing semantic root. A chair entry
names its `root`, supplies `yaw` in radians, `seating_type`, `source_model_id`
and an `evidence` description of the reviewed seat/back direction. `floor_z`
defaults to zero. Child world geometry is retained when authoring the frame.
Collection instances need a separate evaluated-instance comparison: the native
three-frame metadata check covers scene mesh objects only.

Upright, trusted chair roots may have positive nonuniform source scale. The
exporter measures their actual evaluated geometry in a scale-free canonical
frame, records the source scale vector and preserves the original meshes.
Replacement assets remain at native scale; reflection, shear and tilted frames
are rejected. Tabletop QA checks the actual convex body's bottom against its
assigned support, including source/library copies sharing an asset ID.


Support collision vertices use a local origin inside the convex slab, with the
body positioned in source world coordinates. This also supports rooms whose
floor and tabletops have negative Z coordinates. Regression tests drop objects
onto positive, negative and horizontally offset supports.

Original source props may tip under convex-body simulation; QA records their
settled orientation and checks support and stability. It does not force every
rounded source prop upright. Initially intersecting source displays can be
explicitly authored as one rigid arrangement in a reviewed metadata recipe;
its constituent objects then move together. Physics uses bounded tabletop slabs
and per-mesh convex furniture proxies, not full-room mesh collision certification.

Replacement chair collision bodies use the same component boxes and world yaw
as placement validation. This preserves seat openings between rotated armrests;
world-axis enclosing boxes can otherwise push a dropped prop out of the seat.
Dragging and later swaps rebuild these bodies at the current retained anchors.

## Browser lighting and lamps

Scenes with authored daylight use softer browser fill (key 0.8, probe-scene
hemisphere 0.08), exposure 0.85 and lamp multiplier 0.65. Source material colors
and baked data are preserved. Lighting metadata can override `exposure`,
`key_intensity` and `lamp_scale`; these are artistic defaults, not photometric
calibration. Scenes without authored daylight retain the generic lighting defaults.

The WebGL viewer uses a filtered indoor environment map, a shadow-casting daylight
key and exported Blender lights. Native POINT, SPOT and SUN transforms/colors are
retained; AREA sources use spot approximations. Energy-to-browser intensity is an
artistic mapping, not calibrated photometry. The viewer prioritizes lamp fixtures
and renders at most 12 exported lights; the lighting inspector reports omissions.

Recognizable lamp/chandelier/sconce/pendant bulb, shade, diffuser or flame meshes
without a nearby native lamp light receive an inferred warm point light. Export
records distinguish native lights from inferred emitters. Unrecognized geometry
is not silently illuminated. The **Lamps on/off** toolbar button switches lamp
sources and associated emissive shades together. Native daylight/fill remains on.
Attached lights follow the existing furniture/support/joint transforms; dragging
still uses the normal movement policy. Source `.blend` files are never saved.
Simplified solid emitter meshes do not cast shadows because they cannot represent
cloth/glass transmission; unrelated objects retain their shadows.

**Controls → Lighting** offers Fast (pixel ratio capped at 1, no shadow maps),
Balanced (1.5, daylight shadow plus one lamp shadow), and High (2, daylight plus
two lamp shadows). Other lamps illuminate without shadow maps; light leakage is
possible. This is a bounded rendering budget, not a measured FPS guarantee.

Add `--bake-indirect` to `demo.py` or `export_scene.py` for a Cycles bake:

```bash
python3 tools/roomkit_browser/demo.py --source /path/to/scene.blend \
  --out runs/my-scene/browser-lighting --bake-indirect
```

The optional bake creates a 1024²–4096² linear half-float indirect diffuse atlas for
fixed room surfaces and one room-wide diffuse spherical-harmonic probe for moving
objects. UVs use bounded coplanar chart packing on a temporary welded room mesh; exported source
geometry, animation and placement stay unchanged. The atlas and probe are embedded
in both fast and offline exports. `lighting-bake.json` records samples, geometry
scope, atlas statistics and probe location. **Indirect lighting** toggles the atlas
and probe for comparison. Diffuse environment lighting is suppressed where the
probe is used to avoid counting the same illumination twice; specular environment
reflections remain available.

Baking uses the browser's fixed daylight approximation. Movable furniture,
animated people, joints and switchable lamp emission are excluded, so moving them
or switching lamps off leaves no baked lamp glow or furniture shadow. Lamp bounce,
spatially interpolated probe grids, view-dependent reflections and real-time GI
are not implemented. The single probe is approximate across separate rooms; a
new bake is required after changing the fixed room or daylight configuration.

`qa-lighting.mjs` checks actual canvas pixel changes for lamps and indirect light,
owner-following transforms, shadow quality controls, shader/console errors and
mobile overflow. Inspect `lighting-on.png`, `lighting-off.png`,
`lighting-no-indirect.png` and `lighting-mobile.png` separately. Browser QA uses
software rendering and does not establish device performance or photometric fidelity.

To bake on the GPU, set `ROOMKIT_BAKE_DEVICE=OPTIX` (or `CUDA`) before running the
conversion. The bake explicitly enables matching Cycles devices and fails if none
match. Default CPU execution needs no GPU. Bake phase/device logs and the report distinguish
export/unwrap time from rendering time.


## Procedural material lab

Every newly built demo includes **Controls → Material lab**. Select an object and
a material slot to apply any of 19 seeded finishes: wood, stone, metal, glass,
glazed porcelain and walls. Version 3 adds four glass presets, four ceramics
(including blue-and-white porcelain), plaster, matte paint and limewash.
Glass uses transmission with IOR and thickness controls; porcelain has a separate
glaze layer. Saved version 1 and 2 recipes remain reproducible. New materials use
512 px maps. Adjust color, physical repeat size, grain angle, roughness and
relief; restore the original appearance at any time. Changes stay in the browser.
Downloaded recipes generate standard PBR maps and an editable, packed Blender
material through the shared importer. Generated recipes survive subsequent demo
exports. See [Procedural materials](../../docs/PROCEDURAL_MATERIALS.md) for commands,
research/library references, mapping limits and checks.

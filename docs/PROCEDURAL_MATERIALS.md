# Procedural materials

RoomKit generates seeded PBR tiles for wood, stone, metal, glass, porcelain and
wall finishes and uses the same
recipe in the browser demo and Blender. This is a small deterministic generator,
not a reproduction of a learned material-synthesis paper. It uses the project's
existing Three.js renderer and Node built-ins; no extra service, model, texture
library or dependency installation is required.

## Browser

Export a saved scene with the normal `tools/roomkit_browser/demo.py` command.
In **Controls**, select an object, scroll to **Material lab**, choose the material
slot, choose a preset and click **Apply material**. A material slot can span several
parts of the selected object. The default targets one named source material;
**All material slots** is an explicit option. Other objects sharing that source
material keep their original appearance. **Restore original** restores material
and geometry references, including lightmap UVs. Refresh also restores the source.

The 23 presets include natural oak, walnut, veined marble, granite, concrete,
brushed steel, brass and copper; clear, frosted, green-tinted and ribbed glass;
ivory porcelain, celadon, crackle glaze and blue-and-white porcelain; plaster,
matte wall paint and limewash; honed travertine, warm terrazzo, woven linen and
saddle leather. The additional finishes use layered stone pores, mineral chips,
interlaced threads and fine leather grain, respectively. Controls include a deterministic seed,
base color, repeat size in metres, grain angle, roughness and relief in millimetres.
The square preview shows base color only; the scene shows the PBR response.
Glass also exposes transmission, index of refraction and thickness in millimetres.
Ceramics expose glaze amount and glaze roughness. These use Three.js
`MeshPhysicalMaterial`; opaque finishes retain `MeshStandardMaterial`.
The original eight materials retain the upgraded version 2 patterns: fine pores, rays and knots in
wood; multiscale mineral cells in granite; layered marble veins and clouds;
cement aggregate and pores; and interrupted metal brushing with finish variation.
Actors and light emitters are excluded from interactive changes. Structure can
receive materials while remaining locked in place. Chair and tabletop swaps
create new objects with their own materials; material overrides do not transfer
automatically to replacements.

**Download recipe** saves the current generator settings. It does not save layout,
object assignments or changes to a Blender file. Recipes are versioned and fail
explicitly on unknown fields, presets or invalid values. New and unversioned
recipes default to version 3. Explicit version 1 and 2 recipes retain their exact
patterns and defaults. Version 3 adds the new presets and physical surface settings;
the original eight generate the same maps as version 2. Browser
material applications share one set of maps across the changed surfaces.

## Compare the collection

Build an offline swatch gallery using the same generator and Three.js dependency:

```bash
node tools/roomkit_browser/material-gallery.mjs /absolute/new-collection.html
node tools/roomkit_browser/qa-material-gallery.mjs /absolute/new-collection.html /absolute/qa
```

The gallery filters glass, ceramics, walls and the new stone/fabric/leather families and compares all three recipe versions with fixed studio lighting,
shows base color separately, switches seeds and resolution, and downloads each
recipe. Slabs and spheres show flat-surface detail and curved specular response.
Review every changed material and another seed before delivering pattern changes.
The gallery is a review surface; apply its recipes through the demo Material lab
or the Blender importer to inspect them on the actual objects.

## Reuse in Blender

Run builds, tests and Blender locally with your configured Node and Blender. Generate a bundle from a downloaded recipe:

```bash
node tools/roomkit_browser/material-cli.mjs material-recipe.json /absolute/new-material 512
```

The output contains `material.json` and four PNG maps:

| Map | Meaning | Color space |
| --- | --- | --- |
| `baseColor.png` | Surface reflectance, without baked lighting | sRGB |
| `orm.png` | R: 1 (unoccluded), G: roughness, B: metalness | Linear |
| `normal.png` | Tangent-space normal, OpenGL +Y | Linear |
| `height.png` | Normalized procedural relief | Linear |

The small control preview uses 256 px tiles; version 2 and 3 scene materials use 512 px
(version 1 retains 256 px). CLI resolutions are powers of two from 32 to 2048,
with 512 px as the default. Use 1024 or 2048 for close views and offline rendering.
Normal slopes use relief and repeat size in physical units. Height is exported
for reuse but is not connected as geometric displacement. The ORM ambient channel
is neutral, not a geometry-derived occlusion estimate.
Transmission, IOR, thickness and glaze are scalar settings stored in the recipe
inside `material.json`. Keep that file with the PNG maps; the maps alone cannot
reproduce glass or glaze.

Apply the bundle to explicit named objects or a complete root and its descendants:

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python src/aha3d/blender/procedural_materials.py -- \
  --source /absolute/source.blend \
  --bundle /absolute/new-material/material.json \
  --object 'Exact furniture root' --material 'Original wood material name' \
  --out /absolute/new-scene.blend
```

Repeat `--object` for multiple targets. Omit `--material` only to replace every
material slot of the selected meshes. The importer creates an editable Principled
node graph, packs all used images, copies selected mesh data to protect linked
instances and adds a separate `RoomKitMaterial` UV layer. It never overwrites an
existing output or the source. The adjacent `.materials.json` records exact input
hash, selected objects and recipe. Python callers can use `load_material` and
`apply_material` directly inside Blender.

The importer connects transmission, IOR and coat settings to Principled BSDF.
Blender uses actual mesh thickness for transmission; the recipe thickness is
stored as `roomkit_transmission_thickness` for the browser approximation.

The browser exporter retains `roomkit_procedural_material` recipes and the generated
UV layer, so imported materials survive the next browser export. It also retains
scalar transmission, IOR and coat settings from native Principled materials,
using 6 mm browser thickness unless the custom property above is set. Arbitrary
linked Blender node graphs still use scalar approximations. This is an
explicit supported recipe path, not a general Blender shader translator or baker.

## Mapping and limits

Objects without material UVs receive per-face planar projection in object axes,
scaled to metres at application time. Existing RoomKit material UVs are preserved.
Projection follows rigid object movement and does not edit placement. It can show
projection seams on curved or beveled surfaces; this version does not provide
triplanar blending, automatic grain alignment across joinery, or animated skin
texturing. Author suitable UVs for hero assets. Applying later nonuniform scale
changes the physical repeat size.

Patterns use periodic value noise, domain warping, wrapped knot fields, mineral
cells, grain/vein masks and directional microstructure. Tile boundaries are
continuous in both axes. The metal presets
provide directional color/roughness/normal variation with metalness 1; they do
not model anisotropic conductor BRDFs, measured optical constants, rust or wear.
These are appearance presets, not measured materials. Browser and Blender use the
same maps and recipe but different lighting, filtering and tone mapping; renders
are not promised to be pixel-identical. Baked scene indirect lighting is retained
and is not recomputed when a material changes.

Glass uses transmission with opacity 1. Browser refraction uses the rendered
opaque scene and an approximate thickness; overlapping glass layers and caustics
are not simulated. Fully transmissive meshes skip ordinary opaque shadow maps,
including after lighting-quality changes. Meshes mixing glass and opaque slots
retain an approximate opaque shadow. Ribbing is normal-map relief, not new geometry.

## References and reusable libraries

- [Infinigen Indoors (CVPR 2024)](https://arxiv.org/abs/2406.11824) and
  [Infinigen code](https://github.com/princeton-vl/infinigen): the closest fit for
  richer Blender procedural materials and scene variation. Its stable Indoors
  branch is a useful reference; the repository also has a newer V2 interface.
  Select and test a compatible version before introducing it as a dependency.
- [Material Maker](https://github.com/RodZill4/material-maker): an MIT-licensed,
  Godot-based node graph authoring tool. It is a candidate for authoring richer
  PBR texture sets offline. No Material Maker runtime or graphs are bundled here.
- [tsl-textures](https://github.com/boytchev/tsl-textures): an MIT-licensed collection
  of real-time 3D procedural textures for Three.js Shading Language. Its documented
  API uses WebGPURenderer and node materials; our existing WebGLRenderer needs a
  separate integration, so this implementation keeps the current renderer.
- [TexPro: Text-guided PBR Texturing with Procedural Material Modeling](https://arxiv.org/abs/2410.15891):
  a research direction if natural-language material selection and parameter fitting
  are later needed. This feature does not implement its pipeline.

No third-party generator code or texture assets were copied. Three.js remains the
existing pinned rendering dependency and retains its bundled license.

## Validation

```bash
node --test tools/roomkit_browser/material-generator.test.mjs tools/roomkit_browser/material-surface.test.mjs
blender --background --factory-startup --python-exit-code 1 \
  --python tests/test_procedural_materials_blender.py -- \
  --bundle /absolute/new-material/material.json --out /absolute/new-check
node tools/roomkit_browser/qa-materials.mjs /absolute/demo.html /absolute/qa
node tools/roomkit_browser/qa-physical-materials.mjs /absolute/demo.html /absolute/physical-qa
```

Unit checks cover byte-for-byte compatibility with shipped version 1 and 2 maps,
deterministic maps, changed seeds, tile continuity, physical
normal slopes, rejected inputs and UV/lightmap preservation. Blender checks cover
linked-instance and slot isolation, packed map color spaces, saved recipes and
physical settings. Browser checks exercise all 19 presets, native exported glass,
transmission and glaze controls, shadow behavior, shared texture allocation,
other-object isolation, unchanged
placement, restoration, recipe download, actor exclusion when present, mobile layout
and JavaScript/WebGL errors. Inspect the actual material screenshots separately;
passing these checks does not certify measured appearance or source-video fidelity.

# Current asset quality upgrades

The owner requested a complete registered-library audit and replacement of
inferior current assets on September 13, 2026. The current inventory has 49 model
collections and 59 independently registered materials. A retained item means
the audit did not identify a justified change; it does not mean it was rebuilt.
See [the current item-level review](../../assets/quality_review.json).

## Current payload policy

Asset IDs and registered paths remain stable. Build a distinct temporary
candidate, inspect its geometry and rendered appearance, then replace the
canonical payload and update the manifest, checksum and orientation evidence.
Rebuild both indexes. Do not register a second obsolete library solely for
reproducibility. Temporary before/after evidence is separate from the asset
inventory. Existing library names containing `v1` or `v2` remain compatibility
identifiers; a manifest and SHA-256 describe their exact current payload.

Use task claims for source tools, candidates, canonical assets and generated
catalogs. All Blender work, hashing, copies, builds and tests run locally.
The source is opened in background Blender; changes are staged separately until
accepted. Coordinate with active readers before replacing current payloads.

## Tools

- `tabletop.py`: actual vessel walls/bottoms, smoothly sampled profiles and pole
  welding for the nine registered vessels and plant-container collections.
- `models.py`: audit of the remaining models and materials, followed by targeted
  repairs. Retains native cabinet controls and useful source-specific geometry.
- `integrate.py`: merge explicitly reviewed collections from separate candidate
  libraries, preserve all other registered collections/materials, verify exact
  saved/reopened geometry, and publish the reviewed current payloads.
- `verify.py`: import every registered model twice, verify independent object
  trees, test static semantic replacement or native cabinet-control independence,
  and reopen saved fixtures. Fixtures are removed after successful checks.
- `refresh_scene.py`: refresh existing static semantic slots by explicit asset
  identity. Reports protected/unknown placements without guessing from names.
- `rigid_body_smoke.py`: bounded exterior-contact drop and platter-stack checks
  using Blender Bullet convex hulls; reports simulation settings and limits.

For integration, author a schema-version-1 JSON plan with an `entries` array.
Each entry names `asset_id`, `library_id`, `datablock`, `candidate_library`,
`status: "upgraded"`, `changes`, `validation`, attributed `visual_review`, and
optional `manifest_updates`. Duplicate or unknown collection selections fail.

```bash
blender -b --python-exit-code 1 --python tools/asset_quality_upgrade/integrate.py -- \
  stage --plan MERGE_PLAN.json --out NEW_STAGING_DIRECTORY

# After independently reviewing the staged libraries and report:
python tools/asset_quality_upgrade/integrate.py publish \
  --report NEW_STAGING_DIRECTORY/report.json
python tools/asset_index.py build
python tools/asset_index.py check
python tools/build_catalog.py build
python tools/build_catalog.py check
```

The publishing preflight rejects source, candidate or registry changes since
staging. Files are replaced individually; publication is not a cross-file
transaction. Keep the claim and coordinate readers until all checks complete.

## Refresh an existing scene

```bash
blender -b --python-exit-code 1 --python tools/asset_quality_upgrade/refresh_scene.py -- \
  --source SOURCE.blend --audit --report AUDIT.json

blender -b --python-exit-code 1 --python tools/asset_quality_upgrade/refresh_scene.py -- \
  --source SOURCE.blend --out REFRESHED.blend --report REFRESH.json
```

The default selection is current upgraded model IDs. Repeat `--asset-id` to
select explicit registered models instead. Static replacements retain slot
identity, transforms and support relationships through the shared variant tool.
Animated, constrained and active-contact replacements remain protected. Loose
legacy parts or collection-only placements need an explicit complete-object
semantic migration. This command does not regenerate rendered videos or browser
exports, nor does it select a new Gallery delivery automatically.

## Geometry and everyday rigid-body simulation

Classify modeling difficulty by structural constraints, not polygon count.
Revolved cups, bowls, plates and vases permit explicit control of cavities,
thickness and contact surfaces. Sculptures and organic ornaments may benefit
from an image-conditioned generative mesh. Neither route guarantees physics.

For everyday picking, dropping, collisions and stacking, a detailed visual mesh
can use a simpler collision shape. A single convex hull preserves the exterior
envelope but fills cavities and handle holes. Use reviewed compound convex parts
when those empty spaces matter. A plant normally needs a pot-centered collision
approximation rather than treating every leaf as a solid rigid obstruction.

The included smoke test covers five vessels dropped from 0.25 m with a 5-degree
tilt and one two-platter stack, at 24 FPS for 240 frames, using assumed 0.25 kg
mass, friction 0.6, restitution 0.02 and a 0.5 mm collision margin. Passing means
those cases settled without excessive floor penetration or drift. It is not a
test of cavity insertion, liquid containment, calibrated mass/inertia, fracture,
soft bodies or arbitrary contacts for every asset.

[TRELLIS.2](https://github.com/microsoft/TRELLIS.2) is an image-to-3D asset generator
that supports open and non-manifold surfaces. Treat its outputs as candidates:
inspect geometry and author collision shapes as required by the interaction.
No TRELLIS output was used or benchmarked in this deterministic upgrade pass.

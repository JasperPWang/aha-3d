# Seating and plant quality

Scope: the September 10, 2026 user-requested asset-quality pass. Two model agents
work on seating and plants; the integrating agent owns registration and checks
real library placement. New immutable assets preserve existing libraries and
saved room outputs. The integration handoff (historical or external input; omitted from this bundle)
records exact jobs, source snapshots and acceptance evidence.

## Observed source quality

A visible gap is not sufficient evidence of a floating chair back. The inspected
open-frame dining chair has a continuous geometric support path through its arms
and legs. The original walnut lounge back contacts the arms; its cushion welts
are embedded inside the upholstery. An initial surface-only check incorrectly
classified those embedded parts as detached; the corrected audit includes volume
containment. The lounge lumbar pillow has a measured 6.59 mm gap above the seat,
although it remains connected through the back. Geometric contact is not a
load-bearing or manufacturing certification.

The inspected plant sources differ:

| Source | Saved geometry observed | Reuse implication |
| --- | --- | --- |
| g0025 orchid arrangement | Seven thick ellipsoid leaves, stems and petals | Supplies an adaptable pot profile; not a complete registered plant |
| g0064 shelf planter | Nine pale ellipsoid leaves on the selected plant, using upholstery material | Placeholder leaf shape/material benefits from a complete leafy replacement |
| g0070 vase flowers | Seventeen stems and 51 flower masses, no authored leaf mesh | A flower arrangement; a broadleaf potted plant is a different object |

See the source plant audit (historical or external input; omitted from this bundle)
and seating handoff (historical or external input; omitted from this bundle). These findings
apply to the inspected saved objects, not every scene or every chair in storage.

## Supported chair refinements

Two new items share `assets/seating/refined_v1`:

| Item | Change | Dimensions in metres |
| --- | --- | --- |
| `seating-refined-v1/chair-walnut-lounge-supported` | Two walnut slats connect the back cushion to both rear rails; lumbar pillow and piping lowered 18 mm into the seat | 0.845 x 0.890 x 1.079 |
| `seating-refined-v1/chair-accent-supported` | Back extends 12 mm into the seat, retaining its top; two original rear legs extend internally into the back | 0.480 x 0.460 x 0.840 |

Both preserve the source outer dimensions, original materials and front -Y/up Z.
The lounge has 17 mesh parts and 5,730 vertices; the accent has six parts and 320
vertices. The small accent chair remains a simple white-model-style furnishing.
Its original back/seat seam was mathematically tangent; bevel shading made that
connection look weaker. The refinement adds intersecting geometry and continuous
rear support. It is not evidence that the original had a disconnected component.

The parent inspected the new rear material and side clay views for both chairs.
See the lounge comparison (historical or external input; omitted from this bundle),
lounge rear (historical or external input; omitted from this bundle),
accent comparison (historical or external input; omitted from this bundle),
and accent side (historical or external input; omitted from this bundle).

## Complete broadleaf plant

The authored broadleaf candidate adapts the g0025 bowl profile and existing
RoomKit green/ceramic materials. Twenty thin curved mesh leaves have attached
petioles, midribs and side veins; the pot includes soil and a closed base.
Its bounds are approximately 0.742 x 0.790 x 0.710 m. Balanced horizontal leaf
extents keep the pot base at the declared floor-center origin during export.

The plant is a stylized ornamental with a visibly regular paired arrangement.
It does not claim botanical fidelity, exact reconstruction of an existing plant,
or a general foliage collision guarantee. The authored presentation front is -Y,
up is Z, and symmetry is `none`; an asymmetric plant is not rotationally symmetric
just because its pot is round. Leaf/petiole relationships use `leaf_id` and
`plant_role` within each instance. Object names are source provenance and must
not be used to resolve relationships after Blender copies/renames objects.

Whole candidate (historical or external input; omitted from this bundle),
leaf closeup (historical or external input; omitted from this bundle),
and build measurements (historical or external input; omitted from this bundle).

## Delivered library integration

The registered demonstration (historical or external input; omitted from this bundle)
contains both supported chairs and the complete leafy plant, with
material (historical or external input; omitted from this bundle)
and clay (historical or external input; omitted from this bundle) stills.

Job 45938186 passed all three assets and eight asset-index tests. At that checkpoint the
catalog contained 73 cards, including 41 registered entries: ten model collections
and 31 materials. The three new models are selectable by stable item ID through
`place_asset` and the existing model-replacement recipe interface.

## Natural foliage continuation

The user asked whether the potted plant is procedural and whether it could look
more realistic. Both versions are script-built. The v1 generator uses opposed
leaf pairs; the new [generator](../tools/build_natural_plant_asset.py) uses an
irregular clump inspired by [UF/IFAS peace lily morphology](https://gardeningsolutions.ifas.ufl.edu/mastergardener/resources/plantid/flowers-and-foliage/spathiphyllum/).
It is an authored foliage model, not a scanned specimen or exact cultivar.

Registered item `plants-v2/plant-peace-lily-natural` contains 27 leaves (12 mature,
11 mid-stage and four young folded leaves), across four basal crowns. Blades vary
in size, bend, twist and margin shape. Tapered petioles and basal sheaths replace
the v1 uniform rods. Fine UV-aligned veins, color/roughness variation and restrained
6.5-10% Translucent BSDF mixing replace the prominent secondary-vein tubes.
Leaf tissue thickness is 0.28 mm. The same existing pot mesh/material is retained;
soil receives small granules. No photographic texture or external model is embedded.

The accepted seed/count is **20260911 / 27**, with local pose adjustments selected
after visual and triangle-intersection review. It measures approximately
0.755 x 0.700 x 0.719 m, with 84 mesh parts and 60,369 vertices. Final root is
whole-geometry floor center; the physical pot is offset about +1.36 cm X and
+0.99 cm Y. The offset is recorded so placement and support can be reviewed without
forcing artificial mirrored foliage merely to center the bounds.

The first candidate had 12 intersecting leaf-blade pairs. Local adjustments removed
the conspicuous mature-leaf piercings, leaving two pairs among internal folded
young leaves (25/26 and 25/27). These remain a known limitation. Other seeds or leaf
counts have not passed the same visual/clearance review, and no general collision
or photorealism guarantee is made.

The matched comparison (historical or external input; omitted from this bundle)
aligns the actual pot centers at native scale and uses identical cameras, exposure,
world light and area lights per view. Parent reviewed
front (historical or external input; omitted from this bundle),
side (historical or external input; omitted from this bundle)
and backlit (historical or external input; omitted from this bundle)
pairs. The plant has a less regular silhouette and subtler leaf surface detail
under both illumination setups; the comparison supports a visible improvement,
not equivalence to a photograph.

Job 45948104 passed the registered v1-to-v2 replacement, independent copies with
20 and 27 leaf identities, save/reopen geometry checks, eight asset-index tests
and eight matched renders. Export job 45947949 preserved all evaluated vertices,
topology, UVs and material graphs with zero coordinate difference. The
editable comparison scene (historical or external input; omitted from this bundle)
and registered reuse demo (historical or external input; omitted from this bundle)
are ready to open. The current text index contains 74 cards, 42 registered items
(11 models and 31 materials). Old versions and saved rooms remain unchanged.

## Acceptance and maintenance

Inspect front, rear and low side views for seating, plus whole-plant, top, leaf
and pot views for foliage. A renderable or decodable asset alone does not establish visual quality.

The owner superseded the old immutable-library policy on September 13, 2026.
Publish reviewed improvements under the current stable ID/path; do not register
obsolete copies solely for reproducibility. Build distinct temporary candidates
for inspection, then update the canonical payload, manifest, checksum and
orientation evidence together. Exact current hashes still protect imports from
accidental or partially published changes.
Register palettes as dependencies when they adapt existing materials. Rebuild
and check the [text index](../assets/README.md#text-discovery) under a shared-path
claim. Validate multiple independent placements, compatible model replacement,
and saved/reopened geometry using the actual registered import path.

Existing room scenes retain their saved meshes. Updating the asset library
makes improvements available to new placement or an explicit scene replacement;
it does not automatically rewrite old rooms, contact-dependent motion or videos.
The [current quality tools](../tools/asset_quality_upgrade/README.md) audit and
refresh explicitly identified static placements. Loose legacy parts require a
reviewed semantic migration; object names alone are not an asset identity.

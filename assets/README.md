# Reusable assets

Twelve registered Blender libraries are included as ordinary files. Their IDs
and paths remain stable when reviewed improvements replace the current payload.
The owner adopted this policy on September 13, 2026; obsolete geometry does not
need a second registered library solely for reproducibility. Checksums identify
the exact current bytes. See [the quality review](quality_review.json).

| Library ID | Furniture/plant collections | Registered materials |
| --- | ---: | ---: |
| `roomkit-v1` | 3: sofa, lounge chair, counter stool | 31 |
| `cabinets-v1` | 1 operable storage cabinet | 0 |
| `dining-chair-v1` | 1 open-frame dining chair | 0 |
| `ceramic-vase-v1` | 1 rounded vase | 0 |
| `faucet-simple-v1` | 1 gooseneck faucet | 0 |
| `seating-refined-v1` | 2 supported chairs | 0 |
| `plants-v1` | 1 complete broadleaf potted plant | 0 |
| `plants-v2` | 1 peace-lily-inspired potted plant | 0 |
| `tabletop-plants-v1` | 2: compact fern and pink hydrangea bowl | 0 |
| `additional-444547-44-v1` | 9 dining collections | 11 palette variants |
| `additional-444547-45-v1` | 16 lounge collections | 11 palette variants |
| `additional-444547-47-v1` | 11 bedroom collections | 6 palette variants |

See the [additional 44/45/47 catalog](additional-444547/v1/README.md) for dimensions,
previews, source coverage, refinements and validation evidence. These are editable
static approximations; source scale is uncalibrated and drawer fronts are static.

The [tabletop plants](plants/tabletop_v1/README.md) provide two distinct editable
models with physical pot-bottom mounting origins, embedded materials and reviewed
front/top/side/support views. Scene-specific leaf material overrides can adapt
them to existing lighting without changing the registered library materials.

The 31 original materials and 28 additional palette variants are cataloged material assets. Other libraries retain embedded
materials without registering those dependencies as new material designs.
Historical whole scenes are excluded; normalized reusable extractions remain.

## Text discovery

```bash
python tools/asset_index.py tree
python tools/asset_index.py search sofa --kind collection
python tools/asset_index.py search --category materials/wood --json
python tools/asset_index.py show roomkit-v1/sofa-linen-three-seat
python tools/asset_index.py check
```

See [the generated catalog](INDEX.md) and [registry](registry.json). The curated
catalog includes only registered libraries and shared callable helpers. Objects
that still need extraction from omitted scenes are intentionally absent.

Inside Blender, use `aha3d.assets.resolve` or the validated
`place_asset` interface in [scene variants](../docs/SCENE_VARIANTS.md). Dimensions
are metres. Read each item's orientation and origin; do not infer front direction
from a library-wide label. Prior orientation reviews are retained as
historical metadata; this does not include the old review renders.

The RoomKit skill retains its original small library and preview images for its
standalone examples. It is the same three furniture/31 material asset set, not a
second set of new designs. The central registry is the canonical asset inventory.

For edits, claim registry/catalog outputs, build and inspect a distinct temporary
candidate, then publish it over the current library only after validation. Update
the manifest, registry checksum and matching orientation evidence together, and
run `python tools/asset_index.py build` followed by `check`. Inspect geometry, dependencies, support, placement and rendering before
publishing assets. See [orientation](../docs/ASSET_ORIENTATION.md) and
[quality](../docs/ASSET_QUALITY.md).

Registration is an explicit closeout step, not an automatic consequence of
creating an object in a room. The exporter creates the library and manifest;
registry promotion and index/catalog builds make reviewed assets discoverable.
Scene-local candidates are not reusable registered assets until extraction,
dependency/orientation/support review, and actual registered import/reopen checks
are completed. Updating the index alone does not perform those checks.

This is an internal distribution; see [distribution status](../DISTRIBUTION.md).

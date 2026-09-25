# Project tools and skills

Choose the skill for the current operation; load its detailed references only
when needed. Shared policy and task routing live in [docs/INDEX.md](docs/INDEX.md).

| Skill | Use |
| --- | --- |
| [Indoor scene workflow](.agents/skills/indoor-scene-workflow/SKILL.md) | Complete reconstruction or resuming its stages |
| [Blender RoomKit](.agents/skills/blender-roomkit/SKILL.md) | Editable rooms, furniture/material assets, cabinets and cameras |
| [Pi3X reference](.agents/skills/pi3x-scene-reference/SKILL.md) | Source geometry, cameras and dimensioned reference views |
| [GVHMR reconstruction](.agents/skills/gvhmr-body-reconstruction/SKILL.md) | Estimated source-person motion and fixed rigid room alignment |
| [Kimodo motion](.agents/skills/kimodo-body-motion/SKILL.md) | New/changed actions or documented generated fallback |
| [SAM 3D motion reference](.agents/skills/sam3d-motion-reference/SKILL.md) | Reviewed sparse pose guidance for the generated route |
| [Local runtime](kimodo_blender/RUNTIME.md) | Runtime profile, background batch workers and troubleshooting ([policy](MACHINE.md)) |
| [Browser demo](.agents/skills/blender-browser-demo/SKILL.md) | Saved Blender scene to interactive browser delivery |
| [World postoptimization](docs/WORLD_POSTOPT.md) | Corrected v2 world-space optimization of tracked bodies and foot-contact metrics |

Project skills stay under `.agents/skills/` because their links use this checkout.
System/plugin skills are not project source.

## Tools by operation

| Operation | Interface and details |
| --- | --- |
| Coordinate writers | `python3 tools/task_claim.py list --compact`; [coordination](docs/COORDINATION.md) |
| Declare scope and enforce completion | `bash tools/indoor acceptance`; [acceptance](docs/WORKFLOW_ACCEPTANCE.md) |
| Browse assets and pipeline stages | [Generated catalog](docs/catalog/README.md), [HTML](docs/catalog/index.html) |
| Search furniture | `tools/asset_index.py`; [asset index](assets/INDEX.md) |
| Review object placement/source fit | [Object review](docs/SCENE_WORKFLOW.md#furniture-layout-review-entrypoint), [layout inspection](docs/LAYOUT_INSPECTION.md), [placement check](docs/PLACEMENT_CHECK.md) |
| Replace scene assets | `tools/scene_variant.py`; [variants](docs/SCENE_VARIANTS.md) |
| Export operable assets | `tools/export_articulated_asset.py`; [orientation](docs/ASSET_ORIENTATION.md) |
| Configure a runtime | `tools/configure_runtime.py`; [setup](docs/SETUP.md) |
| Register/select deliveries | `bash tools/indoor results`; [results](docs/RESULTS.md) |

Rebuild the human catalog with `python tools/build_catalog.py build` and `check`
after changing assets, skills, stages or demo metadata. Shared implementations
live in `src/aha3d/`; use documented commands before reading source.

## Requested motion experiments

[Motion controls](docs/MOTION_CONTROLS.md) defines the default and authorization
boundary. For explicitly requested refinement, use [contact repair](docs/CONTACT_REFINEMENT.md),
[trajectory experiments](docs/TRAJECTORY_REFINEMENT.md), or
[resumable human experiments](docs/HUMAN_AUTOMATION.md) as applicable.


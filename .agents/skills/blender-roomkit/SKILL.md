---
name: blender-roomkit
description: "Build or refine editable Blender interiors from references; reuse, place or replace furniture and materials. Use for room modeling, reusable interior assets, and requested cabinet or camera animation."
---

# Blender RoomKit

Use the registered assets and `scripts/roomkit.py` helpers for editable rooms.
User instructions govern scope. For new reference reconstructions, default to a
static scene and useful inspection stills; add animation only when requested or
already authorized. Preserve unrelated existing animation during revisions.

## Choose the work needed

Read the matching reference or section only. Follow further links when the current
operation needs them; do not preload every reference, related skill or lesson.
Repository coordination, runtime and delivery rules remain in `AGENTS.md` and
the linked project docs; do not reread unchanged instructions already in context.

| Current operation | Read when needed |
| --- | --- |
| Reconstruct or correct a room from source images/video | [Reconstruction](references/reconstruction.md) |
| Find, place, replace or extract furniture/materials | [Assets](references/assets.md); search [asset index](../../../assets/INDEX.md) before authoring |
| Animate doors/drawers or author a camera path | [Animation](references/workflows.md#animation-json) |
| Render stills or a requested clip | [Rendering](references/workflows.md#rendering-and-resuming) |
| Import/export source cameras or combine room and people | [Source cameras](references/cameras.md) |
| Resolve executables or a runtime failure | [Runtime](../../../kimodo_blender/RUNTIME.md), [render settings](../../../docs/RENDERING.md) |
| Validate saved placement/replacement edits | Run [placement check](../../../docs/PLACEMENT_CHECK.md); the layout renderer already includes it |

## Choose the inspection tool

For reference layout work, **individually inspect every main item—at least beds,
tables and shelves—before advancing beyond layout review**. Open each item's
isolated X-ray focus images against matched source views and a plan/side view;
record its discrepancies, repair and recheck. A generated packet or whole-room
verdict does not complete this step. Include other dominant and user-flagged items.

- Highlight modeled objects: native `quick_check --object-id <exact-id>` for
  visible contours; `object_outline` and `agent_review --all-objects` for X-ray
  silhouettes and per-object focus images.
- Identify source pixels: reviewed SAM3 masks or source landmarks. Account for
  occlusion before interpreting scores or depth fits.
- Repair a mismatch: hold reviewed cameras fixed, edit one complete object root
  or structural plane, then compare affected objects in plan and source views.
  Use separate stable IDs for furniture and structure.

Use [layout inspection](../../../docs/LAYOUT_INSPECTION.md#object-review-default-and-repair-loop)
for commands and evidence requirements, from the first reconstruction blockout.

## Shared constraints

- Open a saved source in background Blender and write a distinct output. If
  unsaved UI edits are needed, obtain a current saved copy first.
- Put `--python-exit-code 1` before `--python`/`--python-expr`; propagate failures
  and check the saved output before dependent work. Use Blender Python for `bpy`.
- Move complete placement roots. Canonical semantic placement uses metres,
  **-Y front, Z up**; registered imports normalize verified source axes. Preserve
  materials, joints and independent controls when replacing assets.
- Inspect actual representative renders against the source. Geometry checks and
  generated review text do not establish similarity. Repair visible findings
  within scope; blockers do not by themselves require another user approval.

Deliver the edited `.blend`, requested stills/clips and relevant metadata, with
remaining approximations stated. For clips, validate full decoding and requested
timing as well as visual quality. `demo_scene.py` is a helper integration example,
not a starting layout or an implicit animation requirement.

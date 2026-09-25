# 0002: Shared pipeline and isolated scene runs

Status: accepted implementation direction. Date: 2026-09-08.
Source: the user's request to continue the full maintenance/scaling refactor.
Implementation and validation: task handoff (historical or external input; omitted from this bundle).

Scene-specific scripts previously repeated generation, placement, rendering and
validation logic. Multiple agents could also write ambiguous output directories
or unknowingly rerun expensive motion stages for camera changes.

Use one Python package under `src/aha3d/`, strict per-scene JSON recipes,
versioned shared assets and explicit runtime profiles. Execute every run in a
unique directory with copied inputs, frozen code/configuration, stage fingerprints,
logs and validation artifacts. Coordinate edits through the existing task claims.

Prepare and execute on the local workstation, one GPU job at a time; batches run
sequentially in a background worker. Resume intact stages and rendered frames; reuse
matching motion stages for camera/material variants. Require recorded visual
review before selecting a delivery.

Existing scene workspaces now follow [Decision 0003](0003-scene-layout.md).
Use the shared runner for new work without breaking active scene runs. Installed
licensed assets and runtime dependencies remain shared rather than duplicated
into every run. See the [pipeline guide](../PIPELINE.md) for the exact guarantees
and limits.

---
name: pi3x-scene-reference
description: Generate Pi3X room reference geometry, timestamped cameras, and source-colored dimensioned views with source-linked measurements. Use for bird's-eye or side references, approximate room/object dimensions, and scale calibration from video or cached predictions.
---

# Pi3X scene references

Produce source-linked geometry, cameras and dimensioned views for editable room
authoring. Keep observations, fitted surfaces and inferred hidden bounds distinct.
User instructions govern scope; follow project ownership and [runtime](../../../MACHINE.md) rules.

## Choose the operation

- **New video:** read [reconstruction](references/reconstruction.md); run
  `python -m tools.layout_inspection.build_reference` for Pi3X, SAM3, alignment,
  meshing and source overlays. Use one continuous shot and preserve frame IDs/PTS.
- **Floor/up/wall axes:** read [structural alignment](../../../docs/STRUCTURAL_ALIGNMENT.md).
  Review floor/wall masks and plane support. Camera-up alone establishes no floor.
  Preserve an existing room basis unless deliberately migrating room and cameras.
- **Cached dimensions/diagrams:** read [measurements](references/measurements.md);
  run `scripts/measure.py`, passing `--cameras` for the final aligned basis.
  Reuse predictions for changes to labels, display slices or scale cues.
- **Surface dimensions:** read [mesh measurements](references/mesh-measurements.md)
  or [furniture measurements](references/furniture.md). Use source corners or
  reviewed SAM3 masks; visible extents do not establish complete furniture bounds.
- **Room authoring:** use [Blender RoomKit](../blender-roomkit/SKILL.md) in the same
  reference basis, then run [matched layout inspection](../../../docs/LAYOUT_INSPECTION.md).
- **Human depth/camera handoff, only when requested:** read
  [tracking and trajectory](../../../docs/HUMAN_TRACKING_AND_TRAJECTORY.md).
  Keep these observations separate from static geometry; follow
  [motion policy](../../../docs/MOTION_CONTROLS.md).

## Preserve these invariants

- Use the 32-frame default or 64-frame tier over the full shot; shorter videos use
  every frame. Semantics and meshing consume all inference frames. Display-view
  selection never reduces reconstruction coverage.
- Default to the 3 cm TSDF core plus visible context. For fusion/filter details,
  read [geometry reference](../../../docs/PI3X_GEOMETRY_REFERENCE.md) when needed.
  Measurements use source triangles and `measurement_valid`, not display patches.
  People are excluded; glass/mirrors remain explicitly uncertain.
- Keep one rigid transform shared by points and cameras. Uniform metric correction
  is separate and applies to geometry, dimensions and camera translations together.
  Pi3X scale is predicted; assumed object sizes are assumptions. Reprojection
  agreement and model confidence do not establish physical accuracy.
- Choose measurement endpoints from actual source frames. Retain source pixels,
  timestamps and selection rationale; reject unreliable depth edges. Missing
  geometry is unknown, not free space. Height requires an explicit floor basis.
- SAM3 labels source pixels; native object outlines highlight authored geometry.
  Inspect identity, occlusion and front details. Check source agreement across
  views rather than accepting a fit score or a generated report.

## Deliver and inspect

Provide plan/front/side views and 3–5 native source-camera overlays (five by
default), spanning distinct visible regions and early/middle/late times. Initial
reference overlays need no authored room; once a room exists, add matched model
edge comparisons and label which geometry is shown.

For measurements, deliver `MEASUREMENTS.md`, diagrams, JSON/CSV and `cameras.json`.
Inspect arrows, endpoints, units and timestamp labels; retain source RGB and
scale/floor limitations. Source pixel IDs are provenance, not tracked physical
points. Sparse camera keys need an explicit interpolation policy and playback
review before being used as a full-rate animated camera.

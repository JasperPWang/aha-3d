# Saved-room placement check

Run one command from the configured checkout:

```bash
source kimodo_blender/env.sh
bash tools/indoor check-placement /absolute/scenes/SCENE/blender/room.blend
```

The command infers `SCENE` from a source under `scenes/SCENE` or `runs/SCENE`.
For another source location, add `--scene SCENE`. The scene must already exist.
It allocates a standard scene run, claims its output, runs Blender on the CPU in
the foreground, verifies the source bytes did not change, and releases its run
claim when it finishes. No manual object list, cameras, model inference, physics
installation, or Blender script is required. Configure `BLENDER_BIN` in the local
environment; Blender threads follow `INDOOR_THREADS` or the runtime profile. A
nonzero exit or missing report is not completed evidence.

The equivalent standard-Python entry is `python tools/check_placement.py SOURCE`.
For cross-scene tests or a standalone run, pass `--out NEW_DIR`;
that path must be covered by the caller's task claim. An existing output is never
replaced. A rerun after scene edits creates fresh evidence.

## What the agent reads

The command prints the run, log and report paths. Open `placement/report.html`
for numbered top/front/side geometry projections, a concise exception table,
expandable affected-object views, and the object inventory. `placement/REPORT.md`
is the agent summary; `placement/report.json` contains the complete diagnostics,
coverage, thresholds and per-object reasons. `status.json` binds source and code
hashes, configuration, run ID (`INDOOR_RUN_ID`) and output hashes. The snapshot records the
code that executed. The saved source is never overwritten and original materials
and animation are retained.

1. Read the exception table and corresponding source views.
2. Correct only demonstrated layout/geometry errors at complete placement roots.
3. Rerun the same command. Review unknowns explicitly instead of treating them as
   passed checks. Continue the existing Pi3X/native-view layout review.

Completion means the diagnostic ran. `needs_attention` means errors or warnings
were found; `incomplete` means unresolved coverage/metadata; `no_issues_detected`
means no reported issue within the stated scope. None grants scene acceptance.
Exit 0 means a complete diagnostic, including a report with layout errors; exit 2
means execution/configuration failure. Consumers must inspect `summary.status`.

## Automatic layout integration

The existing `tools/layout_inspection/render_blender.py` entry also runs this check
on the authored scene before adding reference geometry, at `model_frame`. It
writes `inspection/placement/` alongside the Pi3X/native-camera evidence, so the
ordinary pipeline layout stage requires no extra command. Placement reports are
included in the layout evidence hashes and invalidate the review if modified.
Historical evidence without this extension remains structurally readable; the
changed gate implementation invalidates older implementation-bound receipts.
Review placement exceptions together with source comparisons before recording
an accepted layout review. Geometry diagnostics do not automatically approve or
repair a scene.

## Checks and discovery

- Geometry: evaluated visible meshes, curves and collection instances, including
  modifiers and world transforms. Nearest semantic `instance_id` roots define
  complete objects. Legacy parent hierarchies are retained but reported as
  unverified grouping; no source tags are fabricated. Excluded render collections
  and hidden ancestors are respected. Duplicate IDs and unmatched overrides fail.
- Collision: broad bounds filtering followed by component triangle BVHs and
  sampled, two-ray inside/outside checks on closed components. A contained solid
  can be detected even without crossing triangles. Table legs/shelf boards remain
  separate components; empty furniture cavities are not filled by an object box.
  Deep sampled interior points are errors. Shallow intersections with semantic
  rugs/carpets at most 8 cm thick remain soft-cover contact warnings, not ignored
  pairs; these covers are static obstacles in the rigid-body test. Unresolved surface crossings remain
  warnings. Default penetration tolerance is 5 mm in scene-scaled metres.
- Support: reuse `support_id` or infer candidate surfaces below sampled bottom
  geometry. Record the target, gap and sampled contact fraction. Default contact
  tolerance is 2 cm. Declared missing supports and undetected supports are unknown.
  Wall/ceiling mounting is held fixed and marked unverified; declaring attachment
  does not bypass collision tests. Floor/wall/ceiling roles come from metadata,
  surface tags, or explicitly recorded name hints for untagged structure. Generic trim/beam/roof
  name hints identify architectural components for seam exclusion; all such hints
  are listed in coverage. Furniture against these components is still checked.
- Facing: reuse the shared facing preflight; missing or invalid intent remains
  unverified. Unknown source-facing direction is never inferred from bounds.
- Stability: automatically test eligible static semantic objects using Blender's
  rigid-body solver in a disposable scene. Closed connected components must have
  volume within 2% of their convex hull to form a compound collision shape. Concave,
  open and oversized components are skipped with reasons rather than filled in.
  Structures, mounts and ineligible geometry remain static triangle obstacles.
  Record maximum displacement, final rotation and residual speed over two seconds.
  Default flags are 3 cm motion or 5 degrees rotation. No settlement is copied back.

The report geometry diagrams use per-component convex projections of sampled
extremal vertices. They are illustrations, not collision geometry, depth renders,
or source-image comparisons. Pair details are shown for the first 30 exceptions;
the JSON/table retains every exception.

## Optional overrides

Most inputs need no configuration. Supply `--config placement.json` only for
explicit scene knowledge or different thresholds:

```json
{
  "simulation_seconds": 3.0,
  "objects": {
    "wall-lamp": {"support": "wall-east", "fixed": true},
    "table-vase": {"support": "dining-table", "mass_kg": 1.5},
    "diagnostic-reference-root": {"exclude_reason": "Pi3X reference layer, not authored room"}
  }
}
```

Keys must match exact visible root IDs or Blender root names. Allowed object
fields are `role`, `support`, `fixed`, `mass_kg`, and `exclude_reason`. Unknown
keys or invalid values fail before compute. Prefer stable metadata in authored
scenes over repeated per-run overrides. `--physics off` disables only the
stability test; `--frame N` selects one evaluated frame. `max_samples` and
`max_simulated_objects` bound work; every skipped movable object is reported.

## Limits and evidence

This is a room placement diagnostic, not calibrated physical certification.
Masses, friction, collision margins and uniform-density centers of mass are
assumptions. Thin crossings, open meshes and complex concave assets can require
review or better collision geometry. Contacts within one semantic root and
structural seams are excluded. There is no automatic door/drawer sweep,
navigation test, whole-clip body collision test, human motion correction,
automatic repair, or Pi3X reconstruction. Existing source-motion policies apply.

Regression tests inject wall penetration, full containment and floating objects;
retain legitimate floor/table contacts and chair-under-table clearance; exercise
collection instances, hidden roots, duplicate IDs, unsupported geometry, actual
rigid-body movement, source preservation and evidence tampering. See
`tests/blender/check_room_placement.py`, `tests/test_room_placement.py` and
`tests/test_layout_gate.py`. Run tests locally per `MACHINE.md`.

Design motivation: [SceneMosaic, Sections 3 and 6](https://arxiv.org/pdf/2609.05594v1).
This implementation uses existing Blender geometry and physics rather than the
paper's reconstruction stack. Component validation is not CoACD decomposition.

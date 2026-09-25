# Reference reconstruction

Read for room authoring or source-layout corrections. Resume established scope;
for a new scene, record it through [scene requests](../../../../docs/SCENE_REQUESTS.md)
and [acceptance](../../../../docs/WORKFLOW_ACCEPTANCE.md). Aim for recognizable
structure, object types, proportions, placement and occlusion. Increase precision
only when requested or supported by evidence.

## Pi3X-first reference workflow

For project video references, use the
[Pi3X reference skill](../../pi3x-scene-reference/SKILL.md) before committing room
dimensions, placements or camera basis. For ordinary revisions, reuse suitable
reviewed predictions. For an explicitly independent rebuild, use the original
video and a new bundle without consulting prior scene implementations or outputs.

1. Inspect source frames and shot continuity; retain native frame IDs and decoded
   timestamps. Review Pi3X geometry, floor and static surfaces, excluding moving
   people, reflections and depth boundaries from measurements.
2. Record source-linked room/opening/furniture measurements with endpoint pixels
   and reliability. Separate observed surfaces, fitted planes and unseen
   completions. Predicted metres are approximate without known-length calibration;
   assumed furniture sizes are not measurements. Record unsupported measurements
   as unknowns and label manual assumptions; do not calibrate Pi3X to a guessed room.
3. Use one recorded world transform and scale for reference points, measurements,
   authored geometry and camera centers. Scale camera translations with geometry;
   preserve rotations, intrinsics, timestamps and pixel conventions.
4. Author the editable white model in that frame. Pi3X remains reference geometry.
   Static comparison cameras need no separate approval; exporting observations
   does not authorize a camera animation. For import/calibration mechanics, read
   [source cameras](cameras.md).

## Compare the scene, not just the file

Use [layout inspection](../../../../docs/LAYOUT_INSPECTION.md#object-review-default-and-repair-loop)
from the first blockout. Individually open the isolated X-ray focus images for
each main item, including beds, tables and shelves, against matched source and
plan/side views; then inspect depth/visible contours. Review other dominant and
user-flagged items as well. Verify filters include the intended roots.
Keep object/view-specific findings open until corrected; a collision report,
camera agreement or one overlap score does not establish source fidelity.

Prioritize room envelope/openings, dominant furniture silhouettes and counts,
relative extents, occlusion, facing and circulation. Hold reviewed cameras fixed
while repairing layout. Recheck affected neighbors after moving or resizing roots.
Use the [asset reference](assets.md) when choosing or adapting furniture: library
convenience must not change the reference's object type or layout.

Review one complete custom object before duplicating it. Primitives and generic
noise remain blockout approximations when silhouette, construction or finish is
visibly wrong. Inspect actual material stills after geometry corrections; settle
layout in inexpensive readable previews before polishing lighting. Finish the
current scene's source/layout, material and preview review before expanding a
batch under the [quality gate](../../../../docs/SCENE_WORKFLOW.md#quality-before-batch-expansion).

## Verify support and attachment before delivery

Run the shared [placement check](../../../../docs/PLACEMENT_CHECK.md) after saved
placement/replacement edits. The layout renderer already invokes it; avoid a
duplicate immediately before that renderer. Inspect flagged pairs and source
views, repair demonstrated errors and rerun affected checks. Placement reports
diagnose geometry; source fidelity still requires visual review.

For targeted support diagnosis, update the dependency graph and use evaluated
mesh surfaces. Measure downward rays to intended supports and surface/plane gaps
for wall attachments. Include furniture bases, tabletop props, shelf objects and
wall-mounted items. Move compound props together; retain fixed-size attachments.
Do not gravity-snap intentionally hanging or recessed parts.

Inspect a low side view with visible support surfaces. Cutaways need usable
framing, lighting and support references. Check continuous cabinet fronts/plinths
against the source; body-floor collision checks do not detect floating static
props. Deliver source views, measurements and alignment/scale provenance relevant
to the scope. Keep unseen completions simple and identify material approximations.

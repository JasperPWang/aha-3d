# Kimodo call and validation lessons

Use this reference for human/G1 generation, segmented scene interactions, or an
unexpected result. It records verified project behavior, not a claim that a
checkpoint always follows its conditions. Official sources: the
[Kimodo repository](https://github.com/nv-tlabs/kimodo) and its documentation.

## Plan the action before constraints

State the desired object change, contact/release intervals, support, and the
motion driver in each phase: walking, torso motion, arm reach, hand motion, or a
combination. Derive the root route from reach, stance and obstacle clearance.
Copying hand displacement to the pelvis is not a general movement strategy.
Neither is freezing the root. Keep the text consistent with the chosen strategy.

Use the smallest useful input for that phase:

- Walking: action text and sparse horizontal route/heading keys when needed.
  Do not impose a pelvis-height trajectory just because another phase sits.
- Reaching/pulling: reviewed grasp position and, if requested, hand orientation;
  allow the arm/torso participation and any step justified by reach and clearance.
- Sitting: sparse pelvis-height and seat-placement keys can be useful. Check
  whether a seat point is initial object-local or final world-space: the human
  and experimental G1 adapters historically used different conventions.
- Carrying: check the object's position relative to the torso throughout turns,
  not only at pickup/dropoff. Replan the route or facing if the object passes
  through the body. Walking backward while facing the carried prop worked for
  one book-transfer replan; it is an example, not a default for all carrying.

A palm-down request means a hand orientation in addition to a point. Author an
FK-consistent pose for the actual hand/palm axes; an arbitrary wrist-axis label
is not proof that the mesh palm faces down. It does not imply root translation.

## Verify the actual native call

Use the configured installed upstream source and its matching checkpoint. Compare
with `kimodo/scripts/generate.py`, `kimodo/demo/generation.py`,
`kimodo/constraints.py`, and the official demo inputs. The maintained callers are
`tools/kimodo/interaction_sequence.py` and `tools/kimodo/g1_interaction.py`.

Record the actual text-encoder strings and encoded constraint features, not only
a natural-language description of what the caller intended:

- Text is a list of full action strings; native multi-prompt durations are matching
  integer frame counts at the checkpoint's native FPS (30 in this deployment).
  Check the installed segment-length limit. “A person” is also used by the official
  G1 example; that wording alone does not mean a human model was accidentally used.
- Positions use metres in native Y-up coordinates, with horizontal XZ arrays of
  shape `[N, 2]`. Initial heading is radians; encoded headings are cosine/sine.
  Constraint indices refer to the correct timeline, including continuation context.
- Joint arrays and rotation matrices must match the loaded skeleton and be
  FK-consistent. Check actual masks, feature names, finite values and frame IDs.
- Official `RightHandConstraintSet` also encodes root height, horizontal root and
  heading. “No explicit pelvis constraint” does **not** mean a hand-conditioned
  pass is height-free. Inspect these implicit values before inheriting them from
  a crouched/floating first pass. Blindly stripping the fields is not a validated
  fix. Use sparse, justified keys instead of assuming denser is better.

The text/path pass is a real model generation. Save its native output and inspect
stance/reach before using it to author second-pass hand constraints. Do not call
an interpolated path or a planned pose a Kimodo generation.

## Local frame for every subsequence

Both human and G1 callers use `sample_in_local_frame`. Apply the transform to the
actual diffusion call, including **all** constraints and incoming continuation
frames, rather than moving only the root trajectory:

1. Unnormalize observed features and retain the mask. Subtract the initial observed
   smoothed-root XZ and rotate by the negative initial heading.
2. Rotate root/path, relative joint vectors, global rotation columns, velocities
   and heading pairs consistently. Preserve vertical height and contact labels.
3. Normalize and sample with initial XZ and heading zero. Save the actual local
   features/mask and the transform receipt.
4. Restore generated features to the incoming frame before native continuation,
   blending and human postprocessing. Apply room placement once at export.

Masked-out 6D rotations may be six zeros. Rotate their raw columns linearly;
Gram–Schmidt decoding of those zero placeholders can produce NaNs. Reject scalar
masks whose unpaired X/Z components cannot be transformed consistently.

The deployed native multi-prompt path uses 12 context frames. Retain its blending
and distinguish raw subsequences from the joined result; overlap blending is not
exact preservation of every context sample. If using genuinely separate model
calls, explicitly align starting root/facing and constraints to the prior segment,
then verify seam position, velocity and rotation. Never concatenate four unrelated
world-origin sequences.

The nonzero-heading argument is officially valid. A controlled test on the
installed G1 checkpoint nevertheless produced ~44 cm initial floating, resolved
by a consistent zero-heading local frame. This is measured checkpoint behavior,
not an upstream API prohibition or a guarantee that local frames fix every motion.

## Human and G1 differences

Use matching native checkpoints/skeletons. The official G1 path disables human
postprocessing (`post_processing=False`); do not apply SMPL-X foot cleanup to G1.
Retain official rigid-link geometry and MJCF transforms. Experimental G1 hinge
projection/contact fitting is a separate stage, not official native decoding.

Check support with the **actual foot mesh** against the authored floor on **every
frame**, including frames where all predicted contacts are off. Pelvis
height and predicted contact labels alone miss floating starts. One raised foot
can be a valid walking pose if the other supports the body; both feet high during
an intended grounded start require repair. For non-flight actions, both feet
floating later also fail. A correct first frame and low slip on the few predicted
contact frames do not establish whole-sequence support. Measure contiguous flight
intervals against the rendered floor/rug triangles, and compare actual browser
world-space mesh coordinates with the saved geometry.

If a local-frame sample still starts unsupported, an inspected grounded native
full-body pose at frame zero can be supplied using `FullBodyConstraintSet` and the
G1 caller's `initial_pose_file`. Transform its complete pose into the same native
frame and remove duplicate first-frame root/heading keys. Save its source and
adjustment. This is an explicit initial-pose intervention, not a height constraint
throughout walking or proof that the model naturally started correctly. Verify
that the generated and refined mesh actually follows it.

## Refine and compare the whole result

For generated human motion, optimize joint rotations in 6D or quaternion/matrix form; compute temporal
rotation differences on rotations. Loading original axis-angle parameters once
is different from optimizing/blending discontinuous axis-angle vectors. G1's
bounded physical one-axis hinge scalars, reconstructed with sine/cosine, are not
free 3D axis-angle pose optimization. Protect unrelated head/neck motion.

Refine hand/object, foot/support, seat and temporal objectives together when they
apply. A root-only contact correction can worsen planted-foot velocity. A later
leg-only repair can reduce skating while pushing knees/thighs into furniture or
breaking a seat contact. Compare both contacts and collision geometry after every
such stage; a lower hand-point error alone is insufficient. For source-human
reconstruction, the owner removed the entire 6D leg-repair stage and all collision
correction (2026-09-21), including root collision shifts. Keep GVHMR/V2 articulation
fixed in the current translation-only baseline (including upper-body joints, which
is an experimental restriction rather than an owner prohibition); retain
source-supported hand/seat/foot contact objectives using smooth
whole-body translation. Compare constant versus time-varying corrections because
even a smooth root shift can increase foot skating. Collision checks are diagnostic.

When a generated route is infeasible, inspect mesh intersections and replan body,
prop placement or facing before escalating optimizer weights. Keep intended hand
contact separate from elbow/torso collisions. Hollow furniture must not be treated
as a solid bounding box without acknowledging that approximation. Kinematic grasp
and joint-limit checks do not establish friction, balance or robot executability.

## Deliver every requested case

Keep exact input snapshots, seeds, actual call receipts, text/path baseline, raw
subsequences, native join, projection (G1), and before/after contact results. Show
phase start/end seconds and allow matched-time stage comparison. Frame the viewer
so the feet and contacted object are visible; inspect real representative frames
and fully decode each rendered video with its timing. Retain a video fallback.

A repair tested on one lamp does not repair the other five demos. Maintain an
explicit per-case selected-output manifest, validate each case, rebuild current
viewer links, and check that every entry resolves to the intended new artifact.
An output file, successful exit, historical screenshot, or newly built gallery
is not motion-quality acceptance. Preserve unresolved findings explicitly.

The 2026-09-21 bowl/book investigation found a second failure: hand constraints
inherited root Y from unsupported poses, while roughly 190 frames had all native
contact labels off. Author grounded hand constraints, then fit hand and
actual mesh-floor support jointly for explicitly non-flight actions. Preserve raw
contact predictions; any geometric fallback weights must be saved separately.
Refresh finite floor/rug heights after pose/XY changes and validate every frame
in the actual browser hierarchy. Do not apply this support rule to flight actions.

## G1 hand surfaces and unresolved native motion

The former `patches()` hand proxy was the mean of all rubber-hand mesh vertices,
not the distal surface claimed by its comment. Constraining that interior point
to the object surface could insert the fingers/palm. Use the actual distal
rubber-hand surface vertex (`hand_contact_patch=fingertip`) for touch/drag tasks.
`legacy-centroid` is only an explicit historical comparison. The official mesh's
local +Z runs toward the finger tips; this axis is not a world-space direction.

Review the finite contact mesh, point and outward `hand_surface_normal` in room
coordinates. Prefer the first surface visible from the approach direction over
a nearby interior cushion or the far wall of a hollow object. Transform both
point and normal to the generation frame. Fit the fingertip position and keep
the whole hand outside that local contact surface, including smooth approach and
release intervals (`hand_clearance_seconds`). Per the user's 2026-09-21 update,
G1 object collision detection is cancelled: do not run mesh penetration audits
or supporting-plane penetration diagnostics, or require them for delivery.
Retain fingertip contact fitting, its local surface-normal constraint, foot-ground
support and temporal smoothing. These contact constraints do not certify that
the robot is collision-free. Old collision reports remain historical evidence;
the standalone diagnostic helper is not called by the generation pipeline.
The fixed rubber hand has no articulated fingers: a fingertip touch does not
establish a force-bearing grasp, particularly for carrying a bowl or book.

The later bowl/book audit verified that the deployed upstream commit matched
remote HEAD; it did not find a text-list or constraint-shape API error. Controlled
first-segment experiments showed that current route conditioning can damage
support even when text-only output is grounded. Dense root-path conditioning
reduced one book sample's maximum support gap from 47.2 cm (10-frame path keys)
to 2.82 cm; the same intervention did not resolve the bowl sample. Lower CFG was
also not a general fix. These are single-prompt diagnostics, not full-interaction
acceptance. Preserve seed, heading, prompt and actual masks when comparing.
Do not interpret post-fit 1 mm foot clearance as native model quality, or turn a
single successful seed into a universal default without full-sequence review.

The subsequent full bowl/book selection used dense root keys (`root_path_stride=1`),
no separate heading stream (`heading_constraints=false`), and seed 42 after native
support screening. All four segments were regenerated and checked: neither joined
sample has a both-feet-over-2-cm frame, although native floor penetration around
2 cm still needs the contact fit. This validates those samples, not every seed or
prompt. The historical `hand_object_penetration` audit recorded full right-hand
vertex penetration against closed object triangles, with open parts unverified.
That audit is now disabled at the user's request; its historical findings are
not a current delivery gate. See the rendered-ground lesson for the original
selection and residuals.

# Plan body-part responsibilities before motion constraints

User correction, September 19, 2026: keep the palm-down grasp, but judge whether
an action is driven by whole-body locomotion, torso/upper-body motion, upper-arm
and elbow articulation, wrist/hand motion, or a mixture. Root displacement must
follow that judgment. It must not be copied from hand displacement by default.

## What failed in the chair experiment

The initial palm-down run allowed contact optimization to alter root motion.
The next iteration responded by forcing a constant horizontal root-to-hand offset
through planning, sparse hand-key authoring and final optimization. Its Step 2
text also required two backward steps and hips/whole body moving with the chair
at constant distance. This repeated one unverified action hypothesis in both
language and geometry. No preceding analysis established that it was appropriate.

The user rejected this motion strategy. Palm-down itself was subsequently accepted;
do not record the lesson as a rejection of palm-down grasping or of all root
constraints. A justified backward step remains a valid option.

Exact local evidence (ignored run data; paths retained as provenance, not portable
package dependencies):

- Palm-down run: `runs/dining_interaction/20260919t162103z-hand-down-924bf2ad/final`.
- Fixed-offset run: `runs/dining_interaction/20260919t180905z-root-hand-c8001dfe/stages`.
- Actual submitted text/constraints: the latter run's `generation.json`.
- Metric comparison: the latter run's `coupling-validation.json`.
- Reviewed mesh views: the latter run's `review/`, including hand frames 95/160/205.

Measured mean root-to-mesh-palm relative speed fell from 24.47 to 0.19 cm/s, but
root was explicitly bound to the moving contact. That measurement verifies the
binding; it does not independently establish natural movement. The model inputs
also changed, so this was not an isolated optimization-loss comparison. User
visual rejection takes precedence over the earlier agent quality claim.

## Planning decision for each action interval

Identify the motion driver and participating joints before choosing constraints.
Actions can change strategy within an interval; the following are reasoning aids,
not a fixed taxonomy or an implemented automatic classifier.

| Motion driver | What to inspect | Root implication |
| --- | --- | --- |
| Whole-body locomotion | Footsteps, travel route, clearance, direction changes | Plan root travel consistent with steps and obstacles |
| Torso / upper body | Lean, twist, weight transfer and available reach | Permit justified torso/pelvis participation; do not lock the chain indiscriminately |
| Upper arm / elbow | Shoulder reach, elbow flexion, hand-to-body distance | Much of the hand movement may occur relative to a nearly stationary root |
| Wrist / hand | Local contact orientation and grasp adjustment | Hand direction does not imply pelvis displacement |
| Mixed action | When reach, clearance or support requires a strategy transition | Plan the transition and any step separately from the arm-driven portion |

For pulling a chair, consider reaching/grasping, pulling and release separately.
Judge whether arm articulation and modest torso movement suffice, or whether a
backward step is needed as the chair approaches the body. Use actual geometry,
body reach, body/chair clearance and foot support. Do not replace “copy the hand”
with a universal “keep root stationary” rule or an arbitrary fixed percentage of
the hand displacement. Exact step count and root travel need a scene-specific
reason. A contact position alone does not determine that reason.

Record the intended action, motion driver(s), participating joints, support and
contact intervals, root rationale and any unresolved assumptions in the plan.
Then author text and numerical constraints that express that same strategy.
Constraint priority applies after targets are justified; it does not justify
inventing a root path first.

## Generation and refinement consequences

- Text should describe the intended action and selected movement strategy. Do not
  insert “move the whole body with the hand” or “two backward steps” to explain a
  path chosen without motion analysis. Removing these words alone is insufficient
  if the numerical root trajectory still forces that behavior.
- Keep the first text/path pass free of explicit pelvis-height keys as requested.
  Choose root, hand and support targets jointly after deciding their roles. Native
  sampling can deviate; compare actual generated poses against the intended action.
- Preserve palm-down as a separate grasp-orientation goal. It specifies a hand
  direction, not whole-body translation.
- Choose optimization freedoms for the action. Protecting head orientation is
  useful, but freezing every torso joint can prevent an intended upper-body action.
  Avoid unrelated arm edits; allow joints that the action actually needs.
- If reach/contact goals require large body changes, revisit the action plan and
  regenerate. Do not force an infeasible plan into place with progressively larger
  losses or a collision-response solver.
- Continue using 6D/matrix optimization and rotation-aware continuity. A good
  representation avoids coordinate discontinuities but cannot correct a wrong
  action plan.

## How to assess the next candidate

Keep exact prompts, numerical constraints, actual per-segment samples, native
joined motion and refined motion separate. Compare matched times and camera views
with the last candidate. Evaluate action semantics, whole-body coordination,
root trajectory, steps, torso/arm participation, contact acquisition/release,
foot slip, collisions and seams. Explicitly separate enforced equalities from
independent quality evidence. Compare multiple plausible strategies only when
uncertainty warrants it; do not start a broad search just to improve one score.

The default example now removes fixed root/hand binding and its forced whole-body
text. Its remaining coordinates and timing are historical inputs requiring
replanning; this edit is not a validated replacement motion. The fixed-offset
implementation remains available for deliberate experiments, not as the default
chair-pulling strategy. No new motion was generated while recording this lesson.

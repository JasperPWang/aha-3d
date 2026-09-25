# Temporal diagnosis and input refit

Read this when nearby SAM estimates disagree or generated transitions become
rough. The [pilot lesson](../../../../docs/lessons/sam3d-temporal-guidance.md)
distinguishes evidence from hypotheses and records the current validation limit.

Start with `temporal-report.json`, which the compiler now always writes. Check
source identity/limb assignment, camera alignment, body-relative arm directions,
and the separate heading changes. Native hand keys also guide root and heading;
a rough Kimodo result alone does not prove SAM jitter. Compare with the same
prompt, seed, route and timing, and change only one guidance factor per experiment.

For noisy observations with sufficient neighbors, add this argument to the normal
`aha3d.motion.reference` command:

```bash
--temporal-support-selection "$REVIEWED_SUPPORT_JSON" \
--temporal-window-seconds 0.2
```

The support file follows the normal selection schema and has exactly the same
header as the target selection. Its events contain reviewed neighbors plus the
original target observations. SAM observations and Pi3X must cover every exact
support frame. Support poses are used for fitting only; they do not become extra
Kimodo constraints.

The helper fits upper-arm and forearm unit directions in source time with robust
local linear regression. It preserves facing, root placement, timing and key
count. It needs at least five samples bracketing each key, with gaps no greater
than 0.1 seconds. The default window is a 0.2-second half-window. Large direction
jumps, insufficient support and corrections above 20 degrees retain the original
value with a reason in the report. The Python API exposes gap/correction settings
for a justified experiment; these defaults are heuristics.

Inspect before/after directions and generated target error, heading changes,
jerk, foot clearance and representative previews. A lower fitted input residual
is not proof of smoother or better generated motion. Review rapid true actions
before filtering them. Do not use this helper across cuts or different people.
Do not silently smooth authored heading or physical contact targets.

If heading is unreliable, use the existing authored `facing_xz` field only after
reviewing the desired scene facing, and compare that as a separate variant.
A full SAM parameter refit with shared shape, temporal pose loss and reprojection
loss is separate future work; this helper does not implement it.

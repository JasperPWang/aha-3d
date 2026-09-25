# Temporal reference guidance

Observed September 8, 2026; author `sam3d-temporal-a`.
Scope: SAM/Pi3X directions compiled into native Kimodo hand constraints.

## Evidence and interpretation

The g0070 pilot (historical or external input; omitted from this bundle)
reached three derived wrist goals within 3.29-5.12 cm, but ending jerk p99 was
3.86 times the matched text/root baseline. Its retained poses are about 1.34 and
1.37 seconds apart. This is not enough temporal sampling to identify SAM jitter.
Native hand constraints also guide heading, root height and smooth root. The
inferred heading turns and reverses between these events, so heading guidance
and sparse generator transitions are alternative explanations. Causality remains
unresolved; small reprojection error does not establish pose accuracy.

The user requested skill improvements and temporal smooth/fit support after
reviewing this test. The implemented [input refit](../../src/aha3d/motion/temporal.py)
works on derived arm directions before native FK compilation. It does not refit
SAM model parameters or smooth generated motion. The compiler always emits
pairwise direction/heading diagnostics, including when refit is disabled.

## Operating lesson

Use reviewed neighboring observations to estimate local consistency; emit only
the selected event keys. Smooth in the reference body's local frame after the
same-shot camera transform. Preserve unit directions and use Kimodo bone lengths
through FK. Keep raw observations immutable so original projection checks and
provenance retain their meaning. Do not average camera-space joints from changing
cameras, raw axis-angle values or unwrapped Euler headings.

The initial refit uses robust local linear regression in source time, followed
by unit normalization. It requires at least five samples bracketing the target,
with no gap above 0.1 seconds inside a 0.2-second half-window. Adjacent arm changes
above 75 degrees are not blended; proposed corrections above 20 degrees are left
for review. These are configurable/implementation heuristics, not validated
universal human-motion limits. A rapid true action can look like an outlier.
Facing and root are deliberately unchanged and diagnosed separately.

A denser source selection must preserve one person, one shot, correct limb side,
reviewed overlays, the same coordinate registration and exact Pi3X timestamps.
For a dense test, collect roughly 7-13 samples around each key at the source rate;
ensure Pi3X includes those exact images, then rerun SAM only for the selected
support frames. Separate motion phases or shots into different invocations.
The support selection must include the original target observations. Near a clip
boundary or with insufficient support, retain the key rather than extrapolate.

## Current validation boundary

Task evidence (historical or external input; omitted from this bundle) records synthetic
noise/turn/gap/limb-flip checks and compilation of the cached sparse pilot. The
three sparse pilot keys should remain unchanged: inventing extra samples by
interpolation would not add evidence about SAM noise. No denser real-video SAM
experiment or new Kimodo smoothness benefit is established by these checks.

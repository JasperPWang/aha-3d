# Optional source-occlusion completion

Use only for explicitly authorized completion experiments.

## Partial-body preservation

For the requested source-occlusion completion research, require **both** visible
body-part motion constraints throughout the interval and an explicit action text
prompt. Preserve the visible parts and the source motion outside that interval;
generate only the missing parts. Endpoint keys alone are insufficient for this partial-body preservation experiment. Check
preservation after decoding/skinning, including wrists moved by pelvis changes.
Stock conditioning does not guarantee exact preservation; a validated adapter or
sampler extension may be needed before this experimental route meets the user's
requirement. Keep prompt, visibility masks, targets and seeds with each candidate.


## Whole-body gap replacement

The owner separately authorized whole-body replacement research for PMPose intervals
with fewer than five reliable keypoints on September 17, 2026, then found its visual
quality unsatisfactory and requested skipping it by default. The full world graph
now retains GVHMR motion unless `--kimodo-completion` is explicitly supplied with
an observed-action `--completion-prompt`. Low keypoint counts alone do not enable
Kimodo. The opt-in route uses
`tools/gvhmr/occlusion_completion.py`, not the dense partial-body experiment above.
Use three consecutive reliable frames on each side by default; two per side is
the minimum. Both pose and root inside the invalid interval are generated without
conditioning on its rejected GVHMR values. Preserve shape/timing and all outside
frames exactly. Native full-body endpoint constraints, decoded endpoint checks,
seam velocity/rotation gates and explicit generated-frame provenance are required.
An unresolved interval stops the graph. Actual mesh and scene-contact review still
follow numerical acceptance; endpoint agreement alone is not a quality guarantee.

The whole-body route archives the native sample, then uses a C2 endpoint bridge
plus Kimodo residual confined to the missing interval. Rotation blending is on
SO(3); no rejected GVHMR gap sample is read and outside frames remain exact.
Report this splice explicitly. Raw endpoint equality alone failed the natural
clip32 seam check; do not bypass finite-frame derivative checks or mesh review.

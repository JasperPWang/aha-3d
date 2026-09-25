# Colored references and sparse leg guidance

Status: presentation/tooling implemented; two matched leg experiments evaluated
on living_room_piano_g0064, 2026-09-09. Source, code and job provenance live in the
task handoff (historical or external input; omitted from this bundle). No real-person motion
reconstruction or physical scale calibration is claimed.

## Problem and changes

Gray metric points made wood shelving, dark piano geometry and pale upholstery
hard to distinguish. The Pi3X cache already held source RGB; repeating inference
would add cost without addressing presentation. `measure.py` now defaults to RGB,
uses nearest-depth point rasterization and accepts per-view `clip_xyz_m` display
intervals. Top height filtering removes ceiling clutter; front/side spatial slices
reduce overlap. Gray remains explicit. Labels, dimensions, source endpoints,
camera transforms and scale status retain their original meanings.

Colored sheets (historical or external input; omitted from this bundle)
and invariance validation (historical or external input; omitted from this bundle)
show identical measurement/landmark values and byte-identical dimensions CSV and
camera JSON against the gray run. All three views were inspected. Furniture is
more recognizable, but sparse regions and moving-person fragments remain. Color
and display slicing are not segmentation or evidence of better metric accuracy.

SAM already outputs lower limbs; the old adapter drew arms and compiled hand
constraints only. Added reusable `motion.observations` redraws cached full-body
poses, makes aligned source/overlay crops, and merges explicitly reviewed person
batches with source/camera identity guards. Thirteen additional child frames were
inferred once, alongside three cached frames. Adult cached poses were also
redrawn: legs are out of frame at 100/200. Piano-occluded child legs were excluded
from native guidance. Child crops (historical or external input; omitted from this bundle)
make source visibility and predicted joints directly comparable.

`motion.legs` compiles reviewed body-relative thigh/shin directions into installed
native foot constraints. Pre-generation retargeting preserves baseline root,
smooth-root/heading and global ankle orientation at each key; it does not apply
SAM absolute depth or toe twist. Native masks also carry root height and heading.
The actual three-key FK serialization round trip stayed below 1.1e-6 m. Generated
motion can change at unkeyed times; these are not post-generation pose edits.

## Matched experiments and decision

Both candidates reuse the child baseline's prompt, seed 106, durations
`[2,3,3.008]`, native model and root route. Both use 240 output frames at
30000/1001 fps, with rotations resampled before skinning. Scene-scale mesh metrics
use child stature factor 0.73 and **one common constant floor offset** derived
from the baseline. No per-frame grounding is applied during comparison.

| Experiment | SAM angular error at selected keys, baseline -> candidate | Error at withheld times, baseline -> candidate | Frames penetrating shared floor by >5 mm |
| --- | --- | --- | --- |
| Three feet: right 20, right 180, left 220 | 18.60 -> 5.51 degrees | 16.75 -> 16.87 degrees (14 leg events) | 0 -> 3 |
| One swing foot: right 180 | 22.42 -> 4.31 degrees | 18.09 -> 17.92 degrees (18 leg events) | 0 -> 0 |

Withheld sets exclude every leg at a keyed source time, so the two rows use
different withheld sets and are compared to their own baseline. Errors measure
agreement with single-image SAM directions, not ground-truth accuracy. Nearby
samples are correlated and this is one scene, not a statistical benchmark.

The smaller experiment removes the three-key variant's penetration, but it still
has two frames with the whole body >5 cm above the shared floor. Native near-low
ankle/toe horizontal-speed proxy changes from 0.204 m/s to 0.273 m/s (three keys)
or 0.244 m/s (one key). Fixed right-sole near-floor speed changes from 0.220 m/s to
0.322 or 0.289 m/s. Toe roll, true stance and contact are not classified; these are
sliding proxies. Knee/ankle acceleration p95 is 15.75 m/s^2 baseline, 18.16 with
three keys and 16.03 with one key. The three-key renders also show changes in
unconstrained arms/stride phase.

Decision: accept colored references, full-body/crop review and reusable guarded
foot compilation/evaluation; retain the delivered scene's existing generated
people. Neither experiment establishes a whole-clip gait improvement sufficient
for scene replacement. Keep the foot compiler experimental, with sparse visible
poses as evidence rather than automatic hard contacts. Do not label SAM legs
universally unstable from this test: visibility, retargeting, proportions, timing
and generative coupling all affect the result.

Evidence:

- Three-key metrics (historical or external input; omitted from this bundle),
  actual mesh video (historical or external input; omitted from this bundle),
  video decode report (historical or external input; omitted from this bundle).
- Swing-only metrics (historical or external input; omitted from this bundle),
  actual mesh video (historical or external input; omitted from this bundle),
  video decode report (historical or external input; omitted from this bundle).
- Final visual-review and validation evidence is recorded in the task handoff;
  studio previews do not establish scene/furniture contact.

## Reuse and validation

Reusable functions live in `src/aha3d/motion/observations.py` and `legs.py`;
scene selections and experiment recipes stay in the scene workspace. The small
comparison orchestrator accepts candidate run, selection, output name and title.
Existing compatible skinned caches are passed directly to the mesh preview helper,
avoiding repeated skinning. Numerical metrics use `*_metrics.json`; video metadata
uses `*.json` beside the MP4, preventing sidecar filename collisions.

Seven new regressions cover depth-order RGB, scale-aware display slicing without
mutation, person/camera merge guards, camera/PTS/review validation, actual native
foot FK/root/ankle invariants, whole-time withholding, and exposing vertical drops
under a shared floor. Fourteen existing SAM/hand-adapter tests also pass. Actual
cached RGB and SAM execution, two native generations and their skinned comparisons
provide integration evidence beyond the synthetic checks. Jobs, full video checks
and documentation validation are recorded in the handoff.

Correct input was the original raw Pi3X
bundle used by historical SAM inference. Do not weaken provenance guards to make
a later aligned derivative appear interchangeable.

## Project skill audit

The five then-current project skills were read and checked against the implemented behavior.

| Skill | Action and basis |
| --- | --- |
| pi3x-scene-reference | Updated entry point and measurement reference for RGB, depth order, display slicing and invariance |
| sam3d-motion-reference | Updated scope, cached full-body/person review, runtime routing and new experimental leg reference |
| kimodo-body-motion | Updated motion reference for native-foot side effects, matched comparisons and ungrounded sole review |
| indoor-scene-workflow | Updated routing/reuse guidance and linked the actual experiment evidence |
| blender-roomkit | Reviewed; existing source preservation, mesh review and all-person integration rules already apply |

The common staged workflow was updated. No unrelated platform skill, model
checkout, licensed asset, environment or original scene delivery was modified.

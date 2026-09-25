# Human and authored-scene video comparison

The default view compares **source video → retained reconstruction → new candidate**
on one synchronized timeline. Only cases with an explicit `review` are featured.
Prior experiments remain in a collapsed history section. Numerical evidence and
inspection packages are secondary links; they never stand in for a new full video.
A page containing only legacy manifests shows its history without inventing a new
result.

```bash
python tools/human_experiments/build_portal.py \
  --manifest runs/CASE_A/case_manifest.json \
  --manifest runs/CASE_B/case_manifest.json \
  --output runs/COMPARISON/review/index.html
python tools/human_experiments/serve_portal.py \
  --entry runs/COMPARISON/review/index.html --port 8080
```

Each case provides `id`, `title`, `frames`, `fps`, `source_video`, and `variants`.
Each variant requires `id`, `label`, `method`, `status`, and a real `video` path.
Keep a `baseline` ID for raw GVHMR provenance, but select the actual retained
control for the middle panel; it need not be that baseline. All artifact paths in
input manifests are repository-relative. The builder rewrites them for the HTML.

For a featured comparison, add this `review` object (IDs must exist in variants):

```json
{
  "previous_variant": "retained_control",
  "new_variants": ["joint_light", "joint_strong"],
  "default_new_variant": "joint_strong",
  "actor_hint": "Watch the initially distant man who approaches the camera.",
  "verdict": "Not fixed: less furniture penetration, but the body floats.",
  "change": "Both new candidates adjust body placement while retaining pose.",
  "explanation": "The solver tries to improve contact without changing the room.",
  "source_caption": "The target is the man in the background.",
  "previous_caption": "The retained control, with known placement problems.",
  "watch_points": [
    {"frame": 50, "label": "Check foot support", "explanation": "Compare the feet against the floor."}
  ]
}
```

`new_variants` and `previous_variant` must be distinct and cannot reuse the source
or retained-control video path as a new result. Labels and conclusions should be
plain language. Keep solver weights, provenance and numeric limits in secondary
reports. The UI includes synchronized playback, scrubbing, frame steps, speed,
fullscreen and source-frame jump buttons. A confirmed `track_exit_frame` drives
the explanatory exit message; saved/video visibility must be verified separately.

Use the same authored room, readable camera, cadence and duration for previous/new
videos. Disclose appearance differences. Reopen saved scenes, check all active
meshes and visibility, fully decode every newly rendered video, and inspect source
and actual-room frames. A rejected candidate may be rendered in full when requested
for diagnosis; it stays rejected and is not selected as an accepted motion result.
The default numerical pre-render policy is unchanged by such an explicit request.

For execution use [the resumable runner](RUNNER.md), [automation](../../docs/HUMAN_AUTOMATION.md)
and [the script/GPT-6 responsibility guide](../../docs/HUMAN_PIPELINE_GUIDE.md).
The runner does not install models or allocate GPUs. Private frozen reconstruction
inputs must exist; their absence is not repaired by substituting another actor.

## Secondary inspection bundles

`python -m aha3d.workflow.human_inspection --config CONFIG --output NEW_DIR`
builds source-bound numerical evidence and `decision.json`. Use
`render_inspection.py` inside background Blender for sparse actual-room views,
then pass its receipt via `--room-preview` to a new package. Sparse images alone
do not satisfy a request for a complete new comparison video.

An evidence entry can link a package:

```json
{
  "label": "Numerical checks and worst-frame evidence",
  "report": "runs/EXPERIMENT/inspection/index.html",
  "bundle": "runs/EXPERIMENT/inspection/bundle_manifest.json"
}
```

The builder and server validate exact bundle hashes and local paths. The server
binds127.0.0.1 and exposes only declared artifacts, supports byte ranges, and rejects
unlisted files/traversal/symlinks. Restart after rebuilding to refresh the allowlist,
and wait for HTTP readiness before browser checks. Keep the service-log claim
active. Source videos retain attribution; local runs are excluded from distribution.

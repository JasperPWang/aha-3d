# Scene results and batch demos

New selection and promotion use [workflow acceptance](WORKFLOW_ACCEPTANCE.md).
Registration remains available for inventory/candidates. A new selected delivery
must name its persisted task and exact candidate revision; artifacts **and evidence**
are revalidated under the selection/task locks. Historical selections remain
readable as `historical_unverified` and are not certified by being read or rebuilt.


Status: adopted September 13, 2026. See [coordination](COORDINATION.md) and
[runtime policy](../MACHINE.md). Use the configured core Python through
`bash tools/indoor results`, or Python 3.10+ with `tools/scene_results.py`.

For a previously completed, directly reviewed targeted correction where SHA-256
checks are prohibited, `results select-correction SCENE CORRECTION_ID` reads the
existing `deliveries/SCENE/corrections/CORRECTION_ID.json`. It requires the exact
scene and video files, recorded file sizes, nonempty evidence, direct visual
review, full video decode/timing reports, and saved camera checks. The selection
records file size and modification time for each artifact and evidence file. Any
later change invalidates the pointer. Gallery labels this selection
`targeted_correction_verified`; it does not certify the entire room. The
correction record and reports must exist before selection.

Build this view with `results build --no-sha --posters`, then run `results check`
without `--verify`. This mode does not hash files. Selected demos retain their
recorded selection; derived demo exports are labelled unverified because exporter
hashes are not recomputed. The normal `results select` and `--verify` modes retain their
existing acceptance rules for other tasks.

## Layout and authority

```text
scenes/SCENE/{scene.json,STATE.md,blender/,recipes/}
runs/SCENE/RUN_ID/{run.json,snapshot/,stages/,logs/}
runs/_tools/TOOL/RUN_ID/                cross-scene checks
runs/_batches/BATCH_ID/                 fixed plan, outcomes and logs
deliveries/SCENE/versions/ID.json       immutable artifact/evidence manifest
deliveries/SCENE/selected.json          atomic current selection
gallery/{index.json,index.html}        generated local views
tasks/TASK/                            writer ownership and handoff
```

New pipeline runs already follow the scene/run layout. For standalone work use
`results new-run SCENE --purpose render --owner SESSION_ID`. It creates a unique
timestamp/purpose/short-ID run and an active task claim. Keep the claim while any
queued/running process can write. Release through `tools/task_claim.py` after
writers stop and the handoff is complete. Agent identity belongs in metadata.

Do not move active outputs, edit frozen snapshots or recreate retired paths.
Existing ad hoc directories remain discoverable beneath their scene. New
cross-scene tools use `_tools`; historical roots need no bulk relocation.

## Register and select deliveries

Claim `deliveries/SCENE` before writing. Prepare a manifest in a claimed task path:

```json
{
  "schema_version": 1,
  "scene": "my_scene",
  "id": "material-v3",
  "status": "recorded_delivery",
  "artifacts": [
    {"role": "scene", "path": "runs/my_scene/run-v3/room.blend"},
    {"role": "material", "path": "runs/my_scene/run-v3/material.mp4"},
    {"role": "whitebox", "path": "runs/my_scene/run-v3/whitebox.mp4"},
    {"role": "comparison", "path": "runs/my_scene/run-v3/comparison.mp4"}
  ],
  "evidence": [
    {"path": "runs/my_scene/run-v3/video_validation.json"},
    {"path": "runs/my_scene/run-v3/visual_review.json"}
  ],
  "review": {"by": "SESSION_ID", "note": "Concrete reviewed scope and limitations."},
  "validation_scope": "Recorded full decode and representative review; see evidence."
}
```

Locally:

```bash
bash tools/indoor results register tasks/TASK/delivery.json
bash tools/indoor results select my_scene material-v3
```

Registration hashes artifacts/evidence, rejects missing files and leaves sources
untouched. Version IDs cannot be overwritten. Selection rechecks artifact hashes
and atomically updates the pointer using the existing pipeline's selection lock.
Keep one default `scene` artifact; additional Blender variants need
`"default": false` and a distinct `variant`. Role/variant pairs must be unique.
Optional roles: `thumbnail`, `demo`, `reference`, `render`, `generated_video`.

`candidate` records cannot be selected. `recorded_delivery` means the registering
agent checked and attributed existing delivery evidence. Registration does not
perform visual review, decoding, physical validation or new user acceptance.
Preserve these scopes explicitly. Import clearly selected historical outputs
from STATE and actual evidence; keep rejected, superseded or ambiguous candidates
unselected. Old `indoor promote` records work through a read-only adapter that
checks recorded status, review and output hashes. Readers never parse prose or
filenames to guess the final version. New records use project-relative paths;
external sibling-project media are not traversed or served automatically.

Optional `deliveries/SCENE/context.json` holds a display title, kind and
`selection_note` explaining why a scene remains unselected. It is local migration
context and cannot select a source or establish validation.

## Browse and verify

Claim `gallery` before building. Scans, hashes and poster generation run locally:

```bash
bash tools/indoor results inventory --out tasks/TASK/inventory.json
bash tools/indoor results build --verify --posters
bash tools/indoor results check --verify
bash tools/indoor results serve --port 8767
```

Open `http://127.0.0.1:8767/gallery/index.html` in a browser on the same machine
(WSL2 forwards localhost to Windows). For a remote workstation, forward the port
with SSH. The loopback server serves only indexed files;
restart it after adding indexed paths. The HTML embeds its JSON and also works
as a local file if the browser can access the media filesystem.

All scene directories appear, including those missing scene.json. Current
artifacts, video playback, Blender/demo links, evidence, version records and
expandable candidates share one index. Frozen copies, input references, caches
and frame sequences are excluded from candidate discovery. File presence is not
acceptance. Default builds compare recorded size/mtime; `--verify` hashes selected
and managed-demo artifacts. Integrity checks and single-frame navigation posters
do not establish new scene validation. The index is a timestamped snapshot;
rebuild after changes. One lock protects explicit index rebuilding.

Add `--web-previews` to build 640px VP9/Opus WebM navigation copies for browsers
without H.264 support. These stay under `gallery/previews`, preserve frame count
and timing, and carry source/output fingerprints plus full-decode checks. The UI
labels fallback playback as a browsing preview and keeps the original video link.
Later builds reuse matching cached copies; source or encoding changes invalidate
them. Encoding runs locally and does not modify original renders.

The tracked asset/tool/reference catalog stays portable. Generated Gallery pages,
posters, delivery versions and run data stay ignored and local. Publish only
the generator, documentation and tests.

## Unregister rejected scene work

When the user requests removal of newly created rejected scenes, first stop their
queued/running writers and retain the exact candidate/evidence paths. Archive only
the task-owned `scenes/SCENE` directories under the claimed task archive, recording
each source-to-archive mapping. Preserve source videos and run evidence. For scenes
with no delivery records, removing these scene directories removes their Gallery
registration on the next build; this is not deletion of the reconstruction data.
If delivery records or selections exist, inspect them separately and archive only
the rejected task's records under an explicit claim. Preserve unrelated selected
deliveries and historical scenes. Rebuild and check the claimed Gallery, then verify
the removed IDs are absent from its index. A running Gallery server caches its
allowlist at startup: if it indexed removed candidate paths, coordinate a restart
with the service owner and verify those URLs are no longer served. If they were
never indexed, verify their rejection without disturbing that service. Record
rejection rather than completion in archived scene state and the batch outcome.

Asset collection is a separate quality decision. A rejected room does not establish
that any component is reusable. Collect only complete objects with reviewed shape,
materials/dependencies, support and actual orientation; follow the asset export
contract and validate the exported/reimported asset. Existing library imports are
not new salvage. Record zero collected assets when none meet that standard.

## Incremental demo batches

The wrapper calls the maintained [browser exporter](../tools/roomkit_browser/README.md).
It does not generate motion or repair scene semantics. Plan locally;
repeat `--scene SCENE` to restrict the list:

```bash
bash tools/indoor results demo-plan --out tasks/TASK/demo-plan.json
bash tools/indoor results demo-batch tasks/TASK/demo-plan.json \
  --owner SESSION_ID --submit
```

Plans pin each selected Blender hash, exporter files, dependency lockfile,
Blender executable identity, Node/Python identity and export options. `--tabletop`
explicitly enables tabletop export. Standalone historical demos remain browsable
but cannot silently become cache hits without managed provenance. Reuse requires
matching inputs/tools/runtime/options and intact HTML. Each row is `build`,
`skip` or `blocked` with a reason; invalid scenes block only their own rows.

Batch creation claims its new batch and scene-output paths automatically.
`--submit` starts a detached local background worker that runs the exports one at
a time and records its pid, logs and exit codes in the batch folder. Without
`--submit`, creation retains the claim and prints a path for
`results demo-execute BATCH`, which runs in the foreground.

Each result lives in `runs/SCENE/RUN_ID/stages/demo/`, with a wrapper run.json,
pinned request and logs. Input and exporter/runtime identity are checked before
and after export. Browser QA must pass and identify the exact source hash.
Visual review starts as `pending`; inspect orbit/plan/mobile screenshots before
claiming visual quality. Workers write individual run records; they do not
concurrently update Gallery or replace selected source pointers.

Failures preserve logs and allow independent rows to finish. `batch.json` records
row outcomes; `submission.json` establishes submission only. Claims release as
completed/handoff after all writers stop. Killed jobs retain claims and locks
for scheduler-aware recovery. Confirm old writers stopped before retrying:

```bash
bash tools/indoor results demo-plan --retry runs/_batches/BATCH/batch.json \
  --out tasks/TASK/retry-plan.json
bash tools/indoor results demo-batch tasks/TASK/retry-plan.json \
  --owner SESSION_ID --submit
bash tools/indoor results build --verify --posters
```

Retries use new output paths. Gallery marks managed demos stale on source/exporter
changes; planning additionally checks runtime/options and hashes before reuse.

### Fast demo dependencies

New demo batches link `demo-fast.html`, retain `demo.html` as `demo_offline`, and
fingerprint every `demo_resource` from the fast manifest. Gallery hides internal
resources from the card actions but includes them in the HTTP allowlist and
integrity checks. Batch reuse requires all recorded artifacts to be intact.
Delivery manifests may also register these roles; use a unique variant for each
resource. Keep the offline link when replacing an existing selected demo with a
fast entry. Rebuild the Gallery and restart its allowlisted server after adding
new paths. Source scenes and historical deliveries remain unchanged.

When Gallery itself is opened via `file://`, Open demo uses the offline artifact.
HTTP Gallery uses the fast entry. This preserves local double-click browsing;
progressive network loading requires serving the Gallery over HTTP.

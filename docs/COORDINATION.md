# Agent coordination protocol

Status: accepted for this project on 2026-09-08. Scope: agents and human editors
using the same shared checkout on one workstation. See [Decision 0001](decisions/0001-shared-documentation.md).

Code development and task-end publication use the fixed checkout described in
[Git workflow](GIT_WORKFLOW.md). Directory claims still coordinate concurrent
writers; they do not require a separate publication copy or repeated user approval.

## Reading and ownership

Read `AGENTS.md`, `docs/INDEX.md`, relevant scene state and your task handoff at
the start. Before integration or delivery, refresh relevant dependencies that
changed or whose current state is needed for acceptance; do not reread unchanged
instructions already available in the task context.
Existing sessions must explicitly read updated documents; a file update does
not push new context into another agent's conversation.

Task claims coordinate writes among cooperating agents. Read-only investigation
needs no claim. Use a unique session owner such as `camera-20260908-a`, not just
the shared OS username. Claim exact files or directory subtrees, including paths
that do not exist yet. A directory claim includes its descendants. Parent/child
claims conflict, as do paths resolving through a symlink to the same location.
Do not retarget symlinks while their paths are claimed. Hard-link aliases are
not detected: use one canonical path for shared files. The helper also resolves
retired paths through `configs/path_migrations.json`, so an older task's handoff
cannot bypass ownership of its relocated scene directory. Use canonical paths
for new work; do not recreate retired root-level directories.

Each scene has a designated state editor while a task owns its `STATE.md`. Other
agents keep their results in their own task handoffs until integration. Use
separate output `.blend` files for parallel scene work and one writer for the
combined scene. Before starting a new task, also inspect any existing unregistered
jobs/output activity; work started before this protocol may have no claim.

## Commands

Registry inspection, claims and handoffs use Python's standard library and run
without Blender or model weights. Reconstruction completion loads the acceptance
validators and runs in the configured environment.
Paths are relative
to the project root even when the command runs from another directory.

```bash
python3 tools/task_claim.py list --compact
python3 tools/task_claim.py claim g0070-camera-a \
  --owner camera-20260908-a --scene minimal_living_g0070 \
  --title 'Refine the camera in a separate scene copy' \
  --paths scenes/minimal_living_g0070/blender/camera_candidate_a
python3 tools/task_claim.py checkpoint g0070-camera-a \
  --owner camera-20260908-a --note 'Preview submitted; see HANDOFF.md for logs' \
  --job-id 123456
python3 tools/task_claim.py show g0070-camera-a
```

The job ID above is an illustrative placeholder. Record the actual batch
`job_id` or process ID in real work. `--depends-on TASK_ID ...` on `claim` requires those tasks to be completed.
This is a readiness check, not a job scheduler. Claim only the new outputs and
shared files you actually need to change. The task's own directory is claimed
automatically. A conflict reports the existing task and owner; continue work on
independent paths or arrange a handoff within the already authorized scope.

A claim with `--scene` defaults to `--kind reconstruction`. Initialize and bind
its [acceptance scope](WORKFLOW_ACCEPTANCE.md#declare-scope-before-downstream-work)
after claiming and before downstream work. The acceptance task ID defaults to the
claim ID; use `--acceptance-task EXISTING_TASK` at claim time when resuming an
existing scope under a new writer claim. Completion cannot borrow a different
task's accepted scene. Use `--kind preparation` for an
independent upstream stage (such as reference extraction), or `--kind code` /
`documentation` for maintenance that has no scene-delivery objective. Choose this
from the user's scope at intake, not to bypass an unfinished reconstruction.
The kind cannot be changed by checkpoint/resume/release.

Releasing a reconstruction claim as `completed` performs full acceptance and exact
selected-delivery validation locally, independently of Codex hook trust. Missing
scope, stale evidence or an unselected candidate leaves the claim active. Use
`handoff`/`blocked`/`cancelled` for unfinished work after writers stop. Existing scene
claims without a kind are treated as reconstruction. `list --compact` omits history
and cache-cleanup paths; use `show TASK` for full ownership and job details.

The helper writes ownership/status/history in `tasks/<id>/task.json` and creates
`HANDOFF.md` from the template. Update `task.json` through the helper; edit the
handoff as the task owner. Use `checkpoint` after meaningful changes, recording
evidence and next steps in the handoff. Avoid saving conversation transcripts.

After writing a handoff and confirming no jobs/processes still write the paths:

```bash
python3 tools/task_claim.py release g0070-camera-a \
  --owner camera-20260908-a --status handoff \
  --note 'Camera candidate and checks are documented in HANDOFF.md; writers stopped'
python3 tools/task_claim.py resume g0070-camera-a \
  --owner integration-20260908-b --note 'Read handoff; taking over integration'
```

Use `--status completed` only when the task objective is fulfilled with evidence.
Use `handoff` for continuation, `blocked` when awaiting a dependency or input, and
`cancelled` when abandoned. Release frees all claimed paths. Keep a claim active
while a queued/running job may write them, even when ending the interactive turn.
Record enough job/log information for a maintainer to take over safely.
Completed/cancelled IDs are historical records; use a new ID for new work.
`list --all` includes released tasks. Resuming rechecks path conflicts.

## Evidence and document authority

Follow [scene result management](RESULTS.md) for run allocation and closeout.
Each worker owns its run; claim the scene's delivery records for registration
and selection. A single claimed Gallery builder aggregates those records after
workers finish. Batch demo workers write individual run manifests and never
race to replace the global index. Historical artifact discovery is not selection.

Keep policy in the authoritative document named by [the index](INDEX.md); skills
link to it instead of copying procedures. Load only the current stage's references.
After changing a policy, remove conflicting wording from its entrypoints in the
same change. At resume, refresh changed relevant guidance and task state; a file
update alone cannot refresh an already-running conversation. Write new project
documentation and filenames in English.

User instructions govern the task. Project decisions record accepted choices
with their source; proposals, observations and historical handoffs do not silently
change policy. Mark recommendations awaiting adoption explicitly.

Link status claims to actual run reports and artifacts. For videos, require the
requested frame count, duration, full decoding and representative visual review.
Track automated validation and visual review separately. A submitted job, a file's
existence or a README's claim is insufficient to establish completion.

Put reusable findings in `docs/lessons/` with the exact scene/run and limits of
generalization. Before changing operating guidance, review those findings and
update the appropriate skill reference or decision. Keep current state concise;
retain task history and mark superseded decisions with replacement links.

## Concurrency and recovery

The helper serializes registry operations with atomic directory creation at
`tasks/.registry.lock`, and replaces JSON files atomically. Two cooperating
processes cannot both win overlapping claims through this helper. This is not
filesystem access control and does not lock arbitrary editor or Blender writes.
All participants must follow the protocol in this same checkout.

Full reconstruction completion validation runs outside the global registry lock;
the helper rechecks the unchanged claim before releasing it. Other registry
operations normally last milliseconds. It waits at most five seconds
for a held lock, then reports an error. The lock's `owner.json` identifies its
host, PID and creation time. Locks and task claims never expire automatically.

If interrupted, inspect the lock owner on its recorded host and any associated
writer processes/jobs. A maintainer may remove an abandoned registry lock only
after establishing that its process cannot still be running; preserve its metadata
in a recovery note first. Do not remove a lock merely because it looks old.
An incomplete/corrupt task record blocks further registry operations until a
maintainer inspects and repairs or archives it. Preserve evidence outside the
registry's task directories, for example under `docs/history/`.

An abandoned active task requires the same writer/job check. Because owner IDs
are cooperative labels, a maintainer can release it using the recorded owner ID
and an explicit recovery note, then resume under a new owner. This must describe
who performed recovery; it is not proof that the original owner authorized it.
Do not kill or alter unrelated processes or batch workers as part of registry recovery.

If a shell tool yields a running session ID, the command has not completed.
Require its final exit status before dependent edits, submissions, release/resume
operations or completion claims. Follow [job waiting](RENDER_EXECUTION.md).
Record a compact stage checkpoint in the handoff
before ending or transferring work: selected variant, evidence paths, active job
IDs/logs and next action. Keep earlier failed/pending checkpoints visibly historical
so recovery does not mistake them for the current delivery state.

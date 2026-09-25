# Job waiting and completed-result review

Applies to render, inference and review jobs. Prefer scripted waiting and
infrequent assistant checks; continue authorized work through validation and delivery.

## Launch and wait

Complete the [required preview](SCENE_WORKFLOW.md#submission-preflight-and-full-clip-preview-acceptance)
before a long render and freeze the reviewed scene/configuration. Record the
batch folder (`runs/batches/<id>/`), worker pid or session handle, output/log
paths, expected runtime or deadline, waiting mechanism and next action in the
task handoff. Run one GPU job at a time; do not start another GPU stage beside
an active batch.

- Prefer one script or existing runner through ready stages: render, encode,
  decode and report. Preserve failure propagation and required visual-review gates.
- Prefer process waits or completion events. A background batch has finished
  when its worker pid is gone (`bash tools/indoor status --live`) and every task
  has a `<i>.log.exit` file. If queries are needed, keep them in one bounded
  script that returns a compact completion, failure or deadline summary rather
  than waking the assistant for unchanged progress.
- Otherwise, check at low frequency: about 5 minutes initially, backing off
  toward 15 minutes for unchanged long jobs. Adjust to expected runtime;
  short jobs, failures and user status requests can justify earlier checks.
  Avoid alternating sleeps, log tails and frame counts for the same state.
- Reuse the original session handle within tool wait/responsiveness limits.
  A tool timeout may require another wait, not another status/log query.
  Missing notifications or timeouts alone are not reasons to stop the task.

Continue independent work while waiting. At the deadline, diagnose before
extending or reporting a blocker; elapsed time alone does not prove failure.
If continuation is genuinely unavailable, record the blocker and exact resume
action. Keep [output claims](COORDINATION.md) while writers remain active.

## Continue after completion

Read exit codes (`<i>.log.exit`, `batch.log`) and stage reports together; a
worker pid that is no longer alive does not establish success. Perform the required frame/timing, full decoding, saved-scene,
camera and visual checks under the [scene workflow](SCENE_WORKFLOW.md), then
complete [acceptance and delivery](WORKFLOW_ACCEPTANCE.md).

Use the existing [pipeline recovery](PIPELINE.md) and evidence rules. Preserve
valid frames when only encoding or reporting fails; retry the failed stage
without rerendering unchanged accepted inputs. Generated files and successful
exits do not replace required review.

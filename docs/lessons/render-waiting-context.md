# Rendering waits and repeated context

Date: 2026-09-14. Scope: enforcing the existing September 12 render execution
preference after the fireplace reconstruction audit. This is a documentation and
agent-routing correction, not a new scheduler or a measured runtime speedup.

## Observed failure

Scene: `fireplace_open_plan_g0060`.
Run: `20260914t234316z-reconstruction-67b158d6`.
Private evidence: `scenes/fireplace_open_plan_g0060/reports/20260915-execution-audit/`
(`operations.json`, `token_requests.csv`, `token_summary.json`). These local
artifacts are excluded from the source distribution.

The original task repeatedly alternated short sleeps with render/inspection log
tails during normal progress. Its audit records 24 sleep calls across the task.
Some intervening actions performed useful modeling or visual checks; the audit
does not classify every waiting-period request as waste. Smaller log responses
did not prevent repeated requests from carrying the accumulated context.

The rule already existed in `docs/RENDER_EXECUTION.md`. The main scene workflow,
render settings guide and relevant skills did not directly route the agent to
that document. The execution missed the rule; adding another equivalent policy
without fixing these entry points would not address that failure.

## Correction and limits

Link the canonical policy from the documentation index, scene workflow, render
settings and the scene, Blender and runtime skills (the runtime skill was later removed). At render submission, record the
session/job handle, completion mechanism, deadline and next action. The initial
correction allowed repeating bounded waits on the same session. An intermediate
2026-09-16 rule then prohibited all repeated assistant waits following the
waterfront-bedroom task `bedroom_waterfront_g0024`, run
`20260916t175237z-reconstruction-3847cf27`, and the user's concern about token cost.
That blanket ban proved too restrictive: lack of event delivery could cause
agents to stop before finishing authorized work.

The user's subsequent 2026-09-16 correction supersedes that ban with
[scripted waiting and low-frequency fallback](../RENDER_EXECUTION.md). Prefer one
script through ready stages; allow backed-off checks when needed, and continue
validation after completion. Keep the observation about repeated context overhead,
without treating missing notifications as a reason to abandon the task.

This guidance reduces opportunities for unnecessary queries but does not
programmatically prevent an agent from making them. No post-change scene run or
token-saving benchmark is claimed. Verify execution on a future task before
reporting a measured improvement.

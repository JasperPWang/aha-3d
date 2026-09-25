# 0001: Shared documentation and task ownership

- Status: accepted.
- Date: 2026-09-08.
- Scope: project-authored documentation and cooperative work in this shared checkout.
- Owner/author: `docs-root-20260908`, implementing the user's request.
- Acceptance source: the user requested a shared document system and then said
  "lets start this"; the follow-up required all documentation in English.

## Decision

Use a repository-local index, per-scene state, per-task ownership/handoffs,
evidence-backed lessons, separate proposals, and decision records. Use English
for project documentation and document filenames. Retain third-party source,
licensed binaries and original scene/output locations.

Coordinate writable paths through `tools/task_claim.py`. Keep operational
procedures in the existing skills. Read context on demand instead of loading
all scene histories into every task. Define reading and update responsibilities
in [the coordination protocol](../COORDINATION.md).

## Reason and consequences

The earlier handoff combined preferences, an untested Pi3X integration, measured
motion results and runtime history. Splitting those categories makes their scope
and evidence explicit. Per-task documents reduce competing edits to one global
status file; atomic claims detect cooperating writers requesting overlapping paths.

The registry is local to this shared checkout, not an access-control mechanism
or cross-machine synchronization service. Agents must explicitly read updates.
Heavy validation and rendering follow the [runtime policy](../../MACHINE.md).

The broader shared pipeline, asset relocation and code version-control setup
remain future work. This decision does not initialize Git or authorize publishing.

## Evidence and supersession

Implementation and checks: setup task (historical or external input; omitted from this bundle).
Supersedes the single-handoff approach for current coordination; the earlier
handoff snapshot (historical or external input; omitted from this bundle) remains historical evidence.

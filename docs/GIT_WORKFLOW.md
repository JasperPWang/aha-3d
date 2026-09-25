# Git mainline development

Status: adopted on 2026-09-12. GitHub `main` is the shared code mainline.
Develop and execute from the fixed Git checkout. A separate exported publication
copy is no longer the normal development or release path.

## Start a task

Read `AGENTS.md`, this guide and the coordination protocol. Inspect `git status`
and active task claims before editing. Fetch the remote and, when no concurrent
writer or queued/running job can observe a changed checkout, update clean main:

```bash
git fetch origin
git merge --ff-only origin/main
```

Keep unfinished changes. Inspect divergence and integrate it explicitly; do not
reset or clean the directory to make synchronization pass. A fetch alone does
not change working files. Use a separate branch/worktree for concurrent work that
needs a different code revision, and document its data/output ownership.

Do not update a checkout while a running process or background batch still
reads its live code. Pipeline source
snapshots retain their normal immutable-input checks.

## Complete a task

Finish the requested change, review its diff and run appropriate validation.
Commit and push only when the current task or an explicit standing instruction
authorizes those actions. Do not infer publication permission from an ordinary
edit request or this document. Existing authorization needs no repeated approval.
Use the agreed branch; do not choose `main` implicitly. Read-only reviews create
no commits. Without publication authorization, hand off the validated local diff.

When commit and push are authorized, stage only the reviewed task paths, commit,
push to the agreed remote branch and verify its remote commit. A direct
`git push origin HEAD:main` applies only when `main` is the agreed destination.

Use the actual reviewed paths and branch, never blindly stage all shared work.
If the remote advances, fetch and integrate without overwriting anyone's work,
then rerun checks affected by the integration. Report commit and verification
in the task handoff. There is no background auto-commit, auto-pull or file watcher.

## Machine configuration and local data

Tracked code must run with explicit configuration on other machines.
`kimodo_blender/env.sh` loads optional ignored `kimodo_blender/env.local.sh`
before applying portable defaults. Keep installed runtime/cache/model paths in
that local file or the calling environment. Explicit caller values should be
preserved by local defaults (`${VARIABLE:-default}`).

Runtime profiles prefer `configs/runtimes/NAME.local.json`, falling back to the
tracked `NAME.json`. Recipes use `local`, written by `tools/configure_runtime.py`
to ignored `configs/runtimes/local.json`. These files are ignored; do not commit credentials
or machine-specific configuration. See [setup](SETUP.md).

Legacy path aliases can live in ignored `configs/path_migrations.local.json`,
which takes precedence over the portable registry on that machine.

Scenes, generated runs, checkpoints and environments stay in local storage.
Their existing paths can remain inside the checkout under the ignore rules.
Historical files preserved during migration may also be listed in this checkout's
private `.git/info/exclude`; this is an inventory of existing local artifacts,
not a rule to hide new source changes. Reusable assets and selected reference
media retain their explicit tracked entries and attribution.

New pipeline runs record the Git commit/branch and whether the checkout had
uncommitted changes alongside exact source-snapshot hashes. A commit alone does
not describe a dirty working tree; retain the immutable run snapshot and manifest.
The local environment script hash is recorded with runtime identity when present.

## Package and catalog checks

Run `python tools/build_catalog.py build` after changing skills, stages or assets,
then `python tools/verify_package.py`. In a Git checkout the package checker
inspects tracked and nonignored candidate files without traversing model/data
directories. An exported source directory still supports checks without Git.
Private run artifacts are not required to validate a clean clone.

# 0003: Keep scene workspaces and footage together

Status: accepted. Date: 2026-09-08 (local).
Source: the user's request to organize scene folders and videos out of the root.

Use `scenes/<scene-id>/blender/` for each existing Blender workspace and its
historical variants, and `scenes/<scene-id>/references/` for its original videos.
Keep recipes, identity and state alongside them. Unassigned user-supplied videos
live in `references/unassigned/`, with one [catalog](../../references/README.md)
for all inputs; the public source bundles no footage.
New pipeline outputs remain under `runs/<scene-id>/<run-id>/`; portable reusable
assets remain under `assets/`.

Move directories in place; do not rename individual artifacts or rewrite Blender,
video or cache content. Update live scripts, recipes, links and the room-source
symlink. Keep recorded JSON/log provenance and frozen run snapshots unchanged.
The [path map](../../configs/path_migrations.json) lets current path resolution
and task claims interpret retired names without root-level compatibility symlinks.
Historical standalone scripts inside completed task snapshots may still contain
recorded paths; use the current scene recipes for new runs.

This changes organization, not scene quality status.

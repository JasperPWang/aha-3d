# Local scene gallery

Generate with `bash tools/indoor results build --no-sha --posters`. Serve with `bash tools/indoor results serve --port 8767`.
See [result management](../docs/RESULTS.md) for claims, registration, batches and
remote access. Only this README is tracked; generated pages/data remain local.

The Gallery excludes ADT/WorldTrack tracking experiments and the RoomKit variants
tool example. Every room uses a selected-media preview when available, otherwise
source footage or an explicitly labelled candidate preview. Preview images do not
promote candidates or change delivery selection.

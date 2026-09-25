# Reference inputs

Put your own reference videos, images and source annotations here. Nothing is
bundled: this folder is ignored by Git except for this file.

Keep unassigned footage under `references/unassigned/` and record scene
assignments when you create a scene workspace under `scenes/<id>/`. Keep each
source's license and attribution next to the files you add, and follow the
[distribution terms](../DISTRIBUTION.md) before sharing derived outputs.

The catalog can list optional demos from
`references/unassigned/with_humans/manifest.json`
(`{"schema_version":1,"demos":[...]}`); run `python tools/build_catalog.py build`
after adding one. Configuration and usage examples live in
[examples](../examples/README.md).

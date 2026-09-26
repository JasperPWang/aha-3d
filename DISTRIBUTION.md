# Distribution status

This is the public source release of the indoor real2sim pipeline. Project-authored
code, skills and asset libraries are licensed under the
[Apache License 2.0](LICENSE). Third-party files keep their own licenses, noted
below and in [external dependencies](THIRD_PARTY.md).

Project integration code, the project skills,
registered reusable furniture, plants and procedural materials are included.
Previous scene references in asset metadata describe origin; complete generated
scenes and pipeline runs are excluded.

No reference footage, previews or clip listings are included. Footage you add
under `references/` keeps its own license; record its attribution beside it.

Third-party source checkouts, licensed SMPL-X/MHR body assets, checkpoints, text
encoder weights and credentials are excluded. Model files require the recipient's
own authorized upstream access; see [external dependencies](THIRD_PARTY.md).

The owner-authored motion helpers previously kept beside PromptHMR are included
under `tools/gvhmr/world_backend/`; see [their provenance](tools/gvhmr/world_backend/README.md).
Upstream PromptHMR implementation code is not included. A selected subset of official PyTorch3D v0.4.0 rotation utilities is included
with its full BSD license to preserve numerical behavior.

Development and task-end publication follow the fixed-checkout
[Git workflow](docs/GIT_WORKFLOW.md).

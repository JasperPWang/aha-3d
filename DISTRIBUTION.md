# Distribution status

This is the public source release of the indoor real2sim pipeline. No MIT, Apache or other license has been
selected for project-authored code, skills and asset libraries; this snapshot
does not add such a grant.

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

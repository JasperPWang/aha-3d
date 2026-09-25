# Recorded user preferences

Updated: 2026-09-24. Maintained by the owner of the task changing this document.
Current user instructions override earlier preferences. Include source and scope
when recording a new preference; do not turn an agent's suggestion into user policy.

| Preference | Scope and provenance |
| --- | --- |
| Project documentation uses English | Explicit user instruction in the documentation setup conversation, 2026-09-08 |
| Run everything on one local Linux workstation with one NVIDIA GPU | Explicit user instruction, 2026-09-24; [runtime policy](../MACHINE.md) |
| Shared documents and task handoffs for agents | User accepted implementation in the same conversation; [decision](decisions/0001-shared-documentation.md) |
| Approximate generated human actions and paths | Existing [project instructions](../AGENTS.md); no reconstruction of the real person's identity or body motion |
| Keep the successful motion with fewer constraints; retire the first version's external arm IK and keyed facing edits. For required contact, prefer sparse native Kimodo 3D end-effector constraints | Explicit user instruction in the motion-control discussion, 2026-09-08; [current policy and validation limits](MOTION_CONTROLS.md). Native contact control has not been compared against the accepted scene motion |
| Default human motion previews to SMPL-X mesh so facing is readable; skeleton views are optional diagnostics | Explicit user request after the SAM/Kimodo skeleton preview, 2026-09-08 |
| Independent Kimodo environment and one GPU for the full pipeline | Existing [project instructions](../AGENTS.md); exact runtime configuration belongs in [runtime](../kimodo_blender/RUNTIME.md) |
| Start video room/white-model authoring with Pi3X measurements and timestamped cameras; keep one coordinate and scale basis for subsequent camera paths | Explicit user correction during the independent g0070 white-model task, 2026-09-09; [workflow](../.agents/skills/blender-roomkit/references/reconstruction.md#pi3x-first-reference-workflow) |
| Prefer source/action reasoning first, white room and requested camera next, then generated people; reuse reviewed stage outputs and provide a repeatable workflow entry point | Explicit piano-scene follow-up, 2026-09-09; order may adapt for workflow efficiency; [implemented guide](SCENE_WORKFLOW.md) |
| For this g0070 rebuild, do not consult the existing scene implementation | Explicit user instruction in the same task; use a new source-video reconstruction bundle |

The earlier Pi3X pilot proposal (historical or external input; omitted from this bundle) is historical. Pi3X-first
reference preparation is now requested for this room-authoring workflow; this
does not replace Kimodo body generation or authorize camera animation by itself.

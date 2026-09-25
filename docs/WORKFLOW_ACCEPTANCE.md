# Reconstruction acceptance and completion

`workflow.acceptance.evaluate` is the policy for an exact candidate and declared
scope. `indoor acceptance check SCENE TASK` prints a deterministic JSON result:
`status`, task/scene, `candidate_revision`, `required_checks`, stable blocker
`code`s, evidence, next steps and `permitted`. Only `permitted: true` permits
successful reconstruction completion or selection. Run full checks locally.
Inventory, registration, successful subprocess exits, image generation and the
pipeline's internal `validated` state do not accept a task.

## Declare scope before downstream work

Claim the scene, its delivery records and outputs with `tools/task_claim.py`
(`--scene SCENE`, default kind `reconstruction`). Use the claim ID as the acceptance
`task`, or declare `--acceptance-task EXISTING_TASK` on a new claim resuming existing
scope. A completed delivery from another task cannot satisfy this claim.
Create an explicit scope JSON, for example:

```json
{
  "scene": "bedroom", "task": "room-reconstruction", "kind": "reconstruction",
  "reference_reconstruction": true, "source_video": "references/bedroom.mp4",
  "human_motion": false, "render": "video",
  "timing": {"fps": "24", "frames": 240},
  "required_artifacts": ["scene", "render"],
  "subjects": ["bed", "nightstand", "bed-nightstand"], "repair_budget": 3
}
```

`render` is `none`, `stills` or `video`. Human scope additionally declares a
nonempty `people` list of stable person IDs. Code/documentation scopes use
`kind: code` or `documentation` and are not reconstruction acceptance tasks.

```bash
# New scope (initialization fingerprints source inputs):
bash tools/indoor acceptance init scope.json --session SESSION_ID
# Existing scope resumed by another Codex task:
bash tools/indoor acceptance bind bedroom room-reconstruction SESSION_ID
```

`init` defaults the session to `CODEX_THREAD_ID` when available. Use `bind` when
resuming from another Codex task. Scope and fingerprints are persisted under
`deliveries/SCENE/acceptance/TASK/`; `scenes/SCENE/task_scope.json` points to it.
A scope cannot be overwritten or silently replaced with a weaker task. Resume
existing work in its scope, retaining findings. New task handoffs for the same
scene require explicit coordination of the scene pointer and previous state;
there is no command to silently waive the old scope or findings.

Standalone GVHMR consumer manifests must include `task_scope`, a path to that
`scope.json`. Omitting `source_video` no longer opts out of layout review.
New pipeline runs freeze workflow policy and scope references into their existing
immutable source snapshot. Motion-only preparation remains independent.

## Candidates and evidence

`acceptance candidate SCENE TASK candidate.json` registers an immutable revision.
Its JSON contains:

- `context`: paths for `room_scene`, `final_scene`, `cameras`, `configuration`,
  and `source_video` for reference work. For pipeline runs, configuration is the
  frozen `snapshot/recipe.json`. Static room and assembled scene are distinct.
- `artifacts`: the exact final role/path list. `scene` must match `final_scene`.
- `purpose: delivery` and `completeness: complete` for deliverable work. Defaults
  are an unaccepted candidate and partial work. Diagnostic candidates stay so.
- `layout`: existing `spec` and `evidence_dir` for `layout_gate`. Identical static
  room evidence can be reused when only human inputs change.
- Optional `run`: the existing immutable pipeline run to revalidate.
- `final_views`: a JSON path containing `input_binding` (the context SHA-256 map)
  and `images` (view ID to image path). Image paths resolve from this JSON.
  These must describe actual final-scene views produced by the renderer, with
  their scene/camera/configuration provenance; do not invent a render receipt.

Final visual coverage includes `plan`, `front`, `side`. Reference work and
rendered deliveries also require `early`, `middle`, `late`. Reference work adds
`source_early`, `source_middle`, `source_late`. Keep source timing, actual view
provenance, unknown areas and mask limitations. These names label declared
coverage, not a proof that the depicted objects are correct.

Partial room snapshots can be registered for layout prerequisites before final
assembly exists. Register a new revision with the assembled output before its
alignment, preview and final checks. Room-only scopes do not require alignment.

The existing layout generator validates common-frame inputs and exact native
RGB/cameras, then leaves evidence awaiting visual review. It never accepts layout
by collision score or uncalibrated IoU. Generate a concrete review request and
supply the actual images:

```bash
bash tools/indoor acceptance layout-request layout-spec.json layout-evidence --out layout-request.json
bash tools/indoor acceptance review-images layout-request.json --out layout-judgment.json
bash tools/indoor review-layout RUN --reviewer REVIEWER --notes 'Concrete summary' \
  --verdict accepted --views top front side source_000000 source_000005 source_000010 \
  --visual-review layout-judgment.json
```

Use the actual evidence view IDs, not the illustrative indices above. The
reviewer adapter invokes the installed `codex exec --image` interface with every
image attached and a bounded timeout. It uses a read-only reviewer session and
retains rejected judgments. Tests mock this call; a real model review is not part
of CPU validation. The request contains `candidate_revision`, `images`, `coverage`
and `subjects`. Final requests use the immutable candidate revision and exact
final view images. Review records contain observations for inventory, placement,
dimensions, orientation, relationships and uncertainty, all with subject and view
IDs, plus explicit findings, uncertainties and unreviewed areas. Alignment also
requires `human_alignment` observations covering every declared person.

Image delivery is necessary for this adapter, but neither an attachment receipt
nor its hash establishes that the reviewer exercised correct judgment. A path,
HTML-open operation or `viewed: true` is insufficient. If the reviewer fails,
returns malformed output, or cannot inspect the images, the check stays blocked.
The old free-text `indoor review` remains a historical annotation; it cannot
satisfy task acceptance or promotion.

Preview rendering defaults to 5 FPS with source endpoints and an explicit sampled-frame
mapping; 1 FPS is available for coarse inspection and `--preview-fps source` for
explicit every-frame review. See the [preview workflow](SCENE_WORKFLOW.md#submission-preflight-and-full-clip-preview-acceptance).
Sampled preview approval describes its temporal limits. It never substitutes for
full final-video decoding, original delivery timing or final artifact review.

## Record checks and durable findings

```bash
bash tools/indoor acceptance record-check SCENE TASK REVISION technical report.json
bash tools/indoor acceptance check SCENE TASK
```

Check reports use `policy: 1`, `candidate_revision`, `status: passed`, a
fingerprinted `validator` and nonempty fingerprinted `evidence`. Fingerprints
are `{path, sha256}`. Required checks derive from scope, not report omission:
layout for reference work; alignment for people; preview for rendered work;
technical checks and final review for completion. `technical` covers the exact
candidate `artifacts` including roles and fingerprints; video requires actual
full-decode/timing evidence in `video_validation` fingerprint records (the existing
video validator schema: `full_decode_pass`, `sha256`, `decoded_frames`, `fps`,
`decoder_duration_seconds`). These must match the persisted requested timing and
every final render/comparison video, not just a top-level boolean. Visual reports include the
exact `images` and structured `review`. Alignment binds both `room_sha256` and
`scene_sha256`, enumerates `people`, and records `all_people_reviewed`. A pipeline
preview must also pass the existing full-clip `preview_gate`; the generic receipt
cannot bypass it. Validator versions, reports, subordinate evidence and supplied
images are revalidated. These are adapters for real validation results, not a
command that fabricates a pass from an exit code.

Report a user mismatch immediately with `acceptance finding SCENE TASK issue.json`.
The JSON requires stable `id`, `origin` (`user`, `reviewer`, `validator`),
`severity`, `affected_ids`, `views`, `originating_revision`, concrete `observation`
and `resolution_needed`. User mismatches must be blocking. Review reports can
carry findings with the same fields; recording them persists the findings in the
task ledger. New inspections, revisions and check replacements never close them.
The initial user message must still be correctly translated into this ledger;
there is no language classifier that can reliably discover all mismatches.

`acceptance resolve SCENE TASK resolution.json --id FINDING_ID` requires a current
revision, `disposition` (`corrected` or `false_positive`), specific `rationale`,
a structured image review path, and images keyed `before:VIEW`/`after:VIEW` from
the originating and corrected candidates. Corrections require a new revision.
False positives require explicit rationale and actual verification. There is no
waive, downgrade or delete command. Closure is revision-bound; later revisions
must demonstrate continued resolution. Findings and closure history remain.

## Boundaries and publication

Final people integration requires current room layout when reference scope applies.
Full rendering adds applicable alignment and preview checks. Explicit diagnostic
rendering and independent upstream motion work remain possible and unaccepted.
CLI results distinguish submitted, running, awaiting_review, blocked, failed and
accepted; the run manifest retains technical stage statuses for resume compatibility.

`results register` can record unaccepted candidates. New selection needs an
`acceptance` reference `{task, candidate_revision}` in the delivery manifest.
`results select` and `promote` run the same complete policy under the existing
selection lock plus the task lock and, for pipeline output, the execution lock.
They rehash delivery evidence as well as artifacts and reject evidence changes
between acceptance and selection. Historical selected records remain browseable
as `historical_unverified`; they cannot be newly selected/promoted without explicit
scope and current evidence. No default grandfather bypass exists for new work.

## Task-registry completion gate

`task_claim.py release TASK --status completed` revalidates reconstruction scope,
current evidence and exact selected delivery locally before changing the registry.
This check runs even when Codex hooks are unavailable or untrusted. Claim kind is
recorded at intake: `--scene` defaults to reconstruction; independent upstream
preparation and code/documentation maintenance use their explicit kinds. Those
kinds do not certify a reconstructed scene. A missing scope cannot pass completion.

This protects the registry's completion status, not arbitrary assistant text or
shell commands. Scope initialization/binding remains required at intake. Current
user requirements must still be translated into that scope and its findings.

## Codex completion adapter and trust boundary

The project hook configuration is `.codex/hooks.json`. This implementation was
checked against installed Codex CLI **0.154.0** (`hooks` feature enabled, generated
app-server schemas) and the official [hook interface](https://learn.chatgpt.com/docs/hooks).
`Stop` runs independently of a finish tool. The adapter returns `decision: block`
with concrete blockers/next actions while a reconstruction session is incomplete.
`Interrupt` records incomplete state. An accepted candidate must be the current
selected delivery before successful completion is allowed.

Codex requires trust for new/changed hook definitions: review the concrete project
hooks with `/hooks`. A project file alone does not prove that this desktop session
has loaded or trusted it; existing sessions may need a configuration reload/new
session. No daemon is restarted and no hook trust is bypassed by this patch.
`Stop` continuation does **not** retract already displayed assistant text. The
persistent selected delivery and acceptance receipt determine acceptance.

The hook reads the last full validation result and lightweight file-change
tokens; it never launches Blender, models, background batches or hashes large artifacts.
Change tokens only invalidate a previous hash-validated receipt. They cannot create
a pass. Changes require a fresh full check/selection. Filesystem timestamp caching
and arbitrary writers remain limits; preserve task claims and immutable snapshots.

Retries are bounded across turn IDs/restarts. Use
`acceptance state SCENE TASK paused|cancelled|incomplete|failed --reason ...` for
non-successful termination. `active --reason ... --repair-budget N` explicitly
resumes with a new bounded budget. External jobs should be recorded with
`submitted|running --job-id ID`; after verifying termination, `active --job-id ID`
clears pending lifecycle state but grants no acceptance. The pipeline records its
own submitted/running/completed/failed job states. Code/documentation and unbound
conversations are not intercepted. Declare/bind reconstruction scope at intake;
there is no reliable semantic detector for an unregistered conversation.

This is a cooperative enforcement boundary, not an adversarial sandbox. The same
unrestricted OS user can rewrite validators, receipts, hooks, scope and selected
records or invoke Blender directly. A hostile-agent boundary needs external file
permissions/controller ownership. Hashes and review structure do not prove visual
truth, and no Blender/GPU/source-fidelity end-to-end certification is implied by
passing the CPU fixture suite.

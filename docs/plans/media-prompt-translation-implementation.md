# Image prompt translation implementation

2026-10-25: image slice qualified for PR #442 on `feat/media-prompt-translation`.
The controller rollout follows review and merge into develop. The parent [translation/dictation plan](prompt-translation-and-dictation.md)
retains the full scope; standalone Video/music translation remains subsequent work.

## Existing execution boundaries

Settings → Generation stores an initially-off, revisioned local translator
preference in the existing Settings table. Images has an Inherit / Translate to
English / Keep original override, optional review and protected names/tokens.
The shared `create_image_run` path includes image actions in Chat/Work and agents;
ordinary conversation, agent goals, speech and lyrics are unaffected.

An unchanged `photo_pipe` Run waits on a container `media_translate` preparation
child through existing RunDependency rows. HTTP performs validation/enqueue only.
The worker uses the existing local provider, managed llama.cpp preparation and
five-minute cancellable, tools-free JSON stream. The media Run cannot claim GPU
resources while preparation is pending. After inference finishes, the existing
owned-runtime eviction protocol makes room for generation. An external local
server remains externally owned and is never stopped or reconfigured.

Quoted text (including multiline image text), numbers, model tokens, weights and
explicit protected names receive source-bound placeholders. Output must preserve
every placeholder exactly once in its original field and introduce no new fields;
invalid/truncated/filter-ended output fails. This is a mechanical fidelity guard,
not a claim that semantic translation is infallible. The system instruction
requires faithful translation, unchanged already-English text and preserved
identity/reference roles. Only descriptive fields can change; source images,
model/backend, dimensions, seed, CFG and GPU selection retain their saved values.

The original Task/message remains intact. A verified JSON Artifact records
original/effective fields, translator policy and actual managed runtime/load
identity. Managed source observations and GPU/context/cache presets are preserved;
an external local server's unreported weights revision stays unknown. The output
image retains receipt metadata and lineage. Library displays/copies the original
prompt and exposes the effective prompt separately.

## Review, retry, Stop and recovery

Optional review parks a separate `media_translation_apply` Run under the ordinary
Approval model. The translator has already finished and holds no active inference
reference. Editing/review binds to the current candidate hash; approving cannot
change sources, permissions or execution parameters, and does not reload an LLM.
The apply worker rechecks the source, candidate Artifact and approved text before
unblocking the media Run. The original media parameters change only after this
checked application.

The existing image retry endpoint accepts an optional translation choice:
`reuse` (default), `retry`, or `original`, plus a request UUID. Acknowledgement
retries return the same child. An ordinary retry reuses the frozen effective text;
an explicit retranslation uses the frozen translator policy, even if station
defaults changed. Use original records an explicit bypass and drops obsolete
translation-proof links. An unavailable receipt cannot be silently reused.

Stop cancels only verified preparation/review children. A translation-created
model startup is canceled only after its last consumer stops; independent operator
startups and shared consumers remain protected. In-flight streaming closes before
terminal cancellation is published. Task-wide Stop reuses the existing task lock.
Stale preparation is interrupted under shared conservative recovery and never
blindly rerun; generation remains blocked until explicit recovery.

The native Runner API, filesystem roots, external runtimes and database schema
are unchanged. No model download, cloud call, arbitrary URL/command, new service
or broad permission is introduced. The first translator picker is local-only;
external translation would require a separate explicit provider/permission path.

## Qualification

Current focused checks cover source-bound tokens/quoted text, default-off and
overrides, immutable inputs/settings, negative prompts, Edit/Recompose order,
review/edit, failed and missing-proof recovery, same-request retries, Stop/Task
Stop, shared versus independent model startup, stale leases and stream closure.
Compiled desktop/mobile API/worker flows with fake LLM and an owned CPU photo
fixture have passed; those do not constitute real model/GPU acceptance.

Frozen executable head `6638c27dc4ce2326a478bceea29becfd10cf4ad0` passed all
4,038 collected normal Python cases (4,029 passed, nine explicit opt-in skips),
Ruff check/format, 836 frontend tests, format/lint/types/build and six QA exporter
checks. Exact Docker backend/compiled assets, normal/dev/private-LAN Compose and
isolated non-root API/worker/SQLite/SSE/reopen checks passed. Final compiled
1440px/390px review/edit/approve/image-output flows passed with fake LLM and an
owned CPU photo fixture; screenshots were inspected.

Actual installed Qwen3.5 9B Q6_K, managed llama.cpp on both discovered GPUs with
8,192 context, translated a Polish scene before LUSTIFY Q4 generation. The ordinary
Task graph loaded the translator, completed text preparation, stopped the idle
owned LLM and generated the image with GPU-only weights. A second Run used the
unchanged Polish prompt with identical 768×1024, eight steps, CFG 1 and seed 42.
Both completed and retained checked images. Both visibly depict the requested
red bicycle, blue chair and two yellow flowers without people; composition differs.
This verifies this translation/handoff profile, not a universal quality improvement.
The isolated test database did not change preview settings or model presets;
owned test processes, runtimes and resource reservations were released.

Evidence: `data/acceptance/media-prompt-translation-20261025`, including
`real-model-pair-result.json`, retained on/off PNGs, compiled browser results,
complete local gates and reviewed image identity. An initial acceptance harness
path exceeded the private Unix socket limit and was retained as a failed attempt;
the corrected isolated shorter data root passed without relaxing production checks.
The final operator QA catalog includes nine translation cases (146 total).

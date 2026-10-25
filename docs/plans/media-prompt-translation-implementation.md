# Image prompt translation implementation

2026-10-25: implementation in qualification on `feat/media-prompt-translation`.
Not merged or deployed. The parent [translation/dictation plan](prompt-translation-and-dictation.md)
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

Before release: complete the frozen-source repository gates, inspect the full
diff, qualify actual installed translator/image execution with identical-seed
translation on/off comparisons, review results and then merge/deploy to develop.
Preserve the current operator model preset and never stop external services.
Evidence belongs in `data/acceptance/media-prompt-translation-20261025`.

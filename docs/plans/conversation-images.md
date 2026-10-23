# Ordinary image attachments in the main conversation

Active increment after #374. CSV/XLSX now use normal Attach files; PNG/JPEG/WebP
still follow the old inline image-attachment path there, while the separate
Add images control already uses real stored image references and local Vision/
photo operations. Unify the ordinary entry with those existing typed operations.
Do not add another image executor or rewrite the photo pipeline.

## User contract

Choose images through Attach files, see ordered previews, type a question or edit
instruction, then Send. First Send and saved Chat/Work use the same image IDs as
Add images/Library. Ordinary questions use installed local Vision. Editing,
recomposition, upscale and first-frame video reuse their existing actions;
explicit tool selection remains available. A natural request to generate from
attached references must use recomposition rather than silently dropping them.
No model inference or photo generation starts on selection. Show local execution and the actual model/tool.

Use the existing stored image upload API, validation, preview/removal/order and
Library. Preserve partial upload success and show errors outside a replaced
ordinary attachment control. Reject mixed image/data/text/PDF scopes before any
upload rather than silently removing files or project context. Keep the legacy
text/PDF/image attachment behavior where explicit coding/other scopes require it.
Update supported-file/privacy help to explain the chosen operational path.

## Execution boundaries

No native/API/schema/dependency changes or downloads are needed. Current-turn
stored image IDs grant the existing bounded image/Vision tools; source content,
history or model text cannot choose files or extend permissions. Images and
projector loading remain inside the existing local Runner/model boundary.
Chat's existing image-to-Vision fallback does not need text-provider inference;
prevent an unnecessary text-model prerequisite or external-provider snapshot on
that path. Work may still need the existing selected-model planner for ambiguous
intent. Preserve external visibility and never send image pixels to it implicitly.

Image/reference/result hashes, Trash, leases, cancellation, resources, owned
model admission and recovery keep their existing contracts. Explicit Chat action
and Web overrides retain precedence; no image attachment grants project, shell,
agent activation or external sharing. Natural reference generation routes to the
existing Qwen recomposition operation with exact ordered source IDs.

## Verification

Use temporary DBs/fake inference for first/saved Chat/Work image input, ordinary
question fallback without a text-provider/model prerequisite, reference generation,
ordered multi-reference edits, mixed/explicit scopes, partial upload errors,
removal/order, Stop and source provenance. Preserve old text/PDF behavior.
Run full backend/Runner checks when routing changes, frontend lint/types/tests/
build, Compose/image and compiled desktop/phone qualification. Review the full PR
to develop before a backed-up rollout. Qualify a short actual local Vision question
on a synthetic known image, restore the operator model preset and distinguish it
from fake photo generation or subjective editing quality. Reuse existing model
installations; do not claim new real photo generation without running it.

## Inspected input follow-ups — active increment

Ordinary image entry is deployed by #375. Local checks passed 2550 Python/Runner
cases/nine opt-in skips and 630 UI cases. Actual local Qwen3.5 9B Vision answered
“czerwony” for a synthetic red frame and the operator preset was restored; see
`data/acceptance/conversation-image-attachments-20261023/post-deployment-qualified.json`.
No new real photo generation was executed by that qualification.

Extend the existing conversation reference resolver to the exact image input of
a completed Vision inspection. Freeze portable ID/path/MIME/size/SHA metadata on
new orchestration and Vision Runs; verify current bytes in the worker before
inference and before publishing the description. Persist the same snapshot with
the result. Old Vision results without this evidence cannot implicitly select an
input; explicit attachment/reinspection remains available. No backfilled claim
that a changed legacy file was inspected.

The current user's direct referential command is the only authority. Bind the
successful orchestrator, its user message and ordered images, exact successful
Vision child, visible assistant message and result artifact on the same Task and
conversation. Do not use description text to choose IDs. Current source metadata,
Trash, canonical storage and SHA must still match. Do not fall back to an older
unrelated generated image when a newer inspected source is unavailable, incomplete
or ambiguous. Preserve generated-output leaf selection and explicit scope/Work
context precedence. Clear plural commands may reuse the inspected ordered group
for supported multi-reference operations; singular/one-input operations cannot
silently choose from several inputs.

Support direct edit wording with a colon or “to/into/na” after an explicit image
reference; discussion, negation and quoted commands remain non-actions. Show
whether the reused source is an inspected input or a generated result. All work
uses the current normal Task and existing Vision/PhotoPipe/video children,
permissions, Stop and recovery. Normal tests use fake inference and photo contract
checks. Qualify compiled desktop/phone and actual local Vision reinspection on a
synthetic source; do not claim a real edit unless it was actually executed.

For implicit inspected-input media follow-ups, the controller rechecks actual source
bytes before publication. Photo/video children retain the frozen selection and
recheck metadata, canonical paths and hashes before any native dispatch. A source
changed while queued fails without launching inference; normal explicitly selected
media and older queued jobs retain their existing contracts.

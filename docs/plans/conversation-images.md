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

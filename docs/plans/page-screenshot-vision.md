# Visual page analysis from saved captures

Continuation of the deployed [page reader](chat-page-reading.md). Reuse the
existing local image-understanding capability; do not build another executor,
browser, inference service or implicit external-AI integration.

## User flow and execution

1. Expand a rendered page's sources in Chat and choose **Analyze visual design**.
   This stages that exact screenshot and the existing `image.describe` action.
   Keep an existing draft; otherwise provide an editable design-analysis question.
   Switch the turn to Chat and disable Web for this inspection, restoring its
   prior preference after Send is accepted. Nothing executes
   until Send. The tool states that a local Vision model may load.
2. Send creates the ordinary assistant Task. Its worker uses the existing
   `vision.enqueue_inspection`, installed GGUF/projector selection, owned runtime
   preparation, GPU admission and cancellable Chat vision Run. No download or
   cloud fallback. Existing idle-owned-model eviction and active-consumer guards
   stay authoritative; external runtimes cannot be stopped.
3. For a screenshot from a successful page answer in the same conversation, bind
   its canonical page JSON, original answer and selected PNG before model loading.
   Verify conversation/Run/parent ownership, source hashes and the actual selected
   frame. The Vision Run receives only `filesystem_read` for stored evidence,
   never new Browser/network permissions. The existing bounded inline-image
   transport receives the pixels and the corresponding page's visible text.
4. Return the local model's answer in the conversation. Save its normal Markdown
   artifact with both PNG and page JSON parents. Page sources identify the actual
   local model, captured viewport, saved visual observation and inspectable Run.
   Observations can be imperfect; they do not establish the whole site's design.
5. Same-page follow-ups freeze references to the visual message and Markdown hash,
   validate the completed local vision Run, exact screenshot/page/model binding
   and unchanged text, then supply a bounded observation to the selected text
   model. They reuse the original capture and do not run Browser or Vision again.
   Web off retains its normal no-page-reuse behavior for ordinary Chat.

## Boundaries and continuity

Browser ownership anchors source context to the original successful answer across
multiple follow-ups. Preserve legacy captures that lacked an origin metadata key;
do not require a re-fetch after an application update. A new failed page request
must not revive an unrelated old site. Changed, superseded or cross-conversation
visual evidence fails without automatic regeneration.

Explicitly choosing an image from another conversation remains a normal image
inspection; it must not inherit that conversation's stored DOM/page text. Failed
or unbound page answers similarly cannot silently supply page context. Model
permissions, Stop, conservative recovery and source artifact access use existing
contracts. No new public request field, schema migration or host endpoint is added;
turn receipt hashing remains unchanged.

## Qualification

Use fake Browser/native/model providers and disposable databases for normal tests.
Cover actual inline image preparation, page-text scope, description lineage,
repeated and legacy follow-ups, changed JSON/PNG/description/model bindings,
cross-conversation context isolation and cancellation. Check the staged action,
explicit Send, chosen frame, local-model attribution and saved-source follow-up
on compiled desktop and phone UI. Full local gates and PR review precede rollout.

The installed Qwen3.5 9B/projector pair already passed a separate real pixel test
on 2026-10-13; see [vision](../chat-vision.md). A new page-analysis hardware smoke
must be explicitly run and separately reported. It may manage only idle AI
Station-owned runtimes through typed operations, with restoration of the prior
model preset afterward. Never count fixtures as real model/design acceptance.

# One composer for entry and continuing conversations

The current shell gives saved conversations a persistent left history panel on
large screens, with search, date groups, archive filtering and older-history
paging. The application navigation becomes a compact, expandable rail while in
Chat; every dedicated workspace remains available. On phones, history opens as a
keyboard-accessible drawer and the navigation is a separate disclosure.

The saved conversation fills the available viewport. Only the transcript scrolls;
the compact title/model header and composer remain visible. User messages are
right-aligned, assistant answers use the readable central column, and advanced
settings plus memory move into one labelled dialog. A focused message is outlined
only during keyboard focus, rather than framing the latest answer permanently.

The immediate entry and existing conversations now reuse `ConversationComposer`:
the same message field, Enter/Ctrl/Command+Enter and IME behavior, collapsed
attachment/tool menu and compact footer. Shift+Enter keeps multiline input;
Enter in a tool input does not accidentally Send the conversation. An active turn
shows Stop while allowing the next draft to be typed, without submitting it.
Existing typed action scopes, turn receipts, cloud disclosure and model loading
are unchanged. Generic regeneration still cannot repeat an orchestration action.

The transcript follows new content only while the reader is near the bottom.
Reading earlier messages preserves scroll position during updates; Jump to latest
returns to the current answer. Code, selected text and interactive controls retain
normal keyboard behavior instead of triggering message-list navigation. The whole
token stream is no longer an `aria-live` region.

Verification includes the existing turn/attachment/coding conversation tests,
shared composer tests for shortcuts, composition, tool edits and independent Stop,
and read-only Chromium checks at 1440/390 with a synthetic long transcript and
actual live metadata. The browser check updates the fixture while reading earlier
messages, verifies the unchanged scroll position and Jump to latest, and submits
no workload. Evidence: `data/acceptance/conversation-shell-20261014`.

This advances the [conversation plan](plans/chat-work-experience.md); a unified
provider/model catalog and verified reasoning have been delivered.
[Session draft text](chat-drafts.md) now survives refresh/navigation with a compact
retry identity. [Searchable history](chat-history.md) reaches older conversations
with cursor paging. Richer contextual Work follow-ups remain a separate increment.
It does not claim that long-media or those remaining features are delivered.

## Focused Chat qualification — 2026-10-15

This is a frontend-only layout change. Turn receipts, uploads, model selection,
Chat/Work routing, streaming, Stop and existing execution permissions are retained.
Normal frontend qualification covers format, lint, types, the complete UI suite
and the production build. Chromium checks use the real API and worker against an
isolated database and a deterministic fake provider over private LAN HTTP; they
exercise Send, streaming, persisted reload, history navigation, settings and
keyboard dismissal. Screenshots and results live under
`data/acceptance/chat-focused-ux-20261015/`; this is not a real-model inference test.

## Reading-first refinement — 2026-10-15

The transcript uses a wider central reading column with larger type, restrained
speaker labels and quiet Copy/response-details actions. Successful execution
badges are retained for assistive technology; active, failed and partial states
stay visible. Full execution details are one labelled link away. Timestamps stay
in the semantic transcript and appear on desktop hover or keyboard focus.
History rows emphasize titles; their hover text retains model and update time.

The shared composer starts as one line, expands with multiline input and shrinks
when text is cleared or sent. Attachment/tool forms keep their full width when
opened. Short screens give the remaining viewport to the scrollable transcript;
they no longer inherit a fixed-height message area from the older layout.

Qualification evidence for this refinement is stored under
`data/acceptance/chat-reading-ux-20261015/`. It uses a fake provider with the real
API and worker, not real model inference. No execution boundary or data schema
changes are part of this refinement.

## Vision result hierarchy

A completed successful image inspection keeps the answer and file links primary.
Execution details remain available behind the existing native disclosure; active
or failed steps retain their visible status/errors. The description artifact's
Image sources disclosure loads its lineage only when opened, preserving Library
source inspection while avoiding duplicate source previews and eager lineage
requests in the normal transcript. Ordinary generated-media/coding behavior and
Library details retain their existing contracts. Verify native keyboard disclosure,
source links, reload and reading position in desktop and phone layouts.

# 0.6.1: chat inputs, public image references and Studio discovery

User goal, 2026-11-12: advertise Studio on the public site; fix rich image prompts
rejected at intent interpretation; paste clipboard images/screenshots/documents
into chat; find a real image online and transform it through the normal tool chain.
All four items and the release preparation remain in scope.

The reported failed Run retained two otherwise valid semantic responses with
725/698-character descriptions. Both failed the arbitrary 500-character field
limit before any tool executed. Both intent stages now share a bounded 4000-
character description contract. Original instructions and reference bindings are
retained, not truncated or replaced with a stock example. Test the actual saved
responses, long generic prompts, and invalid/over-limit input separately.

Clipboard paste reuses the chooser's existing validation, local upload/text/PDF
reading, previews, removal and error paths in the shared composer. A clipboard
file is not a request to send the message. Ordinary text paste remains native.
The event API works on HTTP LAN without clipboard-read permission; no global
clipboard polling or arbitrary HTML/URL fetching is introduced. Existing image
references are retained within the same four-image limit. Unsupported/mixed files,
busy uploads and scope restrictions report errors rather than silently replacing
attachments. Verify both the new and existing conversation, plus mobile layouts.

Public image work uses typed `web.image_search` and `web.image_import` actions
under the captured public-images-v1 policy and explicit Web permission. SearxNG
image engines return actual source aliases. Only captured aliases/user-supplied
public URLs can be imported. Every redirect and DNS address is checked/pinned;
credentials are never forwarded. Bounded MIME, bytes, still-image dimensions and
pixel decoding lead to a canonical app-owned PNG/thumbnail, provenance and events.
There is no arbitrary download destination, shell or host filesystem access.

A frozen image reference_mode=web requires an actual successful import before
edit/recompose/upscale. Importing the reference does not fulfill the requested
transformation; it remains visible in chat and Library beside the later result.
Workers handle networking, cancellation, claim/lease checks and artifacts through
Task→Run→Events→Artifacts. No new schema/native endpoint or execution engine.
Legacy queued work does not gain the new policy automatically.

The website gets a dedicated responsive Studio explanation, using typography and
native layout only. Existing approved media remain unchanged; no private film or
unreviewed imagery is published.

Acceptance: relevant frontend/backend regression and security tests; actual
clipboard events in a compiled browser UI; desktop/mobile site inspection;
real public image discovery/import; one ordinary local-model search→import→edit
conversation with source and final output visibly inspectable; reviewed PR to
develop, preserving rollout, version/QA/release packages, then the human-owner
master promotion required by release policy. Synthetic tests alone do not prove
real search-provider availability or image inference.


## Verified candidate, 2026-11-12

The two actual failed intent responses now validate intact (725 and 698
characters); no user prompt was replayed or truncated for that check. Current
ReAct and legacy durable-controller tests exercise search, owned import and image
transformation. Stop both during a download and at its completion prevents late
publication. Multiple imported candidates remain alternatives for single-image
Edit. Byte/pixel/animation limits and private-DNS/redirect rejection are tested.

The pinned SearxNG image-engine configuration returned real image results, and
one actual public source passed pinned download and canonical pixel decoding.
A compiled Chromium UI connected to a disposable real API accepted native
Ctrl+V twice in both new and existing conversations, retaining two separate
image references; no message was sent. The site and composer were inspected at
desktop/mobile widths with no horizontal overflow or browser exceptions. This
does not yet qualify a complete real-model search-to-edited-image conversation;
that remains a separate acceptance gate before release preparation.

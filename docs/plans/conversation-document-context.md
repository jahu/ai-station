# Selected documents in the main conversation

Extend the existing Files & data conversation tool with the deployed selected
PDF/text/Markdown scope. Upload/drop or Library selection should work in both the
first-message and ongoing composer without creating a persistent Agent or requiring
an agent editor. The existing data Task graph returns the answer/table/files and
source cards inline. This is document-backed analysis, not a second chat engine.

DataScope adds optional documents with absent-field serialization preserving old
request/receipt identities. The API freezes only metadata before binding the current
message, then enqueues. The worker verifies originals before creating a workspace;
ordinary read_documents and source handoff use the #411 extraction/cancellation/
provenance contracts. Existing model selection, private workspace, deadline, Stop,
Python and output inspection stay unchanged. No migration or native change.

A shared context-tools method orders documents before reviewed public research and
limits optional data files to seven, leaving one complete captured-JSON input.
Exact current-message/Run scope, definitions, source permissions and dependencies
must include documents. Historical follow-ups reuse the immutable verified capture
as offline data, granting no renewed document or network access. Create-from-
instructions rejects selected context until it is removed. No automatic access to
old attachments, earlier files, invented paths or additional documents.

Both composers share ConversationDataControls and readiness. Add document selection
there and report upload progress so Send cannot race an unfinished upload. Keep
spreadsheet inspection, public research, creation and selected-model behavior.
Results distinguish documents and captures from live public sources. Tests cover
Chat/Work, no Agent row, snapshot/source tamper, Stop, mixed inputs, replay/follow-up,
legacy identity and compiled desktop/mobile controls/results. Separate actual
CPU/native extraction/execution from injected inference. Release #411 stays live
until exact-head checks, review, merge and post-deployment qualification prove this
increment. The full-platform goal remains active.

## Qualification — PR #412

All 3400 normal CPU/Runner cases were collected: 3391 passed and nine expensive
opt-in cases skipped. Frontend format/lint/types/build and 749 UI tests pass.
Exact image/backend/compiled assets and normal/dev/private-LAN Compose checks are
recorded under `data/acceptance/conversation-document-context-20261024`.

Compiled 1440/390 browser cases cover both Chat and Work, first PDF Send and an
ongoing large-text Send, refresh, inline results and source cards. Eight actual
native offline Docker Python jobs calculated 27 from the selected text; ongoing
jobs consumed all 180025 captured characters. No Agent row was created. Inference
and the isolated model catalog were injected; no new GPU work is claimed. Source
code, dependencies, native/launcher files and the #411 document reader remain
unchanged at their boundaries; schema remains 0035.

A targeted mixed-source fixture initially omitted the Chat mode, and compiled
scripts initially used the first-message button label and legacy message response
selector for an existing conversation. Those failed attempts remain separate.
Corrected current-source cases and the complete final suite pass; no actual test
failure is waived. Documentation-only follow-ups qualify only with byte identity
to the backend/frontend heads that actually passed.

Use `post-deployment-qualified.json` and the shared deployment authority before
claiming rollout. No physical-phone, external email or new model/hardware
qualification is implied. The full-platform goal remains active.

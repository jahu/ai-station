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

# Selected documents as agent context

Reports and local code/data agents can explicitly select stored PDF or UTF-8
text/Markdown documents. This is separate from unrestricted host read_file, which
remains unavailable. Documents are app-owned Artifacts, chosen by the operator;
models cannot invent paths or extend the selection.

A nullable documents JSON scope (migration0035) freezes selected artifact IDs,
hashes, sizes and MIME types. Absent scope serialization preserves old definition,
receipt and consent identities. Selection/upload stores files only. API handlers
never parse PDFs or run inference. The ordinary context child reads documents in
the worker, emits events and saves a source-bound full JSON capture plus a bounded
model excerpt. Original bytes are checked before use; changed/trashed/missing
inputs require review. Historical captures remain readable.

Use a fixed, bounded CPU reader process for PDF extraction, without inherited
credentials or model-supplied commands. Bound input (8MiB PDF /256KiB UTF-8 text),
PDF pages (64), captured text (256KiB/document), CPU/memory/wall time and output.
Stop/expiry kills and reaps only its owned reader; worker exit cannot leave an
unbounded parser. Encrypted, invalid or image-only PDFs fail explicitly; no OCR or
pixel vision is implied. Show extraction limits/excerpts, not a false full read.

A bounded report-tool call may search or choose a text window within the saved
selection. It grants no networking. Offline Python receives the checked complete
captured text, with a document-specific bounded JSON input budget; report/coding
context stays excerpted. Keep legacy public-source input bounds unchanged.

Both agent editors offer upload/Library selection, source names, removal and
clear activation feedback. Result source cards link to original files, captured
text and the source Run. Generated code receives observations, never live document
or host filesystem tools. No native Runner protocol/model download is added.

Test scope/legacy hashes, MIME/byte ownership and symlink/trash boundaries, normal
text/PDF extraction, bounded malformed input, Stop/deadline/worker-loss cleanup,
query/window validation, immutable report/data adoption and desktop/mobile UX.
Qualify real CPU PDF/Python paths separately from fake inference. Release remains
#410 until reviewed local gates and deployment evidence prove this increment.

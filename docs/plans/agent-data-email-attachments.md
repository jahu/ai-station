# Deliver generated data files by email

The current agent-result email delivers report text or result IDs, never files.
An agent that creates an Excel workbook should be able to deliver that actual
workbook to its reviewed recipients. Extend the existing result-email and offline
Python graph, not the transport architecture or a second notification engine.

## Reviewed scope

Add optional attachment_kinds (csv, xlsx, png, text) to result-email policy. Default
empty is omitted from serialization so old grants, receipts and definitions keep
their identity. Only Python/data agents can select these formats. Selected extra
formats become required outputs in the existing generation/repair contract; CSV
already exists. Missing requested output must fail, never silently skip a file.
Changing formats requires review/activation again under the existing definition
fingerprint. Default remains per-message review. No new migration/dependency.

Only the successful final data-result Run's verified download/export IDs may be
selected. Never attach original uploads, scripts, internal JSON, a previous run,
or arbitrary Library/host paths. Bind exact IDs, fixed filenames, MIME, lengths
and hashes to the delivery payload, its approval and result fingerprint. Limit to
four files, 4 MiB each and 16 MiB combined. Verify regular files, canonical paths,
hardlink/symlink boundaries and actual bytes when preparing and immediately before
SMTP submission. A changed/trash/missing result or changed consent stops delivery.

Reuse EmailDelivery, Message-ID, email.send Run, approval, Stop and conservative
unknown-outcome journal. The child receives filesystem_read only for real
attachments. Build bounded MIME bytes before recording submission_started; failure
before DATA must not masquerade as an uncertain send. Ordinary reviewed messages
and market emails cannot inherit agent attachments. No file bytes, credentials or
new recipient authority enter model prompts. Local setup never sends mail.

## User experience and verification

Agents and the conversation editor offer four optional generated-file format
choices. Explain that selected output bytes leave the workstation and show limits;
summary mode describes the body separately from its attachments. Activation
consent includes the selection. The common delivery preview lists exact filenames,
format, size and Library inspection before approval; saved receipts retain it.

Test legacy identities, mandatory generation formats, complete worker flow, MIME
bytes and hashes, approved scope, revocation/Stop before and after connection,
changed sources, partial/failing/unknown delivery and no blind resend. Normal tests
use temporary DBs, fake inference and a project-owned SMTP sink, never operator
accounts. Qualify actual TLS MIME delivery to that local sink with deterministic
public sample data. Do not claim operator-inbox delivery or send external mail.
Run full backend/Runner and frontend checks, exact image/Compose and compiled
1440/390 setup/approval/receipt/reload/Stop flows; review/develop merge, then back up
and deploy while preserving native Runner and owned models.

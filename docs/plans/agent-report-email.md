# Reviewed email delivery for agent results

The platform can already deliver deterministic market alerts, but ordinary
research/system/data reports have only in-app notices. Extend result delivery
through the existing SMTP connector, EmailDelivery journal, approval model and
email_send worker. Keep original report generation and in-app notices working
when email is absent or unavailable. No new messaging service or account API.

## Contract

The operator selects an enabled SMTP connector, its current policy revision,
allowlisted recipients and a subject prefix on the agent definition. Default is
per-message review: the finished frozen message waits for its ordinary email.send
approval. Automatic delivery requires a separate explicit activation confirmation
bound to the agent's reviewed instruction/tool/input scope, connector revision,
recipients and notification policy. Editing that scope or connector revokes the
standing grant. A model never chooses sender, recipients, credentials or transport.

Freeze the policy in the parent Run's existing definition snapshot. Keep absent
policy fields out of legacy serialization; this extends stored JSON rather than
adding a database column. Use only a verified final result from the same agent
Task, never preparation success, partial media windows or an unvalidated coding
proposal. Reuse the final-result filtering already present in notices.py.

Render a bounded plain-text message from the actual saved report or deterministic
final-result summary, with source Run/Artifact IDs and authenticated application
links when a reviewed access URL exists. No raw code, attachment, private source
file, exception dump, token or credential is implicitly included. Show exactly
what will leave the workstation in per-message review and explain the automatic
scope in activation. Larger reports need an explicit excerpt notice and retained
local original. Media/data/code result families must each pass provenance and
completion coverage before their email path is advertised as operational.

The same Task gains an ordinary email.send child and existing EmailDelivery row.
A stable operation key/source-result identity prevents duplicate publication.
The original result stays successful if preparation/delivery fails; show the
notification outcome separately. Persist source-result/hash/definition/grant
references and verify them immediately before submission. Never blindly retry a
sending/uncertain receipt. Preserve per-message email and market-alert contracts.
Stop before dispatch prevents sending. Cancellation/failure must not create a new
notification loop or widen/renew the agent budget. Approval waiting and email
execution remain inspectable through the existing Runs, notices and delivery UI.

A conditional significant-price alert still uses the existing deterministic
market scope. General report delivery must not pretend to implement arbitrary
model-driven significance rules. Any future optional model decision needs its own
bounded inspectable decision Run; it cannot alter the frozen message or envelope.

## Implementation sequence

1. Add pure optional policy/schema and consent-fingerprint helpers. Existing
   definitions, permissions, factory drafts and unavailable adapters remain
   unchanged until the complete delivery path is tested.
2. Extend explicit agent settings/activation and freeze the policy/grant in normal
   workflow snapshots. Reuse connector revisions/allowlists and approval records.
   No credentials in definitions, prompts, events or normal API responses.
3. Share final-result selection with in-app notices and publish an idempotent
   ordinary email child from actual saved outcomes. Protect the main result with
   a short transaction/savepoint and record preparation errors separately.
4. Extend email_send with a distinct strictly validated agent-result reference.
   Unknown, mixed, forged, changed-source and revoked markers reject before SMTP.
   Preserve normal message approval and existing market scope verification.
5. Add a compact Email delivery section to Agent settings and conversation review:
   connector, recipients, review/explicit automatic mode, scope disclosure and
   recent delivery outcome. Keep the happy path optional; setup never sends mail.
6. Qualify report, data, coding and media final-result projections independently;
   do not advertise an unfinished family. Keep generation/failure history and
   distinguish result ready, prepared message, accepted SMTP and uncertain outcome.

## Gates

Use temporary databases, synthetic report/input artifacts and fake/local test
SMTP, never ambient operator credentials or real recipient delivery. Cover legacy
identity/default no-mail behavior; recipient/header validation; required consent;
connector/definition/source mutation; cross-agent/Task/source substitution;
partial-result rejection; per-message review; Stop; duplicate/restart races;
uncertain submission; SMTP refusal/failure; and unchanged market/manual email.
Actual private test-sink qualification needs the ordinary worker and durable
receipts. UI gates include real API/SQLite desktop/mobile settings, activation,
approval, result/delivery inspection and reload. Run normal complete Python/Runner
and UI checks, Docker/Compose as applicable, full PR review to develop and a backed-
up rollout. Real operator-inbox acceptance requires the operator's configured
connector; never infer it from a private test sink.

Current worktree: `.tools/agent-report-email`, branch `feat/agent-report-email`,
based on develop `737dbd3` (deployed PR #399). Implementation is local and still undergoing complete qualification; it has not
yet been merged or deployed. The full platform objective remains active.

## Implemented qualification notes

Absent policy serialization retains all three legacy in-app flags and does not
change existing Run/consent digests. The compiler/factory cannot invent an email
scope. Summary mode copies only deterministic completion text and verified result
IDs; report mode includes the actual saved report or verified answer/table preview.
Code reviews require their saved JSON report; configured checks precede delivery.
Segment/preparation success and partial artifacts cannot publish an email.

A private project's automatic adoption is normalized only through its existing
verified workspace binding and exact original definition. It preserves the
original approval record and expiration, including subsequent scheduled runs.
User changes to project, instructions, tools, source scope or policy do not use
that derivation. SMTP revalidation reloads ORM identities because worker sessions
retain cached rows across commits. Pausing, revocation, connector changes and
source mutation during connection are covered independently of pre-queue checks.

Local synthetic tests are not real inbox delivery or a new media GPU smoke test.
The live PR #399 native/media qualification remains unchanged by controller-only
email work. Real account/inbox acceptance still requires configured operator SMTP.

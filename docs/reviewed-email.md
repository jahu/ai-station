# Reviewed email delivery

The operator-reviewed SMTP foundation is merged and deployed in PR #342. It
passed 1945 Python tests (nine opt-in skips), 540 frontend tests, all local gates,
compiled desktop/phone acceptance and deployment/persistence verification.
[Activation-scoped price alerts](agent-market-watch.md) are deployed in PR #343.
[General agent result delivery](plans/agent-report-email.md) extends this same
foundation in PR #400; its qualification and live deployment record are kept
under `data/acceptance/agent-report-email-20261024`. No real account or external
recipient is configured by tests.

SMTP configuration lives on the existing Connector: host, TLS transport (465 SSL
or 587 STARTTLS), username, sender and allowed recipients. Credentials reuse the
SecretProvider (stored file or environment reference), never database plaintext,
model prompts, events or error strings. Request-validation diagnostics retain field
locations and messages but omit raw input and context, which may include a
write-only credential on a model-level validation error. TLS certificate/hostname verification is
mandatory. There is no arbitrary URL, port, shell or unencrypted SMTP option.

Draft creation validates the connector revision and recipient allowlist, freezes
the complete message and creates an ordinary Task/Run waiting for approval.
Previewing never sends. Explicit approval queues the existing worker; permissions
are `email_send` and `network_external`. The durable delivery identity, message ID
and payload hash bind that Run. Connector edits/deletion cannot race active work.

The worker connects/authenticates without holding the database transaction, checks
Stop before DATA, persists a sending journal before network submission, then
records accepted/refused recipients. Acceptance means the SMTP server accepted
responsibility, not that a recipient's inbox received it. Partial acceptance is
inspectable and never automatically retried. Disconnects or a worker crash after
submission starts produce an unknown outcome requiring inspection. A late Stop
cannot unsend accepted mail: the receipt stays accurate and the Run reports that
Stop arrived too late. No blind requeue or automatic resend is permitted.

Normal tests use synthetic credentials, fake transports and an isolated local
mail sink. Live external delivery requires a separately reviewed configuration,
recipient and explicit opt-in. Before publication qualify permissions, approval,
Stop, recovery, deduplication, redaction, API validation, UI and the local protocol
integration. Automatic price alerts and ordinary result reports retain distinct
reviewed scopes; neither grants a model control over recipients or credentials.

Transport semantics: [Python SMTP client](https://docs.python.org/3.12/library/smtplib.html).

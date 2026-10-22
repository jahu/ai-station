# Reviewed email delivery

Implementation in progress. This increment provides a typed SMTP connector and
operator-reviewed message delivery. It prepares the existing market-agent
workflow for scoped email, but does not yet grant agents an email tool or send
price alerts automatically. No real account or recipient is configured by tests.

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
integration. Stock-provider support and activation-scoped unattended agent email
remain separate follow-up work.

Transport semantics: [Python SMTP client](https://docs.python.org/3.12/library/smtplib.html).

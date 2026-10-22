# Scoped automatic price-alert email

Next implementation after reviewed SMTP (PR #342). The existing four-stage market
watch is deployed. This increment must finish the user's recurring price → email
workflow; a manual SMTP composer alone does not satisfy it.

## Execution and authority

- Add an optional typed email scope to the saved market policy: one configured
  SMTP connector, its public policy revision and up to five allowed recipients.
  No arbitrary body, URL or model-selected recipient. Preserve old observation
  policy hashes by excluding this new optional delivery scope from baseline keys.
- Extend the existing explicit Enable action to **Enable and allow alert email**.
  Require a distinct confirmation flag; persist a real `Approval` with
  `action=agent.email.enable` (its existing nullable run_id supports configuration
  grants). Bind agent ID, canonical market scope, connector policy revision,
  sender, recipient set and fixed message-template version. Show this approval in
  agent details. Natural-language drafts and duplicates cannot inherit consent.
- SMTP public configuration gets a stable policy revision. Changing credentials,
  server, sender, recipients or enablement rotates it; a health check does not.
  Recheck the enabled agent, exact consent and connector revision before queueing
  and immediately before SMTP. Pause/revoke/configuration changes stop future
  submissions; they cannot unsend an accepted message. Re-enabling requires fresh
  consent, so a queued old workflow cannot inherit a later grant.
- Only deterministic comparisons create email. Atomic market notification work
  creates its in-app notice and a normal `email_send` child with a frozen envelope
  and recorded policy authorization, not a fabricated per-message user approval.
  Reuse the existing SMTP worker, journal, permission/Stop/recovery contracts.
  The model never writes an automatic message or decides whether a price moved.
- Derive a stable delivery UUID from the immutable MarketAlert ID and template
  version. Replayed publication reuses that receipt; unknown/partial/accepted
  outcomes cannot be silently resent. Quote freshness, threshold and cooldown
  still apply. Below-threshold/first/repeated/stale quotes create no mail.
- Put the mail child on the same Task/agent with a parent/source reference and add
  its dependency before the notification stage commits. Report completion must
  include actual delivery outcomes; failures retain comparison and in-app evidence
  with a prominent mail error. Task Stop covers every child. No second scheduler,
  queue, external side-effect engine or generic model email tool is introduced.

## UX and qualification

Agent market settings select an enabled mail connector and allowed recipients,
show the sender, threshold/cooldown and a fixed sample message, then request the
explicit activation consent. Changing scope visibly requires review again.
Agent results show in-app notice and SMTP acceptance separately, with receipt
links and truthful partial/unknown/late-Stop states. Saving settings sends no mail.

Tests must cover activation consent, missing/rotated credentials, pause/re-enable,
duplicate definitions, frozen scope, cross-agent/alert provenance, no-alert paths,
concurrent/replayed publication, partial/unknown outcomes, Stop and stale leases.
Use synthetic quotes and the private TLS sink for an actual complete workflow.
Verify settings/enable/result/error flows on desktop and phone. A real external
recipient requires explicit scope/configuration and remains separately reported.
Stock quotes remain the subsequent fixed-provider increment; no trading follows.

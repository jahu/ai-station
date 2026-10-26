# Notification delivery scope

Owner decision, 2026-10-26: defer SMTP for now; consider push notifications later.
This changes current release acceptance, not the recorded outcome of earlier tests.

## Current release

- Keep existing in-app agent notices, reviewed schedules, threshold comparisons,
  deduplication and inspectable Run history.
- Preserve the SMTP connector, grants, secret handling, cancellation/recovery and
  prior private-sink qualification. It remains optional and unconfigured; actual
  operator-inbox delivery has not been performed and is not a current release gate.
- Retain CONNECT-003 and AGENT-013 for future SMTP acceptance. Their prerequisites
  explain the owner's deferral; no initial operator answer is filled automatically.
- Tailscale access is confirmed by the owner. It is private access to AI Station,
  not a notification channel.

## Future backlog: optional push

First choose a delivery approach with the owner: browser/mobile Web Push or a
compatible notification service. Do not install, subscribe, publish or claim an
operational integration as part of this planning item. Evaluate mobile background
behavior, browser permissions, private-access compatibility and any external relay.

Implement a typed delivery channel behind the existing notification workflow,
using Task → Run → Events → Artifacts, exact reviewed recipients/subscriptions,
secret references and truthful delivery status. Keep notification suppression,
revocation, bounded retries and uncertain-outcome recovery inspectable. Explicit
opt-in is required; a model cannot enable a channel or choose another recipient.
Qualify real delivery on the target device separately from fixtures and transport
acceptance. Push does not become a release dependency until explicitly scheduled.

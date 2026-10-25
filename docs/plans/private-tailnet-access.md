# Private remote access from a phone

LAN/password access is deployed. Read-only workstation inspection on 2026-10-25
found no Tailscale executable or enrollment. Deliver an optional Settings →
Operator access flow, preserving localhost/LAN, operator sessions and the private
Runner/model transports. Do not expose the UI publicly or enable Funnel.

## Execution and ownership

Use a separate AI Station-owned **userspace** tailscaled instance: fixed
`--tun=userspace-networking`, private state/socket, no TUN device, routing, DNS,
exit-node, SSH or host network configuration changes. Never operate the system
Tailscale socket or an existing unrelated service. Detect installed binary/help
capabilities and otherwise offer a pinned, hash-verified optional install. No
unreviewed auto-update, root installer or silent dependency download.

Keep durable node keys in a user-owned native-only secret directory, outside the
control-plane data mount and allowed artifact/project roots. Restrict directory
and socket permissions; verify canonical paths/ownership and symlink boundaries.
Store only non-secret node/origin references in application metadata. App backup
must not export Tailscale keys; missing credentials require re-enrollment.

Typed operator-only setup/login/enable/disable operations create ordinary Tasks/
Runs; workers call narrow Runner operations. No generic command, configurable
proxy target, privileged container or new agent tool. The fixed reverse-proxy
target is the configured UI loopback port. Process identity, PID start time,
boot ID, ownership and private-socket state govern inspect/stop/recovery. A
completed startup Run does not imply that enrollment or HTTPS serving is ready.

Show explicit stages: not installed, stopped, login required, device approval,
HTTPS consent required, ready, failed/unknown. Opening the account login and
Tailscale HTTPS consent pages is a necessary operator step, not an inferred
approval. Never store auth URLs/keys in Run events, normal logs, prompts or DB.
Public status projections omit user/peer lists, machine keys and login URLs.
Expose any validated short-lived login link only to the authenticated operator.

Before enabling Serve, freeze the actual owned node ID/DNS name and operator
password state. Add only its exact HTTPS *.ts.net origin to the existing Host/
Origin policy, with a server-owned revision. Preserve environment-configured
origins and localhost/LAN. Secure cookies apply to the approved HTTPS authority;
proxy identity/forwarding headers never replace the operator password. Reject
unexpected Serve handlers, ports, targets or Funnel configuration rather than
resetting unrelated state. Disable only the owned HTTPS endpoint. Persistence,
restart, Stop and expiry must not blindly repeat enrollment or external actions.

## Delivery and acceptance

1. Implement native fixed command builders, bounded public status and exact Serve
   configuration checks. This initial module is not an operational adapter.
2. Implement pinned installation diagnostics, native private ownership/process
   journal and typed lifecycle; test cancellation, restart/recovery and redaction.
3. Implement operator-only API/worker Run contracts and versioned origin policy,
   including auth/CSRF/Host/Origin/password-removal and restored-state tests.
4. Build accessible desktop/mobile Settings onboarding with clear login/consent,
   service state, the actual private URL, copy/open and owned disable controls.
5. Complete local gates, image/Compose, full diff review, PR to develop and rollout.
   Then perform actual enrollment/Serve and phone-outside-LAN acceptance with the
   operator. Fixtures, a configured origin and loopback proxies do not prove a
   real tailnet or phone/LTE connection. Keep the capability unavailable until
   lifecycle/permissions/cancellation/recovery are qualified.

Primary references checked 2026-10-25:
- https://tailscale.com/docs/concepts/userspace-networking
- https://tailscale.com/docs/features/tailscale-serve
- https://tailscale.com/docs/reference/tailscale-cli/serve

Userspace transport and Serve/HTTPS configuration need an actual installed-version
probe before activation; documentation alone is not a successful smoke test.

Initial source increment: native pure argv/origin/status/Serve-shape boundaries
and 34 CPU tests pass with Ruff. No binary was installed, daemon started, account
enrolled or listener added. Node-online metadata is distinct from service/application
readiness. Next implement native ownership/private storage, actual installed-version
CLI probing, typed lifecycle and redaction/cancellation/recovery before API/UI wiring.
The current module is never registered as available. Preserve live #425 and the
unchanged running Runner/model while developing in this isolated branch.

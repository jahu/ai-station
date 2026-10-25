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

## Native core progress — 2026-10-25

Pinned official Tailscale 1.104.2 x64/ARM64 archives now have an explicit installer,
with SHA-256 checks, bounded selective extraction, private ownership, cancellation,
atomic publication and refusal to overwrite changed installations. The x64 archive
was actually installed under the project's ignored tools directory. Version and
daemon/login/up/set/serve help were executed and retained; no system package or
system Tailscale service was modified.

The service core reuses ProcessManager in a **native-private** directory outside
control-plane data. It binds its owner marker to the data root, journals a canonical
operation UUID, checks boot/PID start identity and preserves node state on stop.
Status discards login URLs, keys and peer/user lists; node-online is not application
readiness. Stale/missing ownership requires inspection. Only the owned process
group can be canceled; replaced socket/journal paths do not authorize cleanup.
Daemon arguments disable uploads, host syspolicy and TPM use, and select a private
state directory and userspace transport. The installed CLI accepted these flags.

59 focused CPU tests pass for builders, installation and actual offline fixture
process/UDS lifecycle, recovery, cancellation, PID reuse and path/ownership attacks.
A real unprivileged 1.104.2 daemon reached NeedsLogin and stopped cleanly in a
private temporary directory; socket0600, unchanged host routes/DNS and zero
login/Serve requests were checked. Evidence:
`data/acceptance/private-tailnet-access-20261025`.

Still pending: typed login/Serve operation ownership and secret-link handling;
installer cancellation/recovery through native jobs; operator API/worker permissions
and versioned origin policy; onboarding UI; full local/release gates and real
operator enrollment/HTTPS/phone acceptance. No endpoint or operational adapter is
registered yet. Keep live #425 and its running native Runner/model unchanged.

## Operator integration candidate — 2026-10-25

The candidate now includes typed native install/start/login/Serve/stop/inspect/
cancel/link operations and a Settings → Operator access onboarding panel.
`POST /api/private-access` only enqueues an operator Task/Run with the exact
`manage_private_access` grant. It is not an agent tool or a general management
profile. The worker binds the saved password epoch, policy revision, request
receipt and selected actual node/HTTPS origin. Changing the password invalidates
pending operations while retaining an already approved origin for new sessions.
Disable revokes that origin immediately; password removal stays blocked until
owned shutdown is confirmed. Existing explicit LAN/proxy origins are preserved.

Install is a separately owned, deadline-bound Python process, using the same
pinned archive checks and cancellation callback as the explicit installer.
Replayed receipts do not launch duplicate processes. Native cancellation persists
an immutable tombstone before stopping an owned process, so a late request cannot
start after Stop. Only authenticated operators may retrieve a validated interactive
login/HTTPS-consent link, through a dedicated no-store endpoint. Links expire and
are never copied into ordinary status, database, events or UI persistence.

Stale private-access leases resume inspection of their existing operation, not
its launch. A recovered Stop is forwarded through the private API, including
queued resumed jobs. Uncertain outcomes require inspection and an owned Disable
before another setup action. No completion is inferred from a lost HTTP response.
The native service remembers only a successfully served endpoint in its private
storage. Runner startup may restart that owned daemon using its existing state;
it never repeats enrollment or Serve. Explicit Disable removes restart intent
and preserves account keys for a later reviewed start. Node keys remain outside
all configured filesystem roots and the Docker data mount.

Settings exposes install/download size, start, sign-in/approval, reviewed HTTPS
address, enable, current progress/Stop, inspection and disable. Setup does not
replace operator authentication. The address can be opened or copied on LAN HTTP
as well as HTTPS. Installing Tailscale and signing into the same account on the
phone remains an actual operator step.

Configuration: optional `AI_STATION_TAILNET_BINARY_DIR` and
`AI_STATION_TAILNET_PRIVATE_DIR` override XDG defaults (documented in `.env.example`).
The binary directory must match the pinned version/architecture installation;
private keys must be outside application data and every allowed/model root.
Never mount that directory into control-plane containers or include it in backups.

Focused native/API/worker and UI tests have passed during implementation. Full
local gates, compiled desktop/mobile acceptance, image/Compose, final review/PR
and deployment are still pending. No real login, HTTPS consent, private Serve or
phone/LTE acceptance has occurred; live #425 is unchanged. Earlier paragraphs
record the historical native-only stage, not the current candidate surface.

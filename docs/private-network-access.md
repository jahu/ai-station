# Private access from a phone or another computer

The same workspace can be used from multiple devices. This remains a single-owner application: sign in with the operator password, without a separate username. Conversations, runs and artifacts remain on the workstation.

## Home network

1. On the workstation, open `http://127.0.0.1:8765/settings` and store an operator password (at least 12 characters).
2. Set the workstation's private IPv4 address in `.env`, for example `AI_STATION_LAN_HOST=192.168.1.121`. Use your machine's address, not this example blindly. Reserving it in your router's DHCP settings avoids later address changes.
3. Start the production UI with `./scripts/start.sh`. The launcher adds `compose.lan.yaml`, retaining the localhost listener. For an existing deployment, stop its owning supervisor first; the launcher will not take it over.
4. On a phone connected to the same home Wi-Fi, open `http://<workstation-IP>:8765` and sign in with the same password.

Only explicit RFC1918 or Tailscale IPv4 addresses are accepted. Wildcard/public addresses and unauthenticated private startup fail closed. `AI_STATION_PORT` controls the published port. Without `AI_STATION_LAN_HOST`, normal localhost startup remains unchanged. Vite development is kept local; use the compiled UI on your phone.

This HTTP listener is intended for a trusted home network. It does not encrypt traffic on that network. Never forward this port on the router. For encrypted access away from home, use Tailscale below. Browser microphone/camera features may require HTTPS even on your home network; ordinary chat, uploads and workspace operations remain available over HTTP.

## Sessions and protection

Each device has a separate httpOnly, SameSite=strict cookie. Up to ten sessions coexist; the oldest is replaced at the limit. Sessions expire after 30 idle minutes or 12 hours from login. Signing out affects only that device. Password changes sign out every other device. Password removal is refused while private access is configured; remove the private configuration and restart locally first.

Passwords remain PBKDF2-SHA256 hashes. Only session HMAC material is stored. Login is limited to ten attempts per minute across the workstation, persisted through API restarts. Exact configured Host authorities and mutation Origins are checked; cross-site writes are rejected. Caller-supplied forwarding headers cannot grant authentication. Public health/login status contain no credentials. No new database table is needed; settings retain existing sessions.

The native Runner stays on its private Unix socket, model services keep their current bindings, and no Docker socket or additional host mount is exposed.

## Tailscale HTTPS access — next activation step

Tailscale is not installed or enabled by AI Station. Once the owner has installed it and enrolled both workstation and phone in the same tailnet:

1. Get the workstation's actual MagicDNS HTTPS name from Tailscale.
2. Add that exact origin to `.env`, for example `AI_STATION_ACCESS_ORIGINS=https://workstation.example-tailnet.ts.net`. Restart AI Station with its password still configured. This allowlist alone does not create a listener.
3. Use `tailscale serve --bg http://127.0.0.1:8765` after checking existing Serve configuration. Tailscale Serve provides a private HTTPS reverse proxy for tailnet members. Do not enable Funnel.
4. Open that HTTPS address on the enrolled phone and sign in with the AI Station operator password. The cookie is Secure for the explicitly configured HTTPS authority.

See the official [Serve instructions](https://tailscale.com/docs/features/tailscale-serve) and [CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve). Tailscale grants control over which devices reach the service; AI Station still requires its own password. No public router port is needed. Actual phone/LTE and Serve integration must be verified after enrollment; configuring an origin is not evidence of a real remote smoke test.

## Browser compatibility on private HTTP

Browser `crypto.randomUUID()` and `crypto.subtle` require a secure context; a
private HTTP IP address does not qualify. Client identifiers therefore use native
UUIDs when available and otherwise version-4 UUIDs from `crypto.getRandomValues()`.
Chat receipt hashes have a pinned pure-JavaScript SHA-256 fallback, preserving
retry identity across reloads without storing the request body in the receipt.
Video scene and GitHub connector identifiers reuse the same helper. See the
browser documentation for [secure UUIDs](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/randomUUID)
and [random bytes on HTTP](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/getRandomValues).

## Delivered acceptance — PR #326

The development preview now serves both localhost and the explicitly configured
home-network IPv4 address. The owner confirmed sign-in from another device and,
after the private-HTTP UUID fix, successful Send after refreshing the page.
Credentials, existing record identities and the owned 131,072-context model
container were preserved; SQLite backups and integrity checks passed.

Local verification: 1,651 Python tests passed with five explicit opt-in skips,
Ruff lint/format; 493 frontend tests, format/lint/types and production build;
production image plus normal, development and private Compose configurations.
The backend suite ran in immutable `32324e2`; the final browser fix changes only
frontend code/dependencies and documentation, with identical backend/Runner and
deployment sources. Eight UUID/draft cases verify secure-byte fallback, a known
SHA-256 vector and receipt reuse after reload.

Real Chromium under the private HTTP IP (not localhost) confirmed that native
`randomUUID` and `subtle` are absent, then sent messages through the real API and
worker to a deterministic fake local provider at desktop/mobile widths. Responses
streamed and survived page reload. Login/logout/settings also passed at
1440/390/320 px. This is browser/API/worker acceptance, not a new real-model smoke.
Evidence: `data/acceptance/private-network-access-20261015/` and
`data/acceptance/private-chat-uuid-20261015/`.

Earlier failed attempts remain in evidence: source identity changed under a
mutable test checkout (resolved by the immutable run), a large history integration
test exceeded its five-second budget (measured 5.28 seconds; bounded at 15 seconds
with assertions intact), and an outdated node-copy assertion was corrected. No
failed check was waived. Tailscale enrollment, HTTPS Serve and actual outside-home
mobile acceptance remain future activation work.

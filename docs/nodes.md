# Nodes and operator access

The only registered execution node is this workstation's private Host Runner over a Unix socket. After an operator password is stored, UI and API require a session cookie. Remote execution-node transport stays unpublished; optional private UI access is described in [LAN and Tailscale](private-network-access.md).

## Operator credential

Settings can store a local operator password (`PUT /api/operator-auth`). It is hashed with PBKDF2-SHA256 (600,000 iterations) in the `operator_auth` setting. The API never returns the password, salt or hash. Replacing the credential (`PUT /api/operator-auth`) or clearing it (`POST /api/operator-auth/clear`) requires the current password.

When that hash exists, requests other than `GET /api/health`, `GET /api/operator-auth`, `POST /api/operator-auth/login` and `POST /api/operator-auth/logout` require the `ais_operator` cookie. Storing the password or a successful login issues an httpOnly `SameSite=strict` cookie (`Secure` on a configured HTTPS origin, otherwise HTTP; `Path=/`). Only HMAC material is stored, using `operator_session` for the first device and token-derived setting keys for further devices. The cookie lasts 30 minutes of idle API use; authenticated requests refresh `last_seen_at` at most once a minute and re-issue that idle `Max-Age`. Sign-in also has a 12-hour absolute expiry that activity cannot extend. Idle or absolute expiry deletes the stored HMAC and clears the cookie. Up to ten devices have independent sessions. Logout deletes only the current device session; password rotation or removal deletes all sessions. Password removal is blocked while private UI access is configured. `GET /api/operator-auth` reports idle/absolute limits and cookie flags; it never returns the token, salt or hash. When an operator session is active, the workspace chrome exposes **Sign out** next to the private-control-plane label; Settings still has the same action. An additional private UI listener requires explicit configuration and the password.

`POST /api/nodes/register` requires that operator session and records a node identity only. It does not enable remote workload execution.

## Private UI access

See [LAN and Tailscale](private-network-access.md). UI access is separate from execution-node registration. The Runner remains on its private Unix socket.

## Node inventory and invitations

`GET /api/nodes` always includes this workstation's Host Runner (`transport: unix-socket`). System shows that inventory as one keyboard sequence (arrows, Home, End) with unique Revoke names; Revoke stays on the selected row. There is no inspectable node Run. After an operator password is stored, `POST /api/nodes/invitations` creates a pending remote node and returns a one-time `aisn_` token. Only the HMAC-SHA256 of that token is persisted. Later GETs omit the token.

`POST /api/nodes/register` accepts the token on the existing loopback API, marks the node `registered`, and consumes the token. `POST /api/nodes/{id}/revoke` clears pending or registered remotes. The local node cannot be revoked.

`remote_registration` retains the legacy value `loopback-token`; it describes the token record, not an operational remote executor. Transport for remotes stays `unpublished`. Registration does not open a LAN listener, extra TCP port, or target-aware remote resource claim. A registered remote still has no workload execution transport.

Invitations and revocation are control-plane writes, not Task/Run workloads. Changing the operator password is a setting write, not a workload.

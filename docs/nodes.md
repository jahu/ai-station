# Nodes and operator access

The only registered execution node is this workstation's private Host Runner over a Unix socket. Remote node registration, LAN transport and a session login for the UI are unpublished.

## Operator credential

Settings can store a local operator password (`PUT /api/operator-auth`). It is hashed with PBKDF2-SHA256 (600,000 iterations) in the `operator_auth` setting. The API never returns the password, salt or hash. Replacing the credential (`PUT /api/operator-auth`) or clearing it (`POST /api/operator-auth/clear`) requires the current password. The hash is a prerequisite for a future authenticated non-loopback listener; it is not yet used to gate localhost requests.

## LAN bind

`AI_STATION_BIND_HOST` is the host publish policy and defaults to `127.0.0.1`. Compose publishes `127.0.0.1:${AI_STATION_PORT:-8765}:8765`. A non-loopback value aborts process startup, whether or not the operator password exists. Authenticated LAN/node transport is not implemented, so a configured password does not open the port.

Uvicorn inside the container still listens on all container interfaces so Docker can map that localhost publish. That internal bind is not host exposure. Do not set `AI_STATION_BIND_HOST=0.0.0.0` to “make Docker work”.

`GET /api/operator-auth` reports `lan_bind_allowed: false` and `lan_exposure` of `disabled` (loopback), `forbidden` (non-loopback without a password) or `unpublished` (password present, transport still off).

## Node inventory

`GET /api/nodes` returns the local Host Runner only (`transport: unix-socket`). `remote_registration` is `unavailable`. There is no join token, TCP listener, or target-aware remote resource claim.

This inventory is a control-plane GET, not a Task/Run. Changing the password is a setting write, not a workload.

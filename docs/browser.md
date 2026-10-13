# Rendered public pages

Status: internal renderer under development; Browser remains unavailable in the
agent/tool registry until the native dispatch, permissions, owned-container
cancellation/recovery and UI contracts are verified. Static GET and web search
remain separate working tools.

Public-page inspection will run as an ordinary Task → Run → Events → Artifacts
workload, launched by the user-level native Host Runner in a fixed executor
container. Its outputs are bounded rendered text, page links and a viewport PNG.
Agents may inspect only explicitly saved reviewed URLs with `browser` and
`network_read`; page contents never grant new permissions or change instructions.

The container has no network, host mounts, Runner/Docker sockets, browser profile
or credentials. It runs non-root with a read-only filesystem, dropped capabilities,
no-new-privileges and fixed memory/CPU/PID/temp/deadline limits. Chromium's own
sandbox is disabled inside this container; the Docker boundary isolates untrusted
page scripts from the workstation. It is a separate optional workload image, not
another control-plane service. Startup must never implicitly pull/install it.

The trusted native parent will fulfill every public GET through a bounded JSON
stdio protocol, pinning DNS addresses and retaining Host/TLS verification from
[public connection identity](security-model.md#public-connection-identity).
Redirects and subresources repeat validation; writes, local files, credentials,
Service Workers, downloads and WebSockets are denied. Screenshot and text paths
stay relative to the app data root. No raw container/command API is exposed.

The renderer blocks [Service Workers](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-route)
and uses [Chromium Fetch interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)
to pause redirects as well as requests. Simple Playwright fulfillment attempted
the redirect directly in real testing, correctly failing against `network=none`.
Do not replace the network-disabled boundary with a request callback alone:
Chromium has networking paths beyond normal intercepted HTTP requests.

Remaining delivery: fixed native container identity/reservation, permission-checked
typed dispatch/report, cancellation and uncertain-completion recovery, bounded
parent GET broker, ordinary artifact adoption, agent workflow integration and
rendered-page previews in the agent history. Real Chromium verification must
include JavaScript, redirects, blocked requests, screenshot decoding and actual
owned-container cleanup. Normal tests must not launch Docker or public network.

## Renderer verification — 2026-10-13

Nineteen normal protocol tests passed without Docker, models or public network.
An explicit manual check ran actual installed Chromium in the new executor image,
with the container's network disabled, no mounts, read-only root, non-root user,
all capabilities dropped, no-new-privileges, 1 GiB memory and a 256-PID budget.
A synthetic page supplied through the stdio broker redirected, fetched JSON,
updated its visible text with JavaScript and produced a decoded 1240×800 PNG.
Attempted POST and WebSocket did not reach the broker. The uniquely labelled test
container was removed. This verifies the renderer and isolation, not a live public
website, native Run dispatch, agent integration or complete browser acceptance.

The initial simple Playwright route failed on the redirect. Chromium Fetch
interception passed the redirected-URL check. One 128-PID attempt crashed at page
creation; the final 256-PID budget passed. Evidence is retained locally under
`data/acceptance/browser-pages-20261013/`. Do not enable Browser from these checks
alone; the remaining native lifecycle, public broker and UI contracts above still
need implementation and verification.

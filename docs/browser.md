# Public-page browsing

Browser is an optional, read-only page tool for Agents and explicitly selected
Chat page reading. Enable it only with the reviewed
executor image installed locally. It renders JavaScript, records bounded visible
text and links, and saves a 1240×800 screenshot for each reviewed public URL.
Static HTTP GET and web search remain separate tools.

## Setup and use

Build the optional workload image explicitly from this repository:

```bash
docker build -f browser-executor/Dockerfile -t ai-station-browser:local .
```

Configure both components, then restart AI Station:

```dotenv
AI_STATION_BROWSER_ENABLED=true
AI_STATION_BROWSER_IMAGE=ai-station-browser:local
```

The control plane checks the native Runner's actual image capability. The Runner
requires the fixed entrypoint, non-root user and protocol label, then snapshots
the immutable image ID into each request. Missing Docker/image/Runner leaves the
tool unavailable. Startup never pulls or installs this image automatically.

In Agents, attach **Browse public pages**, enter up to three reviewed public URLs,
save the definition and explicitly enable it. Browsing uses the shared workflow
before its local-model report. The definition's URL snapshot applies to that Run;
later edits do not change it. Natural-language drafts recognize explicit browser,
JavaScript or page-screenshot requests and remain disabled for review. The
Platform assistant can edit those URLs on its attached agent definition too.
The history shows local screenshot previews, captured plain text, public source
links, capture time and a warning when resources were blocked or unavailable.
Screenshots and the full JSON request audit are ordinary Library artifacts.

In Chat, Web → Search options → **Read JavaScript pages** applies to the next
message's explicit public URL. The Chat reply waits for its owned Browser child.
Captured text grounds the answer; saved screenshots are available for the user to
inspect. Source-backed follow-ups reuse the immutable capture without fetching it
again. This does not enable screenshot vision analysis or account browsing.

An explicit operator can also enqueue `POST /api/browser/runs` with
`{"urls":["https://example.org/"]}`. The HTTP handler enqueues only; the worker
executes. `GET /api/browser/capabilities` reports real availability. There is no
arbitrary browser command, HTML, script, image or Docker-operation parameter.

## Execution and security

Task → Run → Events → Artifacts dispatches through the private native Runner.
Each Run requires `browser` and `network_read`. The native wrapper owns its process
group and each container by Run UUID, request digest, page index, immutable image
and recorded container ID. Images and JSON use UUID-based app-owned paths.
Optional `remember_workflow` retains a bounded observation in the agent's own
memory with source Run provenance; failed/canceled observations are not retained.

The container has no network, host mounts, Runner/Docker sockets, profile or
credentials. It runs non-root with a read-only root, dropped capabilities,
no-new-privileges, 1 GiB RAM, one CPU, 256 PIDs and a 256 MiB temporary filesystem.
Chromium's own sandbox is disabled inside this boundary. This is a separate
optional workload image, not a control-plane service.

Every accepted GET passes through a native stdio broker with public-address DNS
validation, IP pinning, original Host/TLS identity and no authentication/cookies.
Redirects and public subresources repeat validation. Only selected response
headers are returned, without Set-Cookie. Each page permits at most 60 requests,
4 MiB per response, 8 MiB total response bytes and a 45-second broker deadline;
rejected oversized responses consume that byte budget too. Rendering has a
55-second parent deadline; a Run is limited to 165 seconds and cannot exceed its
agent's remaining deadline. Text is bounded to 8,000 characters per page.

[Chromium Fetch interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)
pauses redirects as well as main-page resources. Service Workers, downloads,
popups, non-GET requests and WebSockets are blocked. Chromium has other networking
paths: the network-disabled container is the boundary, not interception alone.
Public-page content never grants permissions or changes agent instructions.
Browser is an explicit workflow step, not a model-selected arbitrary tool call.

Stop persists cancellation, removes only identity-checked owned containers and
terminates only the owned process group. Process inspection cleans up containers
left after a killed wrapper. A lost Docker create response is uncertain until the
owned container can be identified; it is never treated as successful or blindly
replayed. Successful exit and confirmed cleanup are required before adoption.

This adapter inspects anonymous public pages. Login, form submission, clicks,
private services and connector account automation are not exposed. A screenshot
is a bounded initial render, not a promise that every page feature finished.

## Verification — 2026-10-13

Normal tests use fake Docker, network and LLM providers. They cover typed inputs,
permissions, request identity, SSRF/redirect rejection, budgets, cancellation,
uncertain creation, process ownership, report adoption, agent URL snapshots,
manual/scheduled workflows, scoped memory, SSE and UI previews. They do not launch
Docker or public-network tests.

An explicit real Chromium check rendered a synthetic redirected page supplied
through stdio, fetched JSON, updated visible text through JavaScript, blocked POST
and WebSocket, decoded its PNG and removed its own container. A separate real
Task/Run check used the private native Runner and anonymous public HTTPS: screenshot
and JSON artifacts were adopted through the worker. Real cancellation and forced
termination of the owned wrapper removed its container and published no artifacts
from unsuccessful Runs. Both checks use isolated acceptance data, no production
agent, GPU model, external-AI tokens or credentials. Local evidence is under
`data/acceptance/browser-pages-20261013/`. Agent report integration uses a fake
provider; these checks do not claim an actual LLM browser report.

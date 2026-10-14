# Optional Chat web search

Web search is a per-message opt-in tool, disabled by default. It runs in the existing worker before local inference and records its query, results, timestamps and failures as Run events plus a JSON artifact. A visible Sources panel links the actual retrieved results independently of model-generated citations. The Search the web toggle is a keyboard sequence with a unique Search name; Space or Enter selects it and does not send. There is no inspectable search-toggle Run. Arrow keys, Home and End move through those cards; Enter opens the selected public URL. This is search, not browser automation. Regeneration reuses the user's explicit search intent. Cancellation closes the search request; an unavailable search service fails the Run rather than pretending the answer is current.

Only the explicit search query (or the current message if no query is supplied) leaves the control plane. Conversation history, memory and attachments are never used as outbound search context. Queries are bounded. Retrieved titles/snippets are untrusted reference data, cannot grant tools/permissions, and are passed to the local model with citation instructions. The tool searches; it does not fetch arbitrary result pages, execute scripts or perform browser automation.

A private SearXNG container provides the JSON search API without account credentials. It has no host ports, host resources or Docker socket. Chat and agent search run from the control plane. Local coding search runs from the Host Runner only when `AI_STATION_WEB_SEARCH_URL` is set to an operator-configured reachable endpoint; the default Compose service remains unpublished, so runner-side search is off unless that setting is provided. Its image is pinned, capabilities dropped and filesystem read-only, with temporary cache and an ephemeral signing secret. No Redis/Valkey is required with the limiter disabled. Only the worker contacts the fixed operator-configured search endpoint. Result links permit HTTP(S) public hosts only; no automatic page fetching occurs.

References: [SearXNG Search API](https://docs.searxng.org/dev/search_api.html), [server configuration](https://docs.searxng.org/admin/settings/settings_server.html), [container installation](https://docs.searxng.org/admin/installation-docker.html). Search engines can throttle requests; such failures remain visible. Normal tests use fake HTTP results and never access the internet.

The default profile explicitly enables Bing and Yahoo in `config/search/settings.yml`.
Listing an engine under `keep_only` does not override its upstream disabled flag.
On 2026-10-14 the previous profile returned no sources: Brave was rate-limited,
DuckDuckGo required CAPTCHA, and Bing remained disabled by the pinned defaults.
The replacement profile returned 11 and 17 results for two deliberate public
queries in an isolated instance of the same pinned image, from Bing/Yahoo with
no engine failures. No CAPTCHA or provider access controls are bypassed. This
is current availability evidence; future provider failures remain visible and
the operator-configured `AI_STATION_WEB_SEARCH_URL` override is unchanged.

## Verification

On 2026-09-29, a real Chromium submission in an isolated database dispatched an Assistant Run and Chat Run, searched public llama.cpp documentation through SearXNG and streamed a Polish response from the workstation's managed 27B Q4 llama.cpp model. Five actual source cards persisted after refresh; desktop and mobile layouts passed browser checks. Run `2088778e-6f73-4cec-98f9-9d3a63348602` belongs to that isolated smoke database, not production history. The model was loaded beforehand using its existing two-GPU preset through a normal AI Station Run; no models were downloaded or external runtimes reconfigured.

The exact Compose search service passed startup and health checks as an isolated project and was removed afterward. Automated tests use mock HTTP and model providers and cover opt-in behavior, regeneration, source artifacts, cancellation, missing permissions, malformed/oversized responses, redirects, unsafe links and complete engine failure. Search result snippets can be incomplete; source cards identify what was actually retrieved, independently of the model's prose.

Agents can also select this tool with a mandatory, separately reviewed public query. Manual and scheduled Runs share the search permission, cancellation, events and source artifact contracts. See [agent research](agents.md#scheduled-internet-research). Fetching full pages is a separate [reviewed HTTP GET tool](agents.md#reviewed-public-http-fetch); search still does not open result URLs.

## Search-informed image generation

In the Platform assistant, **Auto** and **Generate image** can use **Search the
web**. Enter a short **Search query** for the subject or company and describe the
visual result in Message. The switch no longer forces an explicit image request
into a text-only conversation. Polish “Stwórz obraz…” and English “Create an
image…” are deterministic image intents.

The assistant queues a normal Chat Run for bounded search and a visual brief using
the selected model. Only the reviewed query leaves for search; that brief uses
the current instruction, without unrelated history, memories or summaries.
Actual source cards and the JSON search artifact remain inspectable. Snippets
are untrusted references, never tool grants or a claim that pages were opened.
A successful nonempty brief of at most 4000 characters atomically publishes the
image Run in the same Task. That Run gets its ordinary media permissions and
fresh GPU reservation, without network permission. The Library image retains the
research Run and source artifact ids; optional Upscale follows the existing chain.

Failed search, empty usable sources, failed or oversized inference, cancellation
and uncertain worker completion do not publish an image. Restart does not replay
a completed brief. Search combined with another Auto-routed action asks for a
separate research turn or disabling search, instead of silently changing intent
or ignoring the selected tool. Explicit incompatible action/media combinations
remain rejected before enqueueing. Normal verification uses fake search, model
and native jobs; real search-informed generation is recorded separately when run.

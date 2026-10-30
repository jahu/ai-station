# Optional Chat web search

Web search starts enabled in the unified assistant. The switch saves the current account’s preference across conversations and devices; turning it off keeps it off. This does not force a search for every instruction: known non-research actions retain their existing routing and permissions. Each request still records its own search selection and network permission; API requests that omit search remain offline. It runs in the existing worker before local inference and records its query, results, timestamps and failures as Run events plus a JSON artifact. A visible Sources panel links the actual retrieved results independently of model-generated citations. The Search the web toggle is a keyboard sequence with a unique Search name; Space or Enter selects it and does not send. There is no inspectable search-toggle Run. Arrow keys, Home and End move through those cards; Enter opens the selected public URL. This is search, not browser automation. Regeneration reuses the user's explicit search intent. Cancellation closes the search request; an unavailable search service fails the Run rather than pretending the answer is current.

An explicit Search query is used exactly as entered, without history. Otherwise, a follow-up is resolved by the selected permission-bound model using at most six recent ordinary text messages (1200 characters each), before contacting a search engine. Only the resulting short query leaves for search; the full conversation, system prompt, pinned memory, summaries and attachment bodies are excluded. Replies based on private attachments, memory, summaries or other executors are excluded from query context. The actual query and original follow-up are recorded separately in source details. A failed or canceled topic resolution never searches the ambiguous raw instruction. Long messages use a bounded 4000-character question draft rather than imposing the search query limit on Chat. Queries are bounded. Retrieved titles/snippets are untrusted reference data, cannot grant tools/permissions, and are passed to the local model with citation instructions. The tool searches; it does not fetch arbitrary result pages, execute scripts or perform browser automation.

A private SearXNG container provides the JSON search API without account credentials. It has no host ports, host resources or Docker socket. Chat and agent search run from the control plane. Local coding search runs from the Host Runner only when `AI_STATION_WEB_SEARCH_URL` is set to an operator-configured reachable endpoint; the default Compose service remains unpublished, so runner-side search is off unless that setting is provided. Its image is pinned, capabilities dropped and filesystem read-only, with temporary cache and an ephemeral signing secret. No Redis/Valkey is required with the limiter disabled. Only the worker contacts the fixed operator-configured search endpoint. Result links permit HTTP(S) public hosts only; no automatic page fetching occurs.

References: [SearXNG Search API](https://docs.searxng.org/dev/search_api.html), [server configuration](https://docs.searxng.org/admin/settings/settings_server.html), [container installation](https://docs.searxng.org/admin/installation-docker.html). Search engines can throttle requests; such failures remain visible. Normal tests use fake HTTP results and never access the internet.

The default profile explicitly enables Yahoo in `config/search/settings.yml`.
`keep_only` does not override an upstream disabled flag, so it is enabled explicitly.
On 2026-10-15, an actual user question about a Breaking Bad cast member reproduced
Bing returning dictionary/ranking pages for just “aktor”, and unrelated results
for an English multiword query. Those responses had no engine error. Bing was
removed from the default profile; Yahoo returned relevant article results for a
concise English query in the same pinned SearXNG image. This is availability
and relevance evidence for those queries, not a permanent provider guarantee.

Results are checked against query terms, ranked before the five-source limit and
multi-topic queries reject matches to just one generic word. This is a lexical
relevance check, not verification of the truth or completeness of article text.
If a Chat search returns no usable sources, the selected, permission-bound model
may rewrite only the explicitly approved query once into concise search keywords.
This empty-result rewrite receives no history, memory, attachments or source instructions; it
has a 30-second/256-token/300-character bound and cannot call tools. The original
query and actual retry are recorded in events, the artifact and source details.
No final factual completion runs if relevant sources are still missing. Stop
closes both search and rewrite inference; there is no background retry loop.
Search-informed image briefs keep their separately reviewed short query.
The operator-configured `AI_STATION_WEB_SEARCH_URL` override remains supported.

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

## Automatic query preparation (0.1 candidate)

An ordinary automatic search using the selected Chat model prepares a concise query
before the first search request, including the first message in a conversation.
It reuses the selected, admitted model with tools disabled, JSON output, a
256-token budget and a 30-second preparation deadline. The preparation prompt
contains the question and the existing bounded ordinary-text history; it does
not inherit the conversation system prompt, attached file bodies, pinned memory
or summary contents. A reported death or other claim is treated as something to
verify, rather than an established fact.

Preparation, the effective query and model identity are recorded on the ordinary
Chat Run. The search JSON artifact, saved message and Sources panel retain the
actual query, original question and preparation model/location. Failed, invalid
or canceled preparation never falls back to sending the raw question or
generating a factual answer. Stop closes the preparation stream. The existing
one-attempt empty-result refinement remains bounded and auditable.

A manually entered query retains its existing reviewed search/refinement path.
Reviewed agent queries, image-research briefs and explicit page reading keep
their existing scopes. This increment adds no hidden model load or automatic
external provider choice. When the user explicitly selects an external Chat
provider, preparation uses that same model and requires the Run's `external_ai`
permission; both the events and Sources panel mark it external. This avoids an
additional model/server setting or loading a hidden planner. Existing
permission-bound follow-up resolution is preserved. Tests use synthetic
model/search output. Real-model relevance qualification is recorded below.

## Real search-informed image acceptance

On 2026-10-14 the deployed Assistant completed public search → a visual brief
from the owned local 27B llama.cpp model → prompt-only Qwen generation. The
model was loaded using its saved two-GPU, 131072-context q8_0 preset; this brief
did not exercise the full context length. Five actual source cards and a
832×1216 Library image persisted in the conversation. The prompt-only output
was visually inspected: an empty forest, without the earlier unrequested
portrait. The original photo pipeline's SHA256 remained unchanged. Model and
media reservations were released. Real desktop/mobile browser checks displayed
the source cards and loaded image without JavaScript errors or horizontal
overflow. Image generation took about 361 seconds.

## Follow-up regression (2026-10-15)

Conversation `a1b746f7-c9a7-4104-b5ba-fbec094fcbb1` exposed an additional
failure: the raw follow-up “masz teraz dostep do neta, nie pierdol i sprawdz”
was searched without its actor subject. Downdetector passed the lexical filter
through incidental terms, preventing empty-result refinement. Automatic follow-up
queries now resolve their subject before retrieval, even when the raw instruction
would return results. Exact manually entered queries retain their explicit scope.
Topic resolution shares the existing provider permission, bounded generation,
Stop and audited events; no extra tool, full-page fetching or model fact trust is
introduced. Earlier model assertions are expressly unverified query context.

## Selected-model search qualification (2026-10-30)

The deployed development build completed the original ambiguous actor-question
regression and a subject-free follow-up through the real unified assistant,
ordinary worker, owned RVN 27B Q4 llama.cpp model and configured SearXNG search.
Each Chat child recorded tools-free preparation with the selected local model,
the effective query, five actual subject-specific sources and the final saved
answer. Every returned title identified the subject or show; neither attempt
returned the earlier dictionary/ranking or Downdetector results. The follow-up
query explicitly recovered the actor’s name from bounded conversation context.
This establishes relevance for those two regression cases, not independent
verification of article claims or a guarantee for every future search.

The model used the two discovered GPUs, Q8 cache and a 4096-token allocation for
these short questions. The QA-owned instance was stopped afterward; temporary
verification devices were revoked and no existing owner device or credentials
were changed. Private evidence: `data/acceptance/search-preparation-20261030/`.

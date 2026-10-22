# Read a requested website in Chat

Requested by the operator on 2026-10-22. **The text-reading slice is implemented,
merged in PR #341 and deployed.** Rendered-page and visual analysis remain in the
backlog. This is distinct from web-search ranking; a simple website analysis does
not require a coding project or persistent agent.

## Problem and expected experience

Exact reported prompt:

> przenalizuj stronę akademia.ai i daj mi prompt do stworzaenia grafiki promujacej ta strone

Chat currently substitutes generic search snippets about graphic-design prompts
for reading the requested site. It then asks the user to inspect the website and
offers invented, hypothetical branding. The expected result is an analysis
grounded in the actual page and a useful promotional-image prompt, with linked
sources and a clear distinction between observed facts and creative suggestions.

## Implementation slice

1. Recognize explicit URLs and bare domains in requests to read or analyze a
   website. Normalize a bare domain to HTTPS; preserve the intended page. An
   unrelated domain mention, quoted source or model output must not silently
   grant a new network scope. Resolve follow-ups against recorded conversation
   sources, rather than searching the follow-up in isolation.
2. Reuse the existing reviewed public-page `http_fetch` implementation and its
   extraction, bounds and audit contracts. Connect it to ordinary Chat through
   the existing Task → Run → Events → Artifacts execution path. HTTP handlers
   enqueue; workers fetch. Freeze the selected URLs and permissions before
   dispatch. No new arbitrary HTTP/shell endpoint or parallel execution engine.
3. Honor the conversation's Web control and remembered setting (enabled by
   default). Show “Reading akademia.ai” and the resulting source beside the
   answer. With Web disabled, make the missing access clear and offer enabling
   it; never silently fetch. Read-only Chat access must not acquire Work,
   workspace-write, coding or agent-management permissions.
4. Supply the bounded extracted page text, title and available metadata to the
   selected model as untrusted source material, not instructions. Store requested
   and final URLs, fetch time, extraction/truncation outcome and source Run and
   artifact references. Search can supplement this evidence, but snippets must
   never be presented as a successful read of the requested page.
5. Reuse the existing isolated public-page browser only when rendering is needed
   and its separate permission/configuration is available. A text fetch cannot
   substantiate claims about colors, typography or layout. Visual analysis needs
   actual rendered evidence and a supported vision model; otherwise disclose
   what was not observed without inventing brand details.
6. Keep existing public-address DNS/redirect checks and response size, time,
   content-type and redirect limits. Reject private/loopback/link-local/metadata
   targets and public-to-private redirects; forward no operator cookies, login
   sessions or credentials. No crawling beyond the reviewed scope. Preserve
   Stop, durable provenance and conservative recovery; do not re-fetch silently
   on replay.

## Acceptance

- The exact Polish prompt above and its full-URL variant read the requested page
  and produce an attributed analysis and usable graphics prompt from that page's
  actual offer. No generic design-search substitution or made-up brand claims.
- A follow-up such as “teraz przygotuj wersję na Instagram” retains the same
  source and distinguishes reused evidence from a new fetch.
- Loading, sources and failures work on desktop and phone. A timeout, blocked
  target, unsupported content, login wall or JavaScript-only empty page is shown
  honestly, with an applicable retry/render/paste option.
- Tests cover Web off, URL/bare-domain selection, multiple/ambiguous targets,
  redirects and DNS rebinding protection, untrusted-page prompt injection,
  bounded extraction, follow-up provenance, cancellation and receipt replay.
  Normal tests use fake HTTP/models; real public-page acceptance is explicit and
  records the tested URL and result without claiming unexecuted visual analysis.

Related existing boundaries: [reviewed page coding](../agent-page-coding.md),
[orchestrator](../orchestrator.md), [security model](../security-model.md).


## Delivered text reader (2026-10-22)

[PR #341](https://github.com/jahu/ai-station/pull/341) merged as `157e773`.
The qualified source `5123ca8` was deployed without replacing the operator's
loaded model. Targets are frozen from explicit reading instructions in the
user's own text, including bare domains. Existing DNS-pinned HTTP fetching runs
inside the queued Chat executor before inference and produces a JSON Artifact.
The assistant shows fetched sources separately from search snippets. Explicit
follow-ups can reuse a successful same-conversation Artifact after hash and
provenance checks, without another fetch or a query rewrite. Web off and explicit
custom search queries retain their existing behavior.

Qualification passed 1912 Python tests (nine opt-in skips), 534 frontend tests,
format/lint/type checks, production build, Compose validation, image qualification
and compiled desktop/mobile acceptance. The exact Polish `akademia.ai` prompt
above then passed through the deployed workers with a real local model and real
page fetch. An Instagram follow-up reused the same source and fetch timestamp.
Evidence: `data/acceptance/chat-direct-page-reading-20261022/production-smoke-result.json`
and `deployed-verification.json`. These checks do not establish visual analysis.

## Remaining backlog

Pixel-grounded brand/style analysis with a supported vision model remains separate
work. A text read must not pretend it observed typography, colors or layout.

## Rendered reader implementation — 2026-10-22

The next slice connects the existing optional public Browser executor to ordinary
Chat and Work replies. In Web → Search options, **Read JavaScript pages** is an
explicit choice for one message containing a public URL or domain. It is off by
default, incompatible with an exact search query and cleared after a successful
Send. Web off cannot carry this grant. No URLs are taken from attachments, quoted
examples, memory or model output. Missing scope/setup is an actionable failure;
it never substitutes search snippets for a rendered read.

The enqueue transaction freezes URLs, grants only Browser/network read and
publishes an owned native Browser child on the same Task. Chat acquires a normal
RunDependency on it; workers perform all rendering. The existing private Runner,
anonymous DNS-pinned GET broker, network-disabled Chromium, resource bounds,
ownership/Stop/cleanup and conservative recovery contracts are reused unchanged.
Stopping the Chat Run also stops its exact owned Browser child; shared model
loads and unrelated browser tasks are not canceled by that targeted operation.

Only a successful matching child supplies a hashed canonical JSON artifact plus
verified PNG artifacts. The selected model receives bounded visible text with
untrusted-source instructions, not request audits or screenshot pixels. Chat
keeps screenshots and capture times in collapsed page sources, with blocked-resource warnings and the distinction
between rendered text and pixel analysis. A same-page follow-up verifies original
answer/child/conversation ownership and artifact hashes, reusing the capture even
when Browser is subsequently unavailable. It performs no new page request.

Both static and rendered page sources can ground the existing image-brief stage;
the generated image Run keeps the page artifact reference and receives no network
permission. No new executor, arbitrary browser command, provider or schema is added.
Qualification evidence belongs under `data/acceptance/chat-rendered-pages-20261022`;
implementation alone is not a claim of rollout or real-model visual analysis.

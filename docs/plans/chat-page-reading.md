# Backlog: read a requested website in Chat

Requested by the operator on 2026-10-22. **Planned, not implemented in ordinary
Chat.** This is a Chat grounding gap, distinct from improving web-search ranking.
Include it in the active product-completion work; do not require a coding project
or a persistent agent for a simple website analysis.

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

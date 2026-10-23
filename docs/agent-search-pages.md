# Reading a research agent's search sources

`search_pages` is an optional agent workflow tool alongside `web_search`.
Before activation, review the saved public query and the explicit permission to
read up to three public result pages. Existing agents keep their tools unchanged;
ordinary Web search alone still returns snippets. No API key is required.

The worker publishes the existing search → source-page → report child Runs on
one Task. Page targets come only from the successful, directly preceding search
step's hash-verified JSON artifact in that same agent/workflow/definition. Pick
at most three distinct public URLs from its bounded results. No caller/model URL,
new query, page-link recursion, cookies, credentials or JavaScript is accepted.
Existing DNS pinning, redirect validation and public-address checks remain the
HTTP boundary. Search snippets and page contents are untrusted reference data.

Use the existing cancellable HTTP GET executor for each target under the original
workflow deadline. One unreachable source may produce a partial observation;
cancellation/deadline never starts another fetch or publishes a completed result.
Persist exact search provenance, attempted targets, read excerpts, failures and
HTTP-source lineage in a bounded JSON artifact. The report distinguishes read
pages from snippets, skipped/binary pages and failed requests. Reading a source
is not independent verification of its claims.

This is a workflow-only tool, not a new model tool loop. Model-selected URLs or
extra calls remain forbidden. Existing approvals, scheduling, resource admission,
Run leases, Stop and conservative recovery apply. No schema migration, native
transport or separate execution system is added.

Qualification must cover scope/permission checks, source hash/identity isolation,
ordering/dependencies, bounded selection/output, SSRF/redirect reuse, individual
failures, Stop/deadline, retention, report context and reviewed disabled drafting.
UI must identify source-page reads in settings and results, including partial
outcomes, on desktop and phone. Real acceptance uses a reviewed free public query
and the already installed local model, then pauses its QA agent without replacing
operator runtime settings. Do not claim a real read from a fake fetch fixture.

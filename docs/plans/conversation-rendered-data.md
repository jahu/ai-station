# Rendered public data directly in Chat/Work

Build on deployed PR #402 rather than another browser, agent or Python executor.
A user selects Data analysis, reviews public URLs, optionally chooses **Read
pages with JavaScript**, and asks for a computation/table/chart in the ordinary
conversation. No persistent Agent, repository registration or manual source
capture is needed. Static public GET remains the default. Existing Web/render
and exact search scopes stay separate; do not silently turn default Web into
browser access or change automatic intent routing in this increment.

## Authority and execution

Add an optional strict `render_pages` flag to DataResearchSelection. True requires
explicit reviewed fetch_urls and selects Browser instead of static HTTP for those
URLs. Search/search-page selection remains independently reviewed. Omit false
from serialization, preserving every legacy research receipt/Run definition.
Reject extra fields, truthy strings, private URLs and Browser without URL scope.
No schema migration: this is existing frozen JSON request data.

The data root currently has an exact fixed REQUIRED permission set. Extend that
exact set with browser only when the frozen selected scope requests rendering;
do not infer it from Web on, model output or stored history. Update the root
publication and validation together. Workspace and Python retain their existing
minimal permissions; only the native Browser gets browser/network_read.

Reuse agent_page_coding's reviewed source order and raw/compact projection from
#402. Conversation research validation must recognize the exact Browser executor,
permissions, manifest index, parent, Task, project, definition and shared deadline.
Existing Browser payload/finish currently distinguish agents by agent_id; source
Runs here have no agent_id. Use NativeJobExecutor.prepare plus final adoption
validation to recheck the conversation binding, and use the frozen definition's
URLs/deadline for that verified source. Public standalone Browser Runs retain
existing parameters and behavior. No network or database I/O belongs in payload
construction. No new generic native execution interface.

Stop must prevent dispatch and publication; original expiry applies during
rendering and subsequent code stages. Unknown native outcomes stay inspectable,
never re-rendered blindly. Shared deadline, source hashes, screenshot references,
input map, exact result validation, bounded repair and offline captured-data
follow-ups all retain their existing contracts.

## UI and qualification

Use a small optional checkbox below selected Public data URLs. Explain that it
reads JavaScript-rendered text locally, saves screenshots for inspection and
keeps Python offline. Clear the option when the last URL is removed. Keep existing
file selection, model policy, disabled/sending states and compact source/result
components. A screenshot reference is not model pixel inspection. Add no new
workspace, manual setup flow or dedicated Browser screen.

Test actual API/worker/DAG results without a persistent Agent, source tampering,
permission/manifest/definition/deadline drift, before/during Stop, failed rendering,
source JSON follow-ups and receipt replay. Verify unchanged static and file-only
requests. Run full required local gates, exact Docker/Compose, compiled desktop/
phone first/follow-up/save/reload/Stop and a reviewed backed-up develop rollout.
Reuse unchanged native qualification only after exact source comparison. No
account or download is required. Real local-model/native Browser/Python coverage
is distinct from fixtures; #402 already verified a public JavaScript page's exact
10-marker count with 131072 context and restored the operator preset. Do not
repeat that real GPU work unless the new conversation boundary requires it.

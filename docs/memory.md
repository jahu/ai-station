# Persistent memory

Memory is control-plane metadata under the application data root. The existing Alembic-managed `memories` and FTS5 tables store content, tags, scope, pin/enabled state, confidence, timestamps and source Run/conversation/message references. Full-text search does not need an embedding model.

**Semantic search** offers a managed **Multilingual E5 Small** CPU model. In Memory,
confirm the approximately 130 MiB model/tokenizer download and choose **Set up
semantic memory**. Preparation verifies pinned bytes, checks actual vectors and
queues indexing automatically. Nothing downloads on startup, a status read,
indexing or a search. The offline encoder uses two CPU threads and a 2-GiB
address-space bound; it does not occupy GPUs or reload the chat model. FTS remains
available throughout setup and failures.

The panel shows readiness, current enabled-memory coverage, progress, errors and
Stop. **Search by meaning** uses the current scope/target filters and displays
matches with links to the original entries. Editing content invalidates its old
vector; choose **Index remaining memories** to update coverage. Disabled/deleted
memories never appear in new results. Changing scope hides old search hits until a
matching search completes. Historical Run results retain their original provenance.

**Advanced · existing local endpoint** retains explicit compatible `/v1` endpoints.
Only a successful managed preparation can activate the CPU backend; an endpoint
form cannot forge an installation. Model/endpoint/encoding changes invalidate the
index. Setup, probes, indexing and searches use ordinary Tasks/Runs/events/artifacts,
frozen settings and deadlines. Each CPU Run owns a fixed offline subprocess with
a parent-death signal; Stop waits for its termination. Recovery marks stale work
interrupted for inspection instead of replaying inference or downloads. Partial,
current vectors survive Stop; final results are published only after process cleanup.
Download progress has no memory text; weights/tokenizer stay in application-owned
`cache/embeddings/`. Native llama.cpp and external runtimes are unchanged. See
[model/permission/lifecycle contracts](plans/memory-embeddings-readiness.md).

The Memory workspace supports search, scope/target filtering, editing, pinning, disabling, and confirmed deletion. The entry list is one keyboard sequence (arrows, Home, End, Enter inspects) with unique Inspect names; the pin icon stays out of the tab order. Pin and enabled flags on an entry reuse that sequence with unique Memory names; Space or Enter selects the focused row and does not invent a memory-flag Run. `GET /api/memory` supports literal-token text search, exact tag filtering, pagination and optional disabled entries. SQL filters scope and enabled state before applying the result limit. `POST /api/memory` validates scope targets and compatible provenance references. Sources are immutable after creation; edits and deletion require `expected_updated_at` and reject stale versions with 409. Source-free entries are explicitly user-entered, not attributed to an AI. Linked sources establish provenance, not truth or endorsement.

Chat snapshots enabled, pinned global and matching conversation memory into a new Run's parameters. The snapshot includes the exact context and memory IDs/versions. Retrieval selects at most 20 entries, newest first, within a 12,000-character content budget; oversized entries are skipped. Project, agent, disabled, unpinned and other-conversation entries do not enter Chat. Editing or deleting a memory affects future Runs only; historical Run snapshots remain auditable. Memory content is user-controlled reference context and can be outdated.

Project and agent scopes are stored and searchable; consumers must request their own scope explicitly. No agent silently promotes inferred information into global memory. [Rolling conversation summaries](conversation-summaries.md) create editable scoped entries with exact coverage and source Run provenance. Oversized older messages are chunked at a recorded character offset rather than blocking the segment. Updates are user-requested; disabling/deleting the current entry stops future use without resurrecting an older summary. Existing recent-message window limits remain in force.

Validation uses temporary SQLite databases and fake API requests. It covers FTS index updates/deletion, restart persistence, literal-query escaping, scope-before-limit ordering, source validation, stale edits/deletes, pinned-context isolation and immutable queued Run snapshots. UI tests cover edit conflicts and explicit deletion confirmation.

Agents can explicitly opt into **Remember reports** (`memory_write`). Successful reports create own-scope observations tagged `agent-report` with immutable source Run provenance; no model chooses the scope or permissions. Failures and cancellation do not populate memory. Retention is independent of `memory_search`; disabling/deleting an entry removes it from future retrieval without changing historical Run context. See [agent retention](agents.md#remembering-reports).

**Remember workflow observations** stores successful telemetry, public search and HTTP fetch child Runs as own-scope observations tagged `agent-workflow`. `memory_search` results are not copied. The option is independent of report retention and remains off for existing agents. See [workflow memory](agents.md#remembering-workflow-observations).


## Explicit project memory

The optional **Project memory** agent tool requires a saved linked project and
`project_memory_read`. Linking a project alone still only tags Runs. Retrieval
is restricted to enabled memories in that snapshotted project, at most twenty
entries and 12,000 content characters, with saved IDs, versions and provenance.
Neither the model nor a tool-call argument can choose another scope/project.
Changing the agent's project affects future workflows only. Read observations
become ordinary child Runs with JSON artifacts; report context remains auditable.
This read tool never writes/promotes memory, copies entries into the agent's own scope,
grants Git/filesystem access or sends it to an external provider. Separate report
retention still requires the explicitly selected Remember reports tool. It is also an
allowed bounded report tool only when explicitly selected. Cancellation, deadlines,
permissions and workflow approvals use the existing shared contracts.

Verification (2026-10-13): full Python checks passed (887 tests; five explicitly
opt-in integrations skipped), frontend format/lint/TypeScript/build and 353 tests
passed, both Compose configurations validated and the application image built.
New temporary-database/fake-provider tests exercise manual and scheduled reads,
scope exclusion, revoked grants, target mismatch, immutable observed context,
restart persistence, provenance and model-argument rejection. Desktop/mobile
production-frontend previews used mocked APIs and made no writes. No real model
inference is claimed for this feature.

Project- and agent-scoped memory provenance provides **Open project/agent** and
**View runs**, linking to the existing scope-filtered run history. Global memory
has no project/agent actions. See [scope navigation](memory-scope-navigation.md).

## Scoped context for local code and data

Local coding and Python/data agents can explicitly select own-agent memory or
their linked project's memory. The normal child Run snapshots enabled entries
and their provenance; offline execution receives verified JSON, without live
memory tools or unrelated scopes. Source bytes, entry versions and enablement
are checked before execution; later edits do not rewrite historical captures.

Python agents may separately select Remember reports. After output validation
and confirmed cleanup, AI Station stores a bounded readable answer/table with
the source result and CSV identity. Only the result stage writes memory; model
generation and Python execution do not gain that permission. Failed or stopped
results save nothing. Memory remains inspectable/editable/disableable in this page.
See [the implementation contract](plans/agent-data-memory.md).

# Persistent memory

Memory is control-plane metadata under the application data root. The existing Alembic-managed `memories` and FTS5 tables store content, tags, scope, pin/enabled state, confidence, timestamps and source Run/conversation/message references. Full-text search does not need an embedding model.

Optional embeddings require an explicit local OpenAI-compatible `/v1` endpoint and model name that already serve vectors. AI Station does not download embedding weights, does not start llama.cpp with extra flags, and does not store empty or all-zero vectors. Setup, health, indexing and semantic search are ordinary Task/Run operations with cancellation. Without that setup, semantic endpoints fail closed and FTS remains the search surface.

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

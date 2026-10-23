# Reviewed research before local agent code

Status: implementation candidate, 2026-10-24. No deployed or real-model claim.

A persistent local coding agent should be able to research a reviewed public
query, read its search sources, optionally read explicit public URLs, and use the
observations when building in its private workspace. The current HTTP-only
composition blocks this ordinary combination. Reuse that same context handoff,
AgentToolExecutor, owned workspace/coding chain and existing UI tool choices.
Do not create another execution engine or give generated code network access.

## Contract

- Local coding may combine with web_search, search_pages and http_fetch. Search
  needs its saved public query; page reading needs either the existing verified
  same-workflow search or the explicit saved URLs. External coding and Python
  data agents retain their existing exclusive scopes.
- Execute search, its source pages, and explicit page reads in that order as
  ordinary dependency-linked child Runs. The reviewed approval precedes all
  research. Provision a missing private project through the existing factory.
- Before publishing coding, check the exact parent, manifest, source children,
  dependencies, definition, permissions, immutable JSON bytes and common absolute
  deadline. Hash-check every adopted artifact and preserve source provenance.
  Missing/changed/failed source evidence must not start coding. Distinguish
  snippets, fetched text and partial/failed source reads in bounded untrusted
  context. Public content cannot add tools, paths, commands or permissions.
- Preserve old HTTP-only requests and their saved source_run_id. Stop, lost-worker
  recovery and one absolute budget cover research, handoff and coding. No new
  schema, provider, model download, public publishing or external AI transfer.
- Keep existing tool checkboxes and query/URL editors. Selecting local coding
  preserves compatible research tools in either selection order. Activation must
  explain missing query/URLs; incompatible scopes remain excluded.

## Qualification

Use disposable databases and fake public sources/models for exact dependency
order, scoped query/URLs, source tampering, foreign/duplicate/omitted children,
artifact hashes, legacy scope, approval, Stop, deadlines, recovery and automatic
workspace continuation. Exercise assisted disabled drafts and editor selection
in both orders. Run required full backend/runner and frontend checks, compiled
desktop/phone flows, Docker/Compose qualification, full-diff review and develop
PR before deployment. Then use an explicitly public harmless query and a small
local workspace task through the normal worker; inspect actual source use and
output, preserve operator work/model state, and label fixture versus real proof.

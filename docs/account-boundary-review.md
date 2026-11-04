# Account boundary review

Reviewed for the 0.1 account cutover on 2026-10-30. The production switch is
tracked separately from implementation and verification. This review covers the
existing modular monolith; accounts are application identities, not Linux users.

## Operation policies

The inventory contains 222 HTTP operations, including 214 API operations, and
35 ORM tables. Authentication precedes request-body validation and dispatch on
every registered private API operation. The public exceptions are health,
authentication status, sign-in, sign-out and first-administrator setup. Documentation
and OpenAPI expose application schemas, not stored records.

| Surface | Boundary and verification |
| --- | --- |
| Accounts, devices and MFA | Explicit account services, current-device checks, bounded attempts, last-admin protection, local TOTP/recovery and offline recovery. `test_accounts*`, `test_account_mfa`, `test_account_offline_recovery`, `test_account_request_binding`. |
| Administrator inspection | Explicit, read-only selected-owner scope; no impersonation or secret resolution. Collections, messages, events, ranges and cached lookups: `test_account_inspection`. |
| Conversations, summaries and assistant tools | Scoped conversation/message/task/run references; ordinary history excludes inaccessible references. `test_account_private_api`, `test_account_search_preparation`, private repository tests. |
| Runs, events, SSE, approvals, retry and cancellation | Owner filtering before pagination and action lookup; SSE revalidates current devices; workflow cancellation follows only the owned graph. `test_account_stream_revocation`, `test_account_mutations`, worker/resource and runtime families. |
| Images, video, avatars, speech, music, transcription and uploads | Private Tasks/Runs/Artifacts, validated source references and app-relative paths; existing typed native APIs. Generic root/reference policy tests cover all private families. File/thumbnail/range and lineage requests are exercised over HTTP. |
| Library, lineage, Trash and permanent deletion | Owner predicates before counts/limits/joins; optimistic mutation locks; approved exact-snapshot purge. `test_account_library`, `test_account_mutations`, `test_artifact_purge`. |
| Memory, FTS and embeddings | Global memory scope means global within the current account. Typed index writes follow owner lookup; shared model readiness omits foreign activity. `test_private_data_access`, `test_account_embeddings`. |
| Agents, schedules, notices and drafts | Frozen owner on ordinary Runs; private source/project/tool references; disable/role changes stop only that account's authority. `test_account_agent_lifecycle`, `test_account_worker_resources`, worker and schedule families. |
| Projects, worktrees, previews and code/data jobs | Private project/worktree/run references; canonical native paths; owned workspaces. Arbitrary external repository registration and host-authenticated external coding/publication are administrator operations. The worker independently rechecks executor authority. |
| Providers, connectors, email and market data | Private records and references, account/record secret namespaces, server-only resolution; no host environment credential grant to a personal record. Repository, provider/connector and private API tests. |
| Model files, definitions, runtimes, GPU/RAM and telemetry | Shared physical infrastructure; fixed coordination projections exclude foreign prompt/log/Run data. Ordinary users can consume approved local models; configuration, process diagnostics and host-authenticated CLI catalogs require administration. Shared runtime, coding-model routing and revocation families. |
| Maintenance, snapshots, nodes and private remote access | Administrator-only HTTP operations plus live worker authority. Fixed machine transactions never become unrestricted SQL. Full-database artifacts additionally require current administrator status. `test_account_maintenance`, private-access/revocation/startup families. |
| Skills and capability catalogs | Shared installed instruction packs and platform capabilities; read-only endpoints do not grant tools, credentials or execution. |

`test_account_route_boundary` enumerates the current application schema and tests
anonymous denial and every registered administrator operation's member denial.
`test_private_data_access` enumerates mapped-table policies and all private roots,
checks inherited relationships, cached objects, references, FTS and forbidden raw
SQL. Dedicated A/B/admin HTTP tests exercise the important lifecycle families
above. These are complementary checks; route enumeration alone is not a claim
that each handler has a separate positive and negative test.

## Native and browser boundaries

The Host Runner keeps its private Unix socket and typed operations. Account
workers pass only records resolved inside their frozen owner scope. Python uses
the existing network-disabled, read-only container with only its frozen input
mount; browser containers receive neither the application data root nor Runner
socket. Existing native path, cancellation and process-ownership tests remain
applicable without GPU/model credentials.

An actual installed coding-sandbox probe passed: it could write its own workspace
but could not read/write a synthetic sibling user's file, escape through a symlink,
write Git metadata, connect to a listening TCP endpoint or connect to a private
Unix socket. No real credentials or user files were used. This qualifies that
installed sandbox; it is not a real external-agent or model inference test.

Compiled desktop/mobile browser checks cover setup/sign-in/security, account
changes and selected-owner inspection, including real file previews, focus and
overflow. Account changes clear private query/draft/preview state and fence late
requests; per-device logout does not cancel durable owned work.

## Preservation and evidence

A read-only backup of the live 0036 SQLite database passed upgrade to 0038 on a
private copy. Existing table content, IDs, paths and password records were retained;
all private roots received their owner and foreign-key validation passed. Additional
activation tests cover operator password/device changes after migration, revoked
sessions, ambiguous ownership and quarantined credentials.

Private logs, hashes, exact disjoint test cohorts, browser captures and image/API/
separate-worker receipts live under
`data/acceptance/account-ownership-20261030/`. They are not public screenshots or
sample user data. Real multi-account GPU generation is not claimed by fake-native
coordination tests. Production deployment and the overall 0.1 milestone require
their own receipts; this review does not complete the other release requirements.

# AI Station implementation handoff

The full-platform goal remains active. Prioritize useful local agents and the
conversation-first assistant, with good desktop/mobile UX. Standalone IDE expansion
is deferred. No subagents, unapproved downloads, driver changes, public exposure or
main/master operations. Preserve original root Memory WIP and all existing services.

## Live state and release authority

LAN UI: http://192.168.1.121:8765. Always read
`data/acceptance/safety-redeploy-20261012/deployment.json` and the corresponding
post-deployment qualification before relying on a release name or PID. #410 is the
previous qualified delivery; #411 is the selected-document increment. Consult
`data/acceptance/agent-document-context-20261024/post-deployment-qualified.json`
for actual #411 rollout. Source checkout `.tools/agent-document-context`, branch
`feat/agent-document-context`; deployment must use its own detached release worktree.

## Completed increment: selected documents

Read [document context](agent-document-context.md). Both agent editors upload/drop
PDF/UTF-8 text/Markdown or select from Library. The server freezes ordered Artifact
IDs/hash/size/MIME/name; migration 0035 preserves absent-scope legacy hashes. A fixed
CPU reader receives verified bytes and shares Stop/deadlines; owned kill/reap and
Linux parent-death behavior are tested. Full text/JSON artifacts retain provenance;
reports and local code see excerpts, offline Python sees complete captured text.
Goal-based media can use a selected brief. Report queries/windows stay in scope and
the exact later captures are visible. No native protocol or generated-code authority
changes; no OCR or pixel understanding is implied.

Full CPU/Runner suite: 3392 cases, 3383 passes/nine opt-in skips. UI:747 tests plus
format/lint/TS/build. Actual application-image PDF/text helpers, private 0034→0035
all-value/18-definition-hash migration, compiled 1440/390 editors/conversation/results
and two native offline Python jobs pass. Inference is injected; no new GPU work.
Final UI-only correction wraps long excerpts and has its own full UI/image/browser
checks; backend qualification is carried only with exact byte identity. Failed and
superseded harness evidence remains in the acceptance directory.

## Next useful increments

Broaden document reuse and agent creation from the main conversation using the
existing source-bound graph, rather than adding another execution system. Continue
practical multi-step local-agent composition, clearer capability discovery and
quality/reliability of existing media. Real operator-inbox delivery, actual Tailscale
enrollment/mobile remote acceptance, additional account integrations and execution
nodes remain separate requirements. Do not repeat existing real 60-second Wan,
30-second EchoMimic,27B/131k-context or installed 9B Vision acceptance because an old
plan labels them unfinished. Those qualify recorded profiles, not every quality case.

## Repository and verification rules

Root branch `feat/memory-scope-tagged-runs` and its dirty README/Memory/docs files
are preserved; work only in owned feature worktrees. Feature PRs target develop;
review the full diff and qualify the exact source before squash merge. Hosted
Actions are manual under AGENTS.md's local-check exception. `main`/`master` are never
push, merge or deployment targets. No actual test failures are waived.

Keep all state under app storage; canonical paths, typed Runner calls, app-relative
artifacts and Task→Run→Events→Artifacts remain fundamental. Use temporary DB/fake
inference in normal tests; label actual CPU/native/image/browser tests separately.
Legacy JSON optional defaults must remain omitted for old consent/receipt hashes.
Rollout requires a fresh SQLite backup, intact auth/IDs/agent due instants, no active
owned jobs, exact image/assets, unchanged native fingerprint and preserved model
container IDs. Restarts/deployments are authorized; do not ask again for ordinary
AI Station development restarts. Do not send real external email for QA.

Earlier history is retained in
[handoff history](implementation-handoff-history-20261024.md).

# Chat/Work and longer media: implementation handoff

Updated 2026-10-14. Implementation is active: the earlier planning-only request and
pause were explicitly superseded. Continue implementation; do not repeat delivered
slices. The live release/image/backup record is
`data/acceptance/safety-redeploy-20261012/deployment.json`; inspect it before deploying.

## Delivered conversation work

- #269: immediate first Send, transactional `/api/chat/turns`, UUID receipts,
  optimistic settings/provider guards, enforced Chat/Work policy, migration 0020.
- #270: separate System and Settings workspaces and typed operator preferences.
- #271: selecting a GGUF performs no inference; Send uses owned load prerequisites
  and discovered GPU indices, preserving larger Coding context requirements.
- #273: Work's Create project & build composes project setup, worktree and proposal,
  with explicit external sharing and typed cancellation of that known chain.
- #274: shared composer/shell, collapsed history/settings/tools, preserved reading
  position and Jump to latest, keyboard/IME behavior and independent Stop.
- #275: one searchable provider/model catalog, metadata-only selection and version
  guards. Installed local models are selectable without manually typing model IDs.
- #276: explicit owned-model thinking qualification, bounded Chat switch, separate
  reasoning events/metadata and collapsed trace; final content/context stay separate.
  Real isolated 9B Off/On and Chat passed. The deployed 9B qualification also passed.
- #277: session draft text, unchanged retry identity across refresh and protection
  of newer text during pending Send. Files/tools are explicitly reselected.
- Current history increment: cursor-paged older conversations and title/message
  search; see [history contracts](../chat-history.md) and acceptance evidence below.

The detailed original UX specifications remain in [chat-work experience](chat-work-experience.md)
and [delivery brief](2026-10-chat-work-media.md). They describe historical findings;
those findings are not proof that delivered APIs/components remain absent.

## Next implementation

1. **Contextual Work foundation is delivered:** [same-task continuation](../contextual-work.md)
   now shows project/executor/model and reuses owned worktrees with task-wide Stop.
   Next, extend explicit scope selection beyond the current conversation. Show the current project/task clearly, continue an existing
   owned worktree from subsequent prompts, allow explicit scope changes, and retain
   approvals/validation results. Do not infer permissions from conversation mode.
   Replace the known project-build cancellation chain with transactionally bounded
   task-graph Stop before advertising cancellation of arbitrary descendants.
2. **Automatic model routing:** use installed modality/context/resource observations,
   explicit provider/location policy and existing load/admission services. Never
   silently fall back to external AI. Show the actual executor/model per result.
3. **Long media:** follow [long-media contracts](long-media-execution.md): durable
   plan revisions/unique stage operation keys, existing RunDependency edges, aggregate
   job state, atomic Stop/resume, typed CPU composition with full decode/timing checks,
   GPU plus system-RAM admission. Then qualify Wan continuous/shots and full-audio
   avatar windows. The long-media branch now implements 5–60-second video and full-speech avatar
   job APIs, deterministic timelines, CPU composition and Stop/resume. See
   [implementation](../long-media.md). Real Wan acceptance is ongoing; do not
   claim it or full-avatar quality qualified until evidence is complete.
4. Broaden draft persistence to reviewed scope/attachment contracts if needed; keep
   the current text-only restore explanation and receipt compatibility. Do not cache
   credential values or large media request bodies in browser storage.

The remaining Work/media stages must create ordinary Runs/artifacts, support owned
cancellation/recovery and show partial/final outcomes in both Chat and dedicated tabs.
Planner success means plan prepared, never film finished or code verified.

## Preserved work and verification

The root checkout `feat/memory-scope-tagged-runs` at `6ba096d` has original Memory
UI/README/architecture/status WIP plus `docs/handoff.md`. Do not reset/stash/stage it.
`.tools/assistant-project-build` retains the original pre-adaptation WIP; the adapted
project-build feature was delivered as #273. Do not redo that original WIP wholesale.

Evidence folders under `data/acceptance/`:
`chat-first-turn-20261014`, `settings-separation-20261014`, `auto-model-20261014`,
`work-project-build-20261014`, `conversation-shell-20261014`,
`unified-model-picker-20261014`, `chat-reasoning-20261014`,
`chat-session-drafts-20261014`, `chat-history-20261014`.
Inspect the recorded final head/results, not a still-running log, before claiming
success. #276 passed 1024 Python tests (five opt-in skips), 383 UI tests, lint/types/
format/build/Compose/Docker and actual isolated 9B reasoning. #277 passed 387 full
UI tests plus five final draft tests and desktop/mobile simulated retry checks;
its backend/native code is identical to #276. Hosted Actions are manual under AGENTS.

Use focused feature branches/PRs to develop and successful local checks for the
reviewed head. Never push/merge main/master. Before applying a reviewed image,
backup the idle application's SQLite DB and preserve original record IDs. Keep a
healthy native Runner when its code is unchanged; upgrade this project's user
service when native code changes. No drivers, model downloads, external runtimes
or unrelated infrastructure changes are authorized by routine development.

2026-10-15 continuation increment: explicit existing-task selection in Work is
implemented on `feat/work-task-selection`, pending validation/review/deployment.
The picker searches task/project names, pages existing sessions and selects a
preserved owned workspace without execution. Migration 0022 stores the binding;
Task ownership/history is not moved. Normal follow-up validation, source-version
checks and per-turn external consent remain enforced. Blank-entry task selection
and broader orchestrated workflows remain separate increments.

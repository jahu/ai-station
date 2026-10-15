# Re-run Coding checks without invoking a model

## Verified baseline

Develop `71203e7` includes reviewed PR #314 (build ZIP Artifacts) and #315
(task-scoped Coding drafts and guarded keyboard Send). The combined image is
live at localhost:8765 from `.tools/ui-coding-conversation-drafts-20261015`.
Native Runner source is upgraded; original database IDs and root Memory WIP
are preserved. Checks: 1497 backend/Runner tests (five explicit opt-in skips),
472 frontend tests, lint/types/format/build, Docker/Compose, real native React
validation/export and desktop/mobile browser acceptance. The deployed API/worker
also ran the existing assistant-owned QA project's saved tests/build and produced
a verified downloadable archive, without inference or original-checkout changes.
Evidence: `data/acceptance/coding-build-artifacts-20261015` and
`data/acceptance/coding-drafts-20261015`.

## Current user-facing gap

Projects can run saved checks on an owned worktree, but that creates a separate
validation Task. Coding/Work review has no same-Task action to repeat an existing
turn's checks without invoking an agent. Old successful turns also cannot acquire
new build Artifacts without a new validation execution. Add **Run checks again**
with a clear promise: repeat the recorded commands, no model or dependency install.

## Contract

- Reuse `project_validation`, native owned-worktree/lock/process transport,
  permissions, resources, Stop and conservative recovery. HTTP only enqueues.
- Expose a typed Coding operation bound to an existing successful latest proposal
  and its current validation Run. The request carries the expected validation UUID;
  it does not accept commands, paths, permissions or model choices.
- Require the proposal/validation/project/worktree identities to agree, owned
  storage, no removed worktree, a completed earlier validation, no superseding
  proposal/repair and no active project Run. A committed proposal can be checked
  again if the worktree remains owned and ready.
- Require prior execution confirmed gone, or a demonstrably undispatched prior
  failure. Uncertain native ownership remains an inspection state; do not blindly
  repeat a possibly running external process.
- Repeat the last validation's frozen command list and optional manifest snapshot.
  Validate that the old validation is the ordinary source-child check Run and
  that its structure matches the existing trusted validation command contract.
  Do not silently replace commands from a new model plan. Changed dependencies
  fail the existing manifest check and require normal project preparation.
- The action is an explicit fresh user intent on the same Task. Record who
  requested it, preserve older check Runs and use an immutable `rerun_of` reference.
  Update the proposal's current validation pointer atomically with enqueue.
  Preserve all old result/artifact records. Clear a prior Task Stop only as part
  of this explicit fresh request, as the existing follow-up contract does.
- Serialize duplicate/stale requests before reading mutable state. A guarded
  no-op write/CAS on the source validation pointer can be the first DB statement;
  then serialize on the project row before checking project-active Runs. This
  prevents two accepted repeats and remains compatible with a later PostgreSQL
  repository implementation. Failed guards roll back without workload creation.
- Mark the new Run as manual checks only. In particular, failed checks MUST NOT
  trigger `queue_automatic_repair`, local inference or package installation even
  when the original coding task had an automatic repair budget. Snapshot that
  intent, remove an old agent deadline and use ordinary bounded native validation.
- UI enables the action only for an eligible terminal current validation, reports
  errors in place, preserves the current draft and refreshes source/task/query
  state. Show the queued Run and previous checks. Keep superseded results readable.
  Successful repeated build checks may produce a normal ZIP Artifact via #314.

## Verification

Use disposable repositories and fake executors for ordinary tests. Cover same
Task/worktree, frozen commands, no LLM/repair/dependency Runs on failure, stale and
concurrent duplicate requests, project-active/removed/superseded guards, uncertain
native ownership, Stop/fresh manual intent, retained history and build Artifact.
Frontend tests include in-place pending/error behavior and preserved draft/consent.
Run required full checks, review the complete PR to develop and merge locally
verified changes under the current manual Actions policy.

For opted-in real acceptance, repeat checks on the existing QA React Coding turn
through the normal deployed worker, with no inference or site regeneration. Its
last automatic validation is `5a2a78bf-17b6-4334-9ff8-35709f655448`, source proposal
`64fb729b-62dc-4df9-8ee9-619b5b7db4ee`, Task
`0d0e7756-2498-4482-bf08-2e96fabfa89d`. Re-read current state before acting.

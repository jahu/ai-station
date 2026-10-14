# Continue a project from Work

A conversation with coding history exposes its latest owned coding Task as a
compact context card: project, executor/model, workspace link and Continue task
or General Work. Subsequent Work prompts reuse that Task's branch/worktree and
proposal contract; no new repository or worktree is created. Chat and explicit
other actions leave coding scope. General Work/turn-mode choices and draft text
survive refresh in the current browser session. External consent is intentionally
scoped to the selected proposal and must be confirmed for the next prompt.

Turn requests have an optional typed `continuation` with Task ID, expected source
Run ID and explicit external sharing. The Task must belong to that conversation.
The existing coding continuation service checks current source, project activity,
owned workspace, confirmed process exit and effective permissions; model planning
cannot create this scope. A continuation is an ordinary coding Run with a new turn
receipt, parent source and the same Task. Its review/checks remain in the transcript
and Coding. Older request receipts without the new field remain compatible.

Coding Stop uses `POST /api/coding/sessions/{task_id}/cancel`: it records durable
Task cancellation and cancels up to 1024 active same-Task Runs through existing
owned-process contracts. Task-row locking serializes cancellation with child
publication. Worktree/proposal validation/automatic repair publication observes
the marker; generic Run creation rejects a stopped Task. Shared model-load Tasks
are independent and are not killed by this operation. A new validated follow-up
clears the marker only after the previous process/work is safely finished.
Manual commit/repair/publication cannot silently restart a stopped Task.

Verification: fake-provider API cases cover same-worktree continuation, receipt
replay, stale/cross-conversation scope, external disclosure, mixed-action rejection,
uncertain ownership and Stop versus concurrent child publication. Disposable real
Git worktrees with fake Cursor/Codex subprocesses verify cumulative source changes
while the original checkout is unchanged. No cloud inference is claimed. Desktop/
mobile Chromium verifies context, draft and scope/mode restore without API writes.
Evidence: `data/acceptance/contextual-work-20261014`.

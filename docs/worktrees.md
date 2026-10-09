# Owned worktree preparation

Projects can request a preparation Task/Run before coding execution is available. The worker dispatches a typed request to the native runner. The runner derives `ai/<run-uuid>-workspace` and `worktrees/<project-uuid>/<run-uuid>` itself; callers cannot choose a destination or a task branch. The selected local base branch is resolved to a commit at dispatch. Nothing is fetched.

A private runner manifest records the request before process launch. The existing ProcessManager owns the preparation process group, durable logs, cancellation, and restart inspection. Repeating an identical launch returns its recorded process; a mismatched request or a reservation without a process fails closed for inspection. No partial worktree, branch, or lock is automatically deleted.

The managed preparation job revalidates repository roots and its destination, disables Git hooks, filters, fsmonitor, recursive submodules, and sparse checkout, then runs `git worktree add` with a 120-second limit. Helper Git reads stay in the owned process group and retain their separate 15-second limits. Repositories with custom `core.worktree` are rejected. It verifies the new branch, common Git directory, and base commit before marking the manifest ready. The original checkout and its index are untouched; Git necessarily creates a new branch and linked-worktree metadata in the shared repository. See [Git worktree](https://git-scm.com/docs/git-worktree).

Preparation grants only filesystem read, workspace write, Git read, and Git write. It does not grant network access, project command execution, or external AI. Worker cancellation uses the existing owned-process endpoint. Unknown exit status, lost dispatch responses, and stale workers require inspection; this slice does not retry or adopt an orphan automatically. Completed worktrees are preserved and listed in Projects with their Run and relative path. That list is one keyboard sequence (arrows, Home, End, Enter inspects the preparation Run) with unique Inspect names; install, validate, keep and remove stay on the selected row.

## Explicit removal

**Remove worktree** queues a separate host Run. After confirmation it deletes only the recorded owned checkout and its local `ai/<run-id>-workspace` branch. The source repository, its current checkout and index, other worktrees, protected branches and GitHub remotes are left unchanged. Unregistered paths are never deleted. Callers cannot supply a destination or set an ownership flag: the runner uses the preparation manifest.

Removal holds the worktree and validation locks so an in-use checkout cannot disappear under coding, validation or dependency installation. A symlink at the owned path fails closed for inspection. Interrupted or canceled removal leaves remaining files for inspection; recovery never blindly repeats a delete. A later explicit request can finish an already-gone directory and missing branch. The registry keeps a tombstone (`removed_at`). Validation, coding follow-ups, dependency install and repair then fail closed.

## Automatic expiry

A successful preparation schedules removal seven days later. Coding, validation and dependency Runs refresh that deadline while `expires_at` is set. **Don't auto-remove** clears the deadline so only an explicit removal Run deletes the checkout. Worktrees recorded before this column existed keep `expires_at` empty and are never auto-deleted. The scheduler queues the same owned-process removal used by the Projects button: at most one due worktree per tick, never while the project has an active Run, never for unowned or already-removed checkouts. Recovery never deletes without that Run.

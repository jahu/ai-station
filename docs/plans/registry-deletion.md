# Remove agents and projects from the workspace

Agents and Projects support single and selected-page deletion, with a named confirmation dialog. Deletion is account-scoped, version-checked and transactional; an active Run prevents deletion. A batch validates every item before changing anything.

Migration 0043 adds nullable deleted_at tombstones. Deleted definitions disappear from lists and selectors and cannot be enabled, scheduled, retried or used for new work. Old Runs, artifacts, conversations, scoped memory and worktree provenance remain inspectable. Project removal pauses and unlinks live linked agents; repository folders and worktrees are never removed by this operation. Re-registering the same original repository is allowed under a new identity.

Database checks at new Task/Run/Agent/Worktree references prevent legacy retry/follow-up routes from creating work against removed definitions. Existing fixed worktree expiry housekeeping remains permitted. No execution authority, filesystem deletion or new Runner endpoint is added.

The workstation cleanup is a separate authorized operator operation: back up SQLite, pause existing schedules, then delete the frozen owner-owned inventory through the reviewed API after deployment. Preserve other accounts, original repositories, Library and execution history. Public releases and master are unaffected.

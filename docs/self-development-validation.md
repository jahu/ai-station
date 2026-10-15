# Full validation for AI Station self-development

Observed on the deployed `35ab4a4` release: the registered AI Station project has
only two `compileall` commands, no lint/build commands. Read-only automatic
planning of this repository returns no commands or dependency ecosystems. The
root pyproject contains tool settings, while pytest tests and the Node package
live below it; requirements-dev.lock is outside current manifest selection.
Evidence: `data/acceptance/self-development-validation-20261015/observed.json`.

This is not a failed real self-development feature task. It is a verified gap in
the checks that such a task would receive. The earlier documentation-only smoke
proved worktree isolation and syntax checks, not full application validation.

Implement a reviewed, frozen project validation configuration that can represent
component directories, development dependencies, Python source roots and sufficient
validation time. Preserve existing simple-project requests and manifest snapshots.
Start by inspecting existing manifest/dependency/sandbox contracts; extend them
instead of introducing a parallel self-development execution architecture.

AI Station's profile must run backend/Runner pytest and Python lint/format, plus
frontend lint, TypeScript, tests and production build against the allocated
worktree. Runtime/dependency preparation must be explicit and inspectable. Never
fall back to importing the active checkout's editable packages, and never mount
the Docker socket or grant arbitrary host command/filesystem access.

All component/source/manifest paths must be canonical relative worktree paths,
with symlink/escape protection and frozen hashes before execution. Agents cannot
rewrite trusted validation configuration mid-task. Preserve owned process groups,
Task Stop, deadlines, conservative recovery, reports, diffs and review. Consider
short owned temporary paths for tests that create Unix sockets without granting
general host temporary-directory access.

Use disposable repositories/fakes for policy, snapshot, import-source, timeout,
cancellation and legacy compatibility tests. Then execute full validation in an
isolated AI Station worktree and prove it uses changed worktree source. Preserve
the original checkout/index and all user data. No merge/restart of the application
is implied by a successful self-development task; deployment remains separately
controlled. Do not mark the whole platform complete from this one increment.

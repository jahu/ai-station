# Project validation and coding boundary

Saved project validation is operational. Coding agents remain unavailable until their provider permissions, tool isolation, cancellation and review paths are verified. An installed CLI or successful sandbox probe alone does not enable an agent.

## Validation workflow

From Projects, prepare an owned worktree, configure trusted argv test/lint/build commands, then choose **Run saved validation**. The API accepts the worktree ID and expected project version; it snapshots commands from saved project configuration. It does not accept replacement commands or host paths. A normal Task and host Run require `filesystem_read`, `workspace_write`, `git_read`, and `shell_project_commands`. One project Run can be active at a time.

The native runner revalidates the preparation manifest, project, task branch, base commit and common Git directory. It records an immutable request outside the writable worktree and dispatches an owned process group. Replayed dispatch returns the same process; changed requests or an uncertain prior dispatch require inspection. A native file lock also prevents concurrent validation of one worktree.

Each command executes as an argv array through the installed Cursor `cursorsandbox` helper with a fixed policy: workspace writes, read-only Git metadata and agent configuration, minimal system runtime reads, no network and no global temporary writes. No arbitrary shell endpoint or caller-selected sandbox policy is exposed. Direct shell/privilege-tool executables are rejected. Project scripts are trusted saved configuration and remain confined by the same sandbox.

The command environment contains only fixed runtime settings. Home and temporary storage point to a fresh directory inside the worktree; provider credentials and inherited runner variables are absent. Dependencies outside the workspace/system runtime paths, including symlinked external virtual environments, are inaccessible. Scratch data stays in the worktree for inspection. Install declared Python dependencies with a separate Run before validation if the worktree environment does not already contain the packages.

## Dependency installation

From Projects, choose **Install project dependencies** on a prepared owned worktree. The API accepts the worktree ID and expected project version. It does not accept pip arguments, index URLs or host paths. A normal Task and host Run require `filesystem_read`, `workspace_write`, `git_read`, `shell_project_commands` and `network_read`. One project Run can be active at a time. The same worktree lock used by validation and removal prevents concurrent mutation.

The native runner revalidates the preparation manifest, creates a worktree `.venv` when missing, and refuses symlink environments. It reads `requirements.txt`, or `pyproject.toml` `[project.dependencies]` when that file is absent. Specifiers must be ordinary package pins or relative `.whl` paths inside the worktree. URLs, VCS references, editable installs, extra indexes and pip flags are rejected. A regular `vendor/` directory of wheels selects an offline install (`--no-index --find-links=vendor`). Otherwise pip uses `--index-url https://pypi.org/simple` after `pypi.org` and `files.pythonhosted.org` resolve to public addresses. Both modes run `python -m pip install --isolated --require-virtualenv --only-binary :all:` through the Cursor sandbox helper. Vendor installs keep sandbox network disabled. PyPI installs grant sandbox network only for that command and add TLS/resolver system paths; they still cannot write Git metadata or global temporary directories.

Limits: ten minutes and 2 MiB combined output. Timeout/output violations terminate the owned group. Cancellation uses the normal runner ownership checks. Recovery never automatically repeats an install after uncertain dispatch because pip can modify the environment. Known completion produces a JSON artifact and a `dependencies.completed` event. Arrow keys move through that install result on the Run; there is no inspectable child Run. A nonzero pip exit fails the Run while preserving the report. Unknown exit status, cancellation or wrapper failure cannot become success.

Normal CI installs a disposable local wheel through a fake sandbox helper. It does not contact PyPI. Parser, plan and public-DNS unit tests cover PyPI mode without a live download. Real PyPI downloads are not claimed.

Limits: five minutes and 2 MiB combined output per command, fifteen minutes total, at most sixty commands and 32,000 argument characters. Timeout/output violations terminate the owned group. Cancellation uses the normal runner ownership checks and TERM/KILL grace period. Recovery never automatically repeats validation after uncertain dispatch because test/build scripts can modify workspace files.

Known completion produces a JSON artifact, per-command events and a visible result list in Run detail. Arrow keys, Home and End move through those commands; there is no inspectable child Run. Nonzero command exits fail the Run while preserving the report. Unknown exit status, cancellation or wrapper failure cannot become success. All commands are attempted after ordinary nonzero exits; a sandbox/wrapper limit stops the job. The original checkout, Git index and protected branches stay untouched.

## Evidence and limitations

On 2026-09-26, disposable real Cursor sandbox probes allowed workspace writes while denying outside reads/writes, writes to the worktree `.git` and common Git config, global `/tmp` writes, and a connection to the existing loopback model server. Real managed validation passed success, nonzero-exit and cancellation cases. No model, cloud token or coding-provider credential was used.

Normal CI uses a fake helper and disposable repositories to verify queueing, saved-command snapshots, stale edits, ownership, permission checks, idempotence, logs/artifacts, failure, cancellation, limits and environment isolation. Dependency install coverage uses a disposable local wheel rather than PyPI. To repeat the managed-process tests against an installed native helper:

```bash
AI_STATION_REAL_SANDBOX_TESTS=1 .venv/bin/python scripts/coding_sandbox_smoke.py
AI_STATION_REAL_SANDBOX_TESTS=1 .venv/bin/python -m pytest -q backend/tests/test_projects.py -k 'validation_reports or validation_runner or validation_limits or validation_does_not_inherit'
```

The installed Codex sandbox separately failed a read-only probe with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. No OS/AppArmor setting was changed. Cursor validation isolation does not prove that Cursor CLI built-in tools, plugins or provider authentication meet the coding-agent contract; unrestricted CLI tool execution remains disabled. The separate [bounded Cursor proposal adapter](coding-cursor.md) uses an empty workspace and no enabled provider tools.


Each validation command receives its own exclusive policy file outside the writable worktree. The installed native sandbox consumes this file at launch; the original request policy remains as audit evidence. Test/lint/build sequences therefore retain the same restrictions for every command, including commands after a failed check.

Repository exploration may ask for at most two corrections when a local model
returns a declared read-only operation with missing/extra keys, or omits the tool
name. Invalid requests are recorded as failed tool events and feedback, and count
against the existing exploration request budget. They are never executed or
coerced into a guessed operation. Unknown/disallowed tools, unsafe paths and
invalid argument values still fail closed. This addresses the observed missing
`tool: finish` in the real local Work continuation; it does not grant new tools.

## Next increment: automatic preparation and checks for managed projects

This is planned work, not an operational claim. Name-only projects currently save
empty validation commands, and applying a coding proposal does not automatically
install its newly declared dependencies. The next increment must close that full
happy path for Coding, Work, continued tasks and persistent coding agents.

Persist explicit automatic dependency/check policies on Projects with an Alembic
migration. Existing registered projects and old snapshots retain their manual
behavior. New managed-project UI defaults can enable the policies with concise
public-registry/isolation disclosure; the creation request must carry the choice.
Expose overrides in advanced settings. Freeze policy and project revision on Send
and agent launch; untrusted model plans cannot grant installation/network access.

Compose ordinary child Runs on the same Task: proposal → dependency preparation
when required and authorized → validation → review. A dependency failure, Stop,
expired deadline or uncertain recovery must prevent later execution. Preserve
source proposal and dependency artifacts. Reuse the tested native installers and
sandbox; do not introduce an arbitrary command endpoint or silently weaken checks.
Manually configured test/lint/build argv remain authoritative. When automatic
checks are explicitly enabled and none are saved, native bounded inspection may
choose known checks from actual project manifests, such as npm run build/test;
report the exact chosen commands and distinguish absent tests from passing tests.
Do not silently report success for an app that was never built or tested.

Acceptance must include frozen permissions/revisions, old-receipt compatibility,
Stop across all descendants, failure gating, approval/recovery, and actual
one-conversation creation/coding/dependency/build with a local long-context model
in a disposable repository. Keep external-provider consent independent. The real
React/Vite fixture qualification in #310 proves the installer/build boundary;
it does not prove this automatic LLM-driven chain yet.

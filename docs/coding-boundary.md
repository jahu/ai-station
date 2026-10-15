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

## Automatic preparation and checks for managed projects

Project policies `auto_install_dependencies` and `auto_validate` are persisted by
migration 0025 and snapshotted on each coding turn/agent launch. Existing projects
and old queued snapshots default to manual behavior. New managed-project UI
requests explicitly enable the policies and disclose public package preparation;
advanced settings can override them. New managed projects default to Local AI.

After a proposal succeeds, an ordinary read-only `project_plan` Run asks the
private Runner to inspect bounded regular manifests and test filenames in the
verified owned worktree. It publishes sequential Python/Node dependency Runs
when authorized, then a validation Run gated on every prerequisite. The original
Task, proposal, file diff and artifacts are retained. The model cannot supply
installation policy or arbitrary automatic commands. Exact saved commands stay
authoritative; otherwise opted-in checks use fixed npm test/lint/build or actual
Python test-discovery presets. Missing tests remain explicit warnings.

Manifest hashes (including absence) bind planning, installation and validation.
Changed manifests, failed prerequisites, Stop, expiry or uncertain execution
prevent later work. Reviewed commits require successful preparation, dependencies
and any detected checks. Native planning is bounded metadata inspection; it does
not launch a project process. Workloads remain managed typed native jobs with
existing process ownership and private sandbox contracts.

The real React 19/Vite 7 fixture passed the automatic same-Task plan/install/build
chain, lifecycle suppression, outside-read/Git-write denial and original-checkout
preservation. Its coding source was synthetic, not generated by an LLM. Evidence:
`data/acceptance/coding-auto-project-checks-20261015/real-result.json`. Full local
model conversation acceptance remains separate until that exact test executes.


Manual project validation still uses explicitly saved commands. Automatic discovery
currently inspects root manifests and root/tests test files; nested workspace
package managers and arbitrary script/command generation are not inferred.

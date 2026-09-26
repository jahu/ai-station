# Project validation and coding boundary

Saved project validation is operational. Coding agents remain unavailable until their provider permissions, tool isolation, cancellation and review paths are verified. An installed CLI or successful sandbox probe alone does not enable an agent.

## Validation workflow

From Projects, prepare an owned worktree, configure trusted argv test/lint/build commands, then choose **Run saved validation**. The API accepts the worktree ID and expected project version; it snapshots commands from saved project configuration. It does not accept replacement commands or host paths. A normal Task and host Run require `filesystem_read`, `workspace_write`, `git_read`, and `shell_project_commands`. One project Run can be active at a time.

The native runner revalidates the preparation manifest, project, task branch, base commit and common Git directory. It records an immutable request outside the writable worktree and dispatches an owned process group. Replayed dispatch returns the same process; changed requests or an uncertain prior dispatch require inspection. A native file lock also prevents concurrent validation of one worktree.

Each command executes as an argv array through the installed Cursor `cursorsandbox` helper with a fixed policy: workspace writes, read-only Git metadata and agent configuration, minimal system runtime reads, no network and no global temporary writes. No arbitrary shell endpoint or caller-selected sandbox policy is exposed. Direct shell/privilege-tool executables are rejected. Project scripts are trusted saved configuration and remain confined by the same sandbox.

The command environment contains only fixed runtime settings. Home and temporary storage point to a fresh directory inside the worktree; provider credentials and inherited runner variables are absent. Dependencies outside the workspace/system runtime paths, including symlinked external virtual environments, are inaccessible. AI Station does not install dependencies or weaken isolation to make tests pass. Scratch data stays in the worktree for inspection.

Limits: five minutes and 2 MiB combined output per command, fifteen minutes total, at most sixty commands and 32,000 argument characters. Timeout/output violations terminate the owned group. Cancellation uses the normal runner ownership checks and TERM/KILL grace period. Recovery never automatically repeats validation after uncertain dispatch because test/build scripts can modify workspace files.

Known completion produces a JSON artifact, per-command events and a visible result list in Run detail. Nonzero command exits fail the Run while preserving the report. Unknown exit status, cancellation or wrapper failure cannot become success. All commands are attempted after ordinary nonzero exits; a sandbox/wrapper limit stops the job. The original checkout, Git index and protected branches stay untouched.

## Evidence and limitations

On 2026-09-26, disposable real Cursor sandbox probes allowed workspace writes while denying outside reads/writes, writes to the worktree `.git` and common Git config, global `/tmp` writes, and a connection to the existing loopback model server. Real managed validation passed success, nonzero-exit and cancellation cases. No model, cloud token or coding-provider credential was used.

Normal CI uses a fake helper and disposable repositories to verify queueing, saved-command snapshots, stale edits, ownership, permission checks, idempotence, logs/artifacts, failure, cancellation, limits and environment isolation. To repeat the managed-process tests against an installed native helper:

```bash
AI_STATION_REAL_SANDBOX_TESTS=1 .venv/bin/python scripts/coding_sandbox_smoke.py
AI_STATION_REAL_SANDBOX_TESTS=1 .venv/bin/python -m pytest -q backend/tests/test_projects.py -k 'validation_reports or validation_runner or validation_limits or validation_does_not_inherit'
```

The installed Codex sandbox separately failed a read-only probe with `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. No OS/AppArmor setting was changed. Cursor validation isolation does not prove that Cursor CLI built-in tools, plugins or provider authentication meet the coding-agent contract; that adapter remains disabled.

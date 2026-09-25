# Security model

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Coding/agent modules remain preserved drafts; their workload APIs are not enabled yet. See README for runnable commands and limitations.


AI Station is a single-user workstation application. The default network exposure is loopback only. There is no authentication on that localhost MVP. Do not publish port 8765 on a LAN or the public internet until authentication exists.

## Control plane

Containers run without `--privileged`, without extra capabilities, and without `/var/run/docker.sock`. The only host mounts are the application data directory and the Host Runner socket directory. Compose sets `user` to the host uid/gid so a mode `0600` socket works without making it world-writable. The socket directory itself is the per-user runtime dir (`0700`).

The process inside the container listens on all container interfaces so Docker can proxy `127.0.0.1:8765`. The host publish address is `127.0.0.1`.

## Host Runner

The runner is a user-level process. It does not use sudo. It binds a Unix socket created with mode `0600` and does not listen on TCP in this version.

There is no `POST /shell`. Each operation has a schema. Subprocesses are started with an argv array (`shell=False`) in a new session so cancellation signals only that process group.

## Filesystem

Allowed roots come from configuration: application data, model roots, and project roots. The runner resolves canonical paths and rejects:

- `..` segments
- absolute paths that escape a root after symlink resolution
- symlink components whose target leaves the root
- null bytes and non-normalized absolute injection

Project commands are the argv lists stored on the project. The runner refuses `shell=True`, `sudo`, and shells invoked as the executable (`bash`, `sh`, `zsh`). Agents cannot replace those commands during a run.

## Git

Coding work happens in a fresh worktree and a new `ai/...` branch. The user's current checkout is not the cwd of an agent. Protected branches reject automatic commits, pushes, history rewrites, and merges. Force-push is not implemented. Push and opening a pull request require an approval record. Applying or restarting a changed AI Station checkout is not automatic.

## Permissions

Runs store an effective permission list. There is no universal full-access flag. Profiles grant named capabilities (`filesystem_read`, `workspace_write`, `git_read`, `git_write`, `network_read`, `network_external`, `shell_project_commands`, `external_ai`, and others). Missing permission fails the tool call.

## Network tools

HTTP fetch is a real tool and is off unless the run has `network_read` (GET) or `network_external` (POST). URLs are resolved and rejected when any address is loopback, private, link-local, reserved, or multicast. That blocks trivial SSRF to the host's model servers and cloud metadata endpoints. Web search and browser automation stay unavailable until a real provider is configured. They are not stubbed as success.

## Secrets

Secrets are environment variables or files outside Git. Database rows store references. Logs, events, errors, and prompts pass through a redactor for common token patterns. Connector responses omit secret values.

## External runtimes

Discovered llama.cpp, Ollama, or ComfyUI processes are `external`. Discovery never stops, restarts, or rewrites them.

## Autonomy

Agent drafts are created disabled. The UI shows prompt, tools, permissions, and schedule before enablement. Sensitive side effects pause in `waiting_for_approval`.

## Image boundaries

The typed photo endpoint accepts bounded values and writes the fixed UUID path for its Run. Sources must be validated images inside artifact storage, without symlink redirection. Uploads are bounded by request/file size and decoded image dimensions; HTML/SVG are not accepted as images. Artifact delivery uses canonical data-root paths and nosniff headers. Draft filesystem/Git mutation adapters remain disabled; owned worktree preparation has a separately validated endpoint described below.

## Read-only Git inspection

The enabled validation/status/diff endpoints use a separate bounded inspection adapter. It rejects option-like revisions, resolves branch/commit identifiers before diffing, clears inherited Git environment overrides, and disables repository fsmonitor commands, filters, text conversion, external diff helpers, hooks, and optional index writes. Git can otherwise run configured helpers even during inspection; see [Git diff options](https://git-scm.com/docs/git-diff#Documentation/git-diff.txt---no-ext-diff) and [fsmonitor configuration](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefsmonitor).

Worktree roots, common Git metadata, and object stores must resolve inside configured roots. Repositories using alternate object stores or partial-clone fetch configuration are rejected in this slice. Inspections stop after 15 seconds per subprocess or 2 MiB combined output; failure terminates only the owned command group. Simple branch names and commit IDs are accepted as diff bases; revision expressions are not accepted. Draft Git mutations remain disabled and do not share the inspection adapter.

Project registration uses this inspection boundary before storing a canonical host path. The control plane never opens repository files directly. Configuration updates keep mandatory protected branches and reject stale versions or active project Runs. Stored argv commands and optional task-branch policy preferences do not expose a command, commit, push, or PR endpoint. Worktree preparation uses a separate typed Run endpoint with derived paths/branches, a durable runner reservation, explicit capability permissions, and owned-process cancellation. See [Projects](projects.md).

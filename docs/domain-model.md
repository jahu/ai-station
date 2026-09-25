# Domain model

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation is enabled through the worker and a managed native process. Coding-agent/agent modules remain preserved drafts; their workload APIs are not enabled yet. See README for runnable commands and limitations.


## Task

A task is user intent: a prompt, a routed capability, and optional links to a project, conversation, or agent. A task does not execute anything by itself. It owns one or more runs.

## Run

A run is one execution attempt.

Identity and classification: `id`, `task_id`, `run_type`, `capability`, `executor_type`, `execution_target`.

Lifecycle timestamps: `created_at`, `queued_at`, `claimed_at`, `started_at`, `finished_at`, `cancellation_requested_at`.

Placement: `worker_id`, `runner_id`, `pid`, `process_group_id`, `requested_resources`, `allocated_resources`, `requested_gpu`, `actual_gpu`.

Payload: `parameters`, `effective_permissions`, `metadata`.

Outcome: `status`, `error_type`, `error_message`, `stdout_log`, `stderr_log`.

Links: `project_id`, `agent_id`, `conversation_id`, `parent_run_id`, `triggered_by`.

Recovery: `lease_expires_at`, `retry_class` (`safe`, `inspect`, `external`).

### States

`queued`, `claimed`, `preparing`, `running`, `waiting_for_approval`, `succeeded`, `failed`, `cancel_requested`, `canceled`, `interrupted`.

Transitions are explicit and tested. Terminal states are `succeeded`, `failed`, `canceled`, and `interrupted`. Recovery may requeue only from `interrupted` when `retry_class` is `safe` and no external process was started.

## Run events

Append-only records (`run.created`, `stdout`, `tool.completed`, `approval.requested`, `artifact.created`, and the rest of the execution timeline). Logs are not a substitute for events. Token and log chunks are events so the UI can replay a run after a restart.

## Artifact

A typed output of a run: `image`, `video`, `audio`, `text`, `markdown`, `json`, `code_patch`, `git_diff`, `document`, `log`, `archive`.

AI Station-owned bytes live under the data root with a UUID filename. `original_filename` is metadata. `parent_artifact_ids` links edits and upscales to their sources. External model files are never copied in as artifacts.

## Project

A registered Git repository: path, default branch, integration branch, protected branches, preferred executor, argv test/lint/build commands, agent rules, and PR policy.

## Worktree

An AI Station-owned checkout under `worktrees/`. Branch names look like `ai/<run-id>-<slug>`. The registry is the ownership record. Unregistered worktrees are never deleted.

## Conversation and message

Chat is durable. A completion is also a run. The prompt window is the recent messages, the latest rolling summary, and pinned memory.

## Agent definition

A persistent agent: goal, system prompt, provider, model, tools, skills, memory scope, trigger, permission profile, execution target, limits, and enablement. Enabling is explicit. Drafts are stored disabled.

Triggers that exist: `manual`, `cron`, `interval`, `one-shot datetime`. Unimplemented triggers are not presented as working.

## Approval

A pause record for a sensitive action: action, reason, risk, requesting run, timestamps, and resolution. The run waits in `waiting_for_approval`.

## Memory

Scoped (`conversation`, `agent`, `project`, `global`) and typed (`fact`, `decision`, `preference`, `project_context`, `summary`, `observation`, `procedure`). Every entry has provenance (run, conversation, message) and can be edited, pinned, disabled, or deleted. Search uses SQLite FTS5 plus scope, tags, and recency.

## Model file, definition, runtime, instance

These are different records.

- A **model file** is a discovered file in a configured root.
- A **model definition** is a logical model (family, capabilities) that may point at files.
- A **runtime** is an engine (llama.cpp, photo_pipe, stable-diffusion.cpp).
- A **runtime instance** is a process or endpoint, marked `external` or `managed`.

External instances are never killed or reconfigured.

## Resource lock

A coarse lease such as `gpu:<index>`. The first scheduler policy is one heavy image job per GPU. Chat does not take that lock, because an external model server is shared with the rest of the machine.

## Connector

Metadata for an external system: status, capabilities, non-secret configuration, and a secret reference. Secrets are not returned by the API.

## Scoped memory integration

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred.

# Domain model

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation is enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents use disabled drafts, explicit activation, persistent schedules, bounded context tools, sequential or gated workflow steps and optional bounded registry tool calling. Bounded Cursor file-edit proposals, review artifacts and separate validation Runs are operational. Other coding adapters remain inactive. See README for runnable commands and limitations.


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

AI Station-owned bytes live under the data root with a UUID filename. `original_filename` is metadata. `parent_artifact_ids` links edits, speech, avatars and upscales to their sources. Library lineage resolves those parents and the reverse derived set without creating a Run. External model files are never copied in as artifacts.

## Project

A registered Git repository: path, default branch, integration branch, protected branches, preferred executor, argv test/lint/build commands, agent rules, and PR policy.

## Worktree

An AI Station-owned checkout under `worktrees/`. Branch names look like `ai/<run-id>-<slug>`. The registry is the ownership record. Unregistered worktrees are never deleted. Explicit removal records `removed_at` and does not delete the user's checkout or GitHub remotes.

## Conversation and message

Chat is durable. A completion is also a run. The prompt window is the recent messages, the latest rolling summary, and pinned memory.

## Agent definition

A persistent agent: goal, system prompt, provider, model, tools, skills, memory scope, trigger, permission profile, execution target, limits, workflow mode (`sequential` or `gated`), tool calling (`none` or `bounded`), retry policy, notification policy, and enablement. Enabling is explicit. Drafts are stored disabled. A launch snapshots the step list and publishes child Runs with `RunDependency` edges; the model cannot invent extra steps. Bounded tool calling during the report may request selected registry tools only. Retry never requeues the same Run. Notices are in-app records, not email.

Triggers that exist: `manual`, `cron`, `interval`, `one-shot datetime`. Unimplemented triggers are not presented as working.

## Skill

A versioned `SKILL.md` instruction pack under the skills root. Agents store selected ids; Runs snapshot hashes and inject the text. Skills are not executables and do not grant permissions.

## Approval

A pause record for a sensitive action: action, reason, risk, requesting run, timestamps, and resolution. Agent Runs that require approval wait in `waiting_for_approval` until granted (re-queued) or denied (canceled). GitHub publication still records a granted approval at enqueue time.

## Notice

An in-app record from a saved agent notification policy: agent, run, kind (`succeeded`, `failed`, `interrupted`, `waiting_for_approval`), title, body and optional `read_at`. Email and other connectors are not used.

## Memory

Scoped (`conversation`, `agent`, `project`, `global`) and typed (`fact`, `decision`, `preference`, `project_context`, `summary`, `observation`, `procedure`). Every entry has provenance (run, conversation, message) and can be edited, pinned, disabled, or deleted. Search uses SQLite FTS5 plus scope, tags, and recency.

## Model file, definition, runtime, instance

These are different records.

- A **model file** is a discovered file in a configured root.
- A **model definition** is a user-curated logical model (family, capabilities, load preset) that points at one observed file. Discovery never creates it. Explicit installation verifies the local file and, for llama.cpp, an already-installed image; it does not download weights.
- A **runtime** is an engine (llama.cpp, photo_pipe, stable-diffusion.cpp).
- A **runtime instance** is a process or endpoint, marked `external` or `managed`.

External instances are never killed or reconfigured.

## Resource lock

A coarse lease such as `gpu:<index>`. The first scheduler policy is one heavy image job per GPU. Chat does not take that lock, because an external model server is shared with the rest of the machine.

## Connector

A named external system: kind, status, health, capabilities, non-secret configuration, secret reference and enablement. Operational kind is HTTP GET of one reviewed public URL. Health checks are ordinary Runs. Secrets are not returned by the API. Browser, GitHub, email, calendar and social kinds stay unpublished.

## Maintenance

`GET /api/maintenance` is an inspect-only upgrade-readiness snapshot. SQLite backups are ordinary Runs with verified artifacts. `GET /api/maintenance/backups/{run_id}` re-checks a successful copy read-only. The listing exposes the SQLite artifact for download without restore. `GET /api/maintenance/image` compares `ai-station:local` with running compose containers and does not apply an image. Restore and image rollout are unpublished; see [operations](operations.md).

## Operator access and nodes

The `operator_auth` setting stores PBKDF2 material for a local operator password. `operator_session` stores the HMAC, issue time, last-seen time and absolute expiry of the loopback session cookie. Idle timeout is 30 minutes; absolute limit is 12 hours. Both are control-plane secrets, not Runs. `StationNode` records pending, registered or revoked remotes with hashed one-time invitation tokens. The local Host Runner is synthesized, not stored. LAN listeners stay unpublished; see [nodes](nodes.md).

## Chat provider

A selectable OpenAI-compatible endpoint: key, name, local or external location, URL without credentials, optional secret reference, and enablement. The built-in local provider is seeded from environment settings. Conversations store the provider key; Runs snapshot the endpoint and secret reference, never the secret value.

## Scoped memory integration

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred. Curated definitions, load presets and explicit local installation are separate records and Runs.


`ConversationSummary` records an incremental coverage boundary, exact message sources, preceding summary, source Run and editable scoped Memory entry. Removing memory clears its reference; historical provenance remains.

## RunDependency

A composite (run_id, prerequisite_id) edge orders Runs, including shared model loads across Tasks. Edges are added only to queued Runs, reject cycles, and are separate from parent_run_id. Dependencies survive restarts; all prerequisites must succeed before execution.


### EmailDelivery (migration 0030; qualification pending)

A frozen operator message bound to one Run: durable client identity, sender and
recipient scope, complete preview, payload hash, message ID, SMTP configuration
snapshot, submission state and accepted/refused recipients. Approval binds the
hash; uncertain submission is inspection-only. History survives connector removal.
SMTP acceptance is recorded separately from inbox delivery, which is not claimed.

The market-email candidate stores its optional typed delivery scope in the existing
Agent.market JSON and its version nonce in Connector configuration. Existing
nullable-Run Approval records persist explicit activation grants; ordinary
EmailDelivery records reference the alert, consent and fixed template in their
frozen payload, using a stable UUID derived from MarketAlert identity. No new
column or schema migration is introduced by this increment. Parentage/provenance
and a report dependency keep mail children in the existing Task graph.

Agent `schedule_timezone` is a persisted IANA identifier, default UTC for existing
records and API clients. Cron uses local calendar minutes; `next_run_at` remains
an absolute UTC instant. The frozen Run definition retains the reviewed zone.
Interval durations and explicit-offset one-shot timestamps remain unchanged.

Natural data follow-ups store a controller-owned `data_reference` in Run parameters
and matching `conversation_reference` (`source_kind=analyzed_data`) on the user
message. It binds original input IDs/inspection snapshots, source user/Run and
bounded prior question/result context. These are portable existing JSON fields;
no schema migration or persisted Agent is required.

## Agent document context

Migration0035 adds nullable Agent.documents JSON. Its ordered unique artifact_ids
and frozen snapshots bind up to four selected original Artifacts by SHA-256, size,
MIME and display name. None is omitted from AgentSettings serialization so old
workflow, receipt and consent hashes retain their original identity. Each ordinary
read_documents context Run owns extracted text and a JSON capture, with explicit
parents and extraction/truncation metadata. A shorter observation is supplied to
models; offline Python can adopt the verified complete capture. Tool-call windows
are stored with the report's exact recorded call and capture artifact.

## Conversation-selected documents

DataScope.documents is an optional AgentDocumentScope, bound to the submitted user
message and orchestration parameters. Absent scope is omitted to preserve existing
request/receipt identities. A shared ordered context-tools method allows seven
optional data files plus one complete captured-JSON input. Context-free creation
rejects selected documents. No new database table/column or Agent row is required.

## Repeated-analysis draft provenance

Optional controller-owned data_agent_source metadata binds the current user message,
orchestrator and agent_draft child to a completed original analysis and its exact
source definition, input snapshots, result hash and artifact manifests. It is not a
model/request field and grants no tools by itself. Identity/schedule proposals cannot
rewrite the frozen scope. The definition Artifact retains source/result parents.
No database migration is needed; ordinary drafts and request hashes stay unchanged.

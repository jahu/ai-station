[Optional bounded avatar loading](plans/echo-memory-loading.md) reuses the
existing native ProcessManager, fixed private11-GiB/zero-swap scope and ordinary
media Task graph. Complete existing weights retain full precision; no upstream
files or public command/memory controls are added. Default native arguments are unchanged; new Standard jobs reserve the observed
loader requirement before launch.

[One bounded local-agent correction](plans/agent-validation-repair.md) reuses
the existing validation-repair engine when saved automatic project checks are
enabled. The original deadline, commands, source scope and failed history remain.

[Reviewed research before local agent code](plans/agent-research-coding.md)
reuses the existing source-bound context handoff, public tools and isolated
workspace. One reviewed definition and deadline bind every child.

# Execution model

The existing Python contract may freeze optional output names separately from
required files. Collection after confirmed script exit accepts a required prefix
followed by the present ordered subset of optional names, under the same count,
size, identity, cleanup and deadline constraints. Absent optional files are normal;
invalid files fail. Normal data result/repair and history retain captured extras.
Feature negotiation and empty-default serialization preserve old images/records.

Optional chart/workbook/report names are frozen on the local data generation Run
before the existing Python dispatch. All declared files are mandatory in the
typed request and owned completion report. The result worker validates table/CSV
and every optional export before publishing usable files; failures use the same
bounded repair and original deadline. Legacy two-file requests remain valid.
The installed Python image advertises export support without starting a workload.

The [agent Python executor](agent-python-execution.md) uses ordinary container-target
Runs dispatched by the native Runner. Source/input snapshots, bounded script logs,
required output validation, exact container cleanup, task cancellation and
conservative lease inspection are part of that same Run lifecycle.

Planned extension: [conversation-first and long-media delivery](plans/2026-10-chat-work-media.md).
The [long-media contract](plans/long-media-execution.md) reuses durable Run
dependencies for bounded segments and CPU composition, adds idempotent stage
publication and task-wide Stop/resume, and distinguishes plan-prepared from final
artifact success. It specifies RAM-aware admission and qualified two-GPU shot
concurrency. These are design requirements, not implemented execution behavior.

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation is enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents use disabled drafts, explicit activation, persistent schedules and bounded context tools. Bounded Cursor file-edit proposals, review artifacts and separate validation Runs are operational. Other coding adapters remain inactive. See README for runnable commands and limitations.


## Path

### Planned segmented media extension

The [long-media design](plans/long-media-execution.md) is not yet operational.
It composes normal Runs through existing RunDependency: prepare canonical inputs,
generate bounded segments, compose on CPU, fully decode/verify, adopt a final
artifact. The planner releases its worker slot after publishing the durable graph.
Task success waits for the selected attempts' final verified output, not planner
success. Atomic graph cancellation and resumable stage identities require new
tested contracts; existing single-Run Stop is not evidence that they exist.
RAM and GPU admission must be atomic and release only after owned process exit.
Completed segments are reusable only with authoritative completion and matching
input/profile hashes. See the [implementation handoff](plans/implementation-handoff.md)
for delivery order and the distinction between short-clip and long-output acceptance.

### Current execution path

1. The UI or scheduler creates a task and a `queued` run.
2. The worker heartbeats, recovers stale leases, then claims one queued run in an immediate SQLite transaction.
3. The worker reserves resources (GPU lock for image runs).
4. The executor validates and prepares, then runs on a target.
5. Events and artifacts are persisted.
6. Resources are released. The run ends `succeeded`, `failed`, `canceled`, or `interrupted`.

HTTP handlers do not generate images, run coding agents, or execute agent loops.

The worker service supervises three independent execution slots by default.
`AI_STATION_WORKER_SLOTS` accepts 1–8; set it to 1 for serial execution.
Each slot runs in a spawned process with its own database sessions, executor
instances, worker identity and lease renewals. A long media Run therefore leaves
other slots available for unrelated Chat, inspection or project setup Runs.
The shared queue, prerequisites and GPU/worktree reservations still apply:
increasing slots does not allow two heavy jobs to reserve the same GPU or two
mutations to enter the same worktree. SQLite transactions serialize claims and
resource grants; slots release transactions while waiting on host work.

The supervisor stops only its children on SIGTERM or Ctrl+C. If any slot exits
unexpectedly, it stops the others and exits with an error so the existing Compose
restart policy replaces the group. Native processes retain their ownership
journals; expired leases use the recovery policy below rather than replaying
dispatched work. All slots can still be occupied by independent long Runs, and
the configured model server determines its own inference capacity.

## Claim and lease

A claim is an `UPDATE ... WHERE status = 'queued'` under SQLite `IMMEDIATE` transactions. Exactly one worker can win. The claim sets `worker_id`, `claimed_at`, and `lease_expires_at`.

The worker refreshes the lease on runs it is actively handling. The interval is `AI_STATION_HEARTBEAT_SECONDS`. The lease length is `AI_STATION_LEASE_SECONDS`. `GET /api/system/status` lists held leases and expired-lease counts for inspection. System shows registered workers as one keyboard sequence (arrows, Home, End) with unique Worker names; there is no inspectable heartbeat Run. Held leases are a separate sequence (arrows, Home, End, Enter inspects the Run) with unique Inspect names. That endpoint never recovers, requeues or restores; the next worker tick still runs `recover_stale`.

## Recovery policy

On each loop the worker loads runs whose lease has expired and whose status is still active.

| Observation | Action |
| --- | --- |
| `claimed`, safe retry, host runner confirms no process | Interrupt and requeue. |
| `preparing` or `running`, process no longer alive | Interrupt for inspection; dispatch may have had side effects. |
| Owned process still alive | Keep its reservation, refresh inspection lease, do not launch another. Forward pending cancellation. |
| Host runner unavailable | Keep state and reservations; retry inspection. Even a missing pid may mean a dispatch response was lost. |
| Pending cancellation and host confirms no live process | Mark canceled and release reservations. |

`retry_class`:

- `safe` — no external side effect yet (a second image, a chat completion that never committed work).
- `inspect` — a person should look before repeating (coding agents, git writes).
- `external` — the run may have called a system outside AI Station. Never auto-retry.

Planned explicit retry creates a new run with `parent_run_id`; it is not exposed in the foundation API. Failed runs are not rewritten in place. Interrupted Runs can be marked inspected from System; that acknowledgement does not requeue work or restore a SQLite backup. See [operations](operations.md).

## Cancellation

1. Persist `cancel_requested` and `cancellation_requested_at`.
2. Ask the runner to signal the owned process group.
3. Runner sends `SIGTERM`, waits a short grace period, then `SIGKILL` if needed.
4. The run becomes `canceled`.

The runner will not signal a pid that is absent from its ownership table. It never uses `pkill` or `killall`.

## Scheduler

The scheduler does not execute workloads. When an enabled agent's `next_run_at` is due, it inserts an ordinary task and run (`triggered_by=scheduler`) and advances the schedule. Pause is `enabled=false`. A restart does not lose schedules; they live in SQLite.

The scheduler also stores telemetry samples. That sampling is not a user workload.

## Targets

`execution_target=host` means the Host Runner. `execution_target=container` is reserved for future isolated runtimes and is not required for photo_pipe, Git, or the coding CLIs already installed on the host. Executor code asks the runner client for host operations instead of branching on Docker internals.

## Photo pipeline

`PhotoPipeExecutor` validates parameters, then the runner starts:

```text
<photo python> <photo_pipe.py> <t2i|img2img|recompose|upscale> ...
```

Arguments match `reference/photo_pipe.py`. `--device` is only `cuda:<index>`. `--out` is an AI Station artifact path. The original script is not modified.

## Coding

Default flow: project → new worktree under app data → branch `ai/<id>-<slug>` → selected executor → configured validation argv → diff artifact → optional commit on the task branch. Push, pull request, and merge are separate approved actions. Protected branches and force-push are refused.

## Streaming

Server-Sent Events replay run events. WebSockets are not used. Clients can reconnect and continue from the last sequence number.

## Image execution contract

Image HTTP handlers validate requests and enqueue durable runs. GPU reservations are committed before dispatch. A transport/server failure after a dispatch attempt leaves state and reservations pending runner inspection; it never frees a potentially occupied GPU. Byte-offset stdout/stderr reads drain all available log chunks before completion. Missing exit status becomes interrupted, never successful. GPU-busy requests return to the queue behind already waiting work. Numeric GPU aliases share the same reservation key.

The Host Runner validates run-specific output paths and app-owned source images, rejects symlink redirection, and rechecks discovered GPU IDs. Photo subprocesses use offline Hugging Face settings. Graceful runner shutdown terminates only its verified managed process groups. Successful output registration includes hashes, thumbnails, actual dimensions, parameters, and parent artifact IDs.

## Scoped memory integration

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Native process completion

A native process group can disappear from the live-process scan before `waitpid` exposes its exit status. While the runner still owns the corresponding child object, inspection reports `completion_pending=true`; photo, worktree and model-scan executors keep polling and recovery preserves the lease/resource reservation. This never converts an unknown exit after runner restart into success. Reaping and inspection share a short lock; no blocking process wait holds that lock.


`chat_summary` is a container executor for explicit incremental conversation summaries. It snapshots local model context and source IDs, emits summary deltas, and atomically publishes coverage, scoped Memory and a Markdown artifact only on success. Cancellation or failed publication keeps the previous summary. Interrupted inference requires inspection, not automatic retry.


Saved project test/lint/build commands now run through the worker and a managed native sandbox in an owned worktree. Commands are snapshotted from versioned project settings, Git metadata stays read-only, networking is blocked, and results become events plus a JSON artifact. Declared Python dependencies use a separate native Run and the same worktree lock. See [project validation and dependency installation](coding-boundary.md). The [bounded Cursor adapter](coding-cursor.md) adds explicit external-AI consent, checked selected-file writes, review artifacts and a separate validation Run; other provider adapters remain disabled.

## Waiting for managed models

Run claims exclude unfinished prerequisites without blocking other queued work. Failed or canceled prerequisites produce PrerequisiteFailed before executor dispatch. A selected managed model reloads from its recorded GPU/context preset; consumers share a pending load. Idle managed llama.cpp instances can be stopped through ordinary Runs for an image or another model. Active and queued consumers prevent eviction. Canceling one waiting consumer leaves shared prerequisites intact.


Local coding uses the same worktree preparation, owned process lifecycle, checked proposal artifacts and validation chain as Cursor. `local_proposal` consumes only a configured private inference endpoint or owned llama.cpp runtime, waits for a normal model-load prerequisite when needed, and can be canceled through the shared native process manager. See [local coding](local-coding.md).

## Run inspector

The inspector separates structured Activity from grouped Output and raw All events. Activity/raw pages show at most 50 events; sequence boundaries keep older pages stable as new events arrive. Arrow keys, Home and End move through the current page; older and newer paging stays outside that list. Full persisted events remain available. SSE resumes after the loaded sequence and merges batches into the cache without re-fetching the entire history per token. Large output, payloads and expandable parameters scroll within bounded panels.


Chat and Work Stop address the active Task within that conversation, including
project setup before a coding workspace exists. The durable Task stop marker
blocks later child publication; a stale stop targets the original Task, never a
new turn. A pending owned llama.cpp load is retained if another active Task
already depends on it. The stopped conversation's consumers are canceled while
the other conversation keeps its model prerequisite. Newly submitted consumers
cannot attach to a startup already being canceled. Native cancellation and
process inspection continue through the existing worker/Runner contracts.

Explicit Work task selection persists in `chat_work_contexts` (migration 0022).
Selection checks the latest proposal and owned workspace, and increments the
conversation settings version to reject stale sends. General Work stores an
explicit empty selection. A follow-up is still an ordinary coding Run on that
Task/worktree, with its initiating conversation recorded on the Run. Sending
checks the proposal version, project activity and applicable external consent.
Task Stop accepts a selected Task or a historical Run belonging to the
conversation, preserving stale-stop scoping after selection changes.

Local coding and source exploration require a complete JSON object, not a prose
answer. The private inference bridge will expose only a strict `json_output`
boolean that maps to OpenAI-compatible JSON-object output; it will not accept
arbitrary schemas or model options. Existing path/content/proposal validation and
confirmed stream completion remain mandatory before any worktree write. Failed
proposal decoding must clearly report that no files were applied. This fixes the
unconstrained-output gap observed by the 2026-10-15 real Work follow-up test.
Upstream support: [llama.cpp JSON response format](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#post-v1chatcompletions-openai-compatible-chat-completions-api).

## Resource waiting and interactive work

A resource-blocked independent-shot batch defers its GPU-demanding Runs for two
worker heartbeats. The generic claim predicate applies the server-authored
`resource_wait_until` deadline in both candidate selection and conditional update;
CPU/control work and other Tasks remain eligible. An owned GPU release clears
its Task marker within the existing resource transaction, and explicit media
resume resets it. Task Stop is serialized with deferral. The requeue event retains
the chosen deadline for audit. See [queue fairness](media-resource-wait-fairness.md).


## Chat website text reads (qualification pending)

Explicit page-analysis requests with Web on use the existing queued Chat executor:
freeze user-selected targets → bounded public GET → source JSON Artifact → model
reply with recorded evidence. Assistant routing still publishes the normal Chat
child Run. Follow-up reuse binds to a same-conversation successful source and its
hash; it records `chat.page_read` without another HTTP request. Stop cancels an
in-flight GET before inference. Failed/empty reads produce an inspectable failure,
not a generic search-snippet substitute. See [page-reader scope and remaining
rendered acceptance](plans/chat-page-reading.md).


## Media resource-wait observations

Host media admission persists its reason and timestamp on the queued Run and in
its ordinary `run.interrupted` event. RAM observations use the same required,
observed available, other active reservations and 1024 MiB headroom inputs as
`reserve_memory`; no admission threshold or GPU policy changes. Missing RAM is
unknown, never zero. Single-Run and composed media-job views expose the latest
queued observation without contacting the Runner from HTTP handlers. Speech
preparation and video/avatar segments share this path. A shot job can show an
active shot alongside another shot's resource wait.

The observation is a timestamped sample, not live telemetry or a completion ETA.
Admission removes the stored marker before dispatch; non-queued Runs never expose
it as a current wait. Stop/failed/terminal media results hide it even if another
child is still queued during cancellation. Existing retry checks, ownership,
expiry and task-wide Stop are unchanged. Old Runs without a marker keep the
existing generic queue text. No schema migration or model download is needed.

Calendar cron enumerates local wall-clock minutes and resolves them with ZoneInfo.
Nonexistent minutes are skipped; repeated minutes execute at the first occurrence
only. The next instant must be strictly future, within five years and a bounded
search. Existing atomic claims, no-overlap, coalescing and recovery remain
authoritative. See [agent schedule semantics](plans/agent-schedule-timezones.md).

A natural analysed-file follow-up creates a fresh normal Task with the prior
reviewed local data/model/runtime policy and immutable original input descriptors.
Its prior question/answer are bounded quoted context; the current instruction
wins. The worker validates the completed source before creating a workspace and
uses the existing source/hash checks and graph-wide Stop. Reading old provenance
does not extend an old deadline or resume its execution.

## Research followed by offline data analysis

For reviewed public-research/data definitions, the normal agent workflow runs
selected search, search-page reading and explicit HTTP reads in source order.
The existing context handoff verifies their provenance and saves one immutable
JSON input before publishing the normal owned-worktree data preparation. Local
generation receives bounded previews and a UUID-named full read-only JSON file;
execution and result adoption bind that file alongside any selected CSV/XLSX
inputs. Confirmed Python failures may use the saved bounded repair budget without
repeating research. Task cancellation and conservative recovery retain the
existing contracts. Source warnings, outputs and transitive lineage remain
inspectable in the agent workspace and Library.

## Conversation source analysis and offline continuations

A typed conversation data scope can select reviewed search/page tools alongside
optional CSV/Excel/JSON files. It still creates only ordinary queued Runs and a
private app-owned workspace. The existing research handoff snapshots complete
bounded observations. An inspection child verifies that JSON input and gates
worktree preparation before local generation/Python. Every stage inherits the
original deadline and Task Stop.

Natural same-data follow-ups derive their actual input IDs from one verified
completed same-conversation result. Captured source JSON is reused as inspected
offline data: original source bytes/lineage and capture time remain; no search or
fetch is replayed. A new question owns a new Task/workspace/deadline. The explicit
refresh action carries the reviewed source selection into a fresh research Task
and preserves the old result and files.

## Reviewed whole-workflow time budget

Agent definitions and disabled proposals allow an explicit 5-second to 4-hour
budget. Existing/default values remain unchanged. Media planning and native
deadline admission share that ceiling; every preparation, generated speech,
segment and composition keeps the original absolute expiry. Resource waiting
consumes the same budget. Replay, native restart or an old media Resume cannot
renew it. Per-command/Python/browser/single-invocation limits, GPU/RAM admission
and process ownership remain independent. Selecting a longer budget grants no
additional tool or filesystem scope. See [budget qualification](plans/long-media-agent-budgets.md).

# Execution model

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation is enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents use disabled drafts, explicit activation, persistent schedules and bounded context tools. Coding-agent execution remains an inactive draft. See README for runnable commands and limitations.


## Path

1. The UI or scheduler creates a task and a `queued` run.
2. The worker heartbeats, recovers stale leases, then claims one queued run in an immediate SQLite transaction.
3. The worker reserves resources (GPU lock for image runs).
4. The executor validates and prepares, then runs on a target.
5. Events and artifacts are persisted.
6. Resources are released. The run ends `succeeded`, `failed`, `canceled`, or `interrupted`.

HTTP handlers do not generate images, run coding agents, or execute agent loops.

## Claim and lease

A claim is an `UPDATE ... WHERE status = 'queued'` under SQLite `IMMEDIATE` transactions. Exactly one worker can win. The claim sets `worker_id`, `claimed_at`, and `lease_expires_at`.

The worker refreshes the lease on runs it is actively handling. The interval is `AI_STATION_HEARTBEAT_SECONDS`. The lease length is `AI_STATION_LEASE_SECONDS`.

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

Planned explicit retry creates a new run with `parent_run_id`; it is not exposed in the foundation API. Failed runs are not rewritten in place.

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

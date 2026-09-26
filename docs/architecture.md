# Architecture

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation is enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents now have reviewed definitions, explicit activation, durable schedules and scoped context tools. Coding-agent execution remains an inactive draft. See README for runnable commands and limitations.


AI Station is a local-first AI workstation control plane. It is a modular monolith with one deliberate process boundary: a Dockerized control plane and a native Host Runner.

```text
User
  │
  ▼
Web UI ── HTTP/SSE ── FastAPI control plane
                         │  tasks, runs, events, artifacts
                         │  worker + scheduler
                         │  SQLite (WAL) under app data
                         ▼
                    Unix socket
                         │
                         ▼
                   Host Runner (typed API)
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
        Git/worktrees  photo_pipe   telemetry
        Codex/Cursor   processes    discovery
        Claude Code
```

Future remote machines register as additional runners. Capability code depends on an execution target, not on "this host".

## Processes

| Process | Where | Role |
| --- | --- | --- |
| `ai-station` | container | HTTP API, UI, SSE |
| `worker` | container | claims runs, dispatches executors |
| `scheduler` | container | creates runs from schedules; samples telemetry |
| Host Runner | host user session | typed host operations |

The three containers share one image and different commands. They do not receive `--privileged`, the Docker socket, or unrestricted host mounts.

## Persistence

Application data lives in one directory (`AI_STATION_DATA_HOST_PATH` on the host, `/data` in containers). The database stores AI Station-owned files as paths relative to that root (`artifacts/ab/cd/<uuid>.png`). External models and repositories are references, not copies.

Replacing containers does not drop the database, artifacts, memory, or run history because those files are on the mounted data volume.

## Execution

Almost every action is a **Task** that produces one or more **Runs**. A Run is performed by an **Executor** on an **Execution Target** (`host` or `container`; `remote-node` is reserved). The worker is the only component that executes runs. HTTP handlers enqueue work and stream stored events.

The Host Runner does not expose an arbitrary shell. Photo, Git, coding CLIs, cancellation, telemetry, and discovery are separate validated operations.

## Networking

The published UI/API port is `127.0.0.1:8765`. Inside the container the process listens on `0.0.0.0` so Docker's localhost publish mapping works. That internal bind is not host exposure.

Loopback-only host model services are reached through the private Host Runner bridge. Optional direct container connections use `host.docker.internal` or another configured reachable endpoint; container `127.0.0.1` remains the container itself.

## Extension points

New behavior plugs in at:

- executor (`Executor` protocol)
- LLM provider (OpenAI-compatible client)
- tool (registry entry with permissions and a real implementation)
- connector (status and credential reference; no fake integrations)
- runtime / model discovery (host scan, no mutation)
- skill (versioned directory under `skills/`)

## Scoped memory integration

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred.

## Local agents

[Agent lifecycle](agents.md) uses the shared queue, local provider, Run events and Markdown artifacts. Explicit telemetry and own-scope memory tools gather bounded context before inference. Definitions start disabled; unsupported tools block activation. Scheduling is serialized, persistent and non-overlapping.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Host loopback model access

Compose defaults to the [typed local-model bridge](local-model-bridge.md) over the existing private Runner socket. Model listing and bounded streamed completions target only the configured local endpoint, with no redirects or caller-selected URL. Canceling a Run closes the upstream response. Direct provider transport remains available for native development and explicitly configured container-reachable endpoints.


## Dashboard activity projection

The dashboard reads bounded summaries of persisted Runs, enabled agents, upcoming schedules, conversations, generated artifacts and runtime observations through `/api/dashboard`. It performs no discovery or execution. Runtime observations retain their original age and source; overdue schedules remain visible without promising an execution time. Hardware and worker/scheduler health retain their separate live endpoints.

# Architecture

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage, including bounded text, PDF text extraction and stored image attachments without pixel vision, plus a persisted provider registry with secret references. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation, explicit removal and unused automatic expiry are enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents now have reviewed definitions, explicit activation, durable schedules, scoped context tools, GET of reviewed public pages, versioned Skills as instruction packs, optional durable approval before each Run, sequential or gated workflow steps, optional bounded registry tool calling during the report, saved retry policies and in-app notices. Named HTTP GET connectors with secret references are inspectable health Runs; browser and other connector kinds stay unpublished. Bounded Cursor and Local AI file-edit proposals (complete rewrites or unique snippet replacements), review artifacts and separate validation Runs are operational. Declared Python dependency installation in owned worktrees is operational. Codex also uses the bounded proposal workflow; Claude Code remains inactive. The Platform assistant can review, commit and publish those coding Tasks through the same Git domain services, and can load or unload owned llama.cpp instances without granting extra permissions from a model plan. See README for runnable commands and limitations.


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

[Agent lifecycle](agents.md) uses the shared queue, local provider, Run events and Markdown artifacts. Explicit telemetry, own-scope memory, configured public search and GET of reviewed public pages gather bounded context as persisted child Runs before the report. Optional bounded tool calling during the report may request those same selected registry tools; invented tools, URLs and commands fail closed. Versioned [Skills](skills.md) inject reviewed instruction text; they do not grant tools or permissions. Definitions start disabled; the natural-language factory copies recognized schedules and policies into that disabled draft. Unsupported tools block activation. An optional durable Approval can park the parent workflow before children are published. Gated mode parks the report after those children succeed. Saved retry policies never auto-loop; manual retry starts a new Run from the snapshot. Saved notification policies write in-app notices. Scheduling is serialized, persistent and non-overlapping.

## Named connectors

[HTTP GET connectors](connectors.md) persist a reviewed public URL and optional secret reference. A user-requested health check is an ordinary Run with `network_read`, cancellation and a JSON artifact. Browser, GitHub, email, calendar and social adapters remain listed as unavailable.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Host loopback model access

Compose defaults to the [typed local-model bridge](local-model-bridge.md) over the existing private Runner socket. Model listing and bounded streamed completions target only the configured local endpoint, with no redirects or caller-selected URL. Canceling a Run closes the upstream response. Direct provider transport remains available for native development and explicitly configured container-reachable endpoints.


## Dashboard activity projection

The dashboard reads bounded summaries of persisted Runs, enabled agents, upcoming schedules, conversations, generated artifacts and runtime observations through `/api/dashboard`. It performs no discovery or execution. Runtime observations retain their original age and source; overdue schedules remain visible without promising an execution time. Hardware and worker/scheduler health retain their separate live endpoints.


Conversation summaries use a dedicated persisted coverage/provenance record and the existing scoped Memory model. [Summary updates](conversation-summaries.md) run through the worker and preserve the full conversation history.


Saved project test/lint/build commands now run through the worker and a managed native sandbox in an owned worktree. Commands are snapshotted from versioned project settings, Git metadata stays read-only, networking is blocked, and results become events plus a JSON artifact. Declared Python dependencies are installed by a separate typed Run that uses vendor wheels offline or a public PyPI index after SSRF-safe DNS checks. See [project validation and dependency installation](coding-boundary.md). The [bounded Cursor adapter](coding-cursor.md) adds explicit external-AI consent, checked selected-file writes, review artifacts and a separate validation Run; other provider adapters remain disabled.

## Reviewed Git progression

[Reviewed commits](coding-commits.md) extend a completed coding Task with a user-approved Git Run. Approval data binds the exact review and validation snapshot; the native Runner owns checked commit publication and its interruption journal. The [full-product ledger](product-completion.md) tracks the remaining acceptance increments.

## Conversation orchestration

The default entry point is the [platform assistant](orchestrator.md). Dedicated workspaces remain available. Conversation intent is compiled into typed capability actions, dispatched as ordinary Runs, and projected back into the conversation with live state and artifacts. The assistant shares domain services with workspaces; it cannot bypass their permissions, resource scheduling or native boundaries.

## Owned llama.cpp instances

[Managed llama.cpp](managed-llama.md) loads discovered GGUF files into an owned container through the native Runner. Inference uses a private Unix socket, selected GPUs remain reserved for the runtime lifetime, and a separate stop Run releases them after confirmed termination. The configured Ollama/OpenAI-compatible endpoint remains available alongside it.

## Runtime prerequisites

RunDependency records durable scheduling prerequisites independently of parent Run provenance. The worker skips blocked Runs, fails consumers of unsuccessful prerequisites, and continues unrelated work. Managed model selection and idle eviction compose ordinary load/stop Runs with Chat, agent, summary and image Runs. See [managed llama.cpp](managed-llama.md).

Speech and images share the owned-process media executor lifecycle; capability adapters provide typed dispatch and output validation. See [local speech](audio.md) for the Chatterbox contract.

Portrait animation uses the same owned-process media lifecycle as images and speech. The native EchoMimic adapter runs offline with CPU offload; Video and Avatars expose the real `avatar.animate` capability, and MP4 results retain image/audio lineage. See [avatar execution](avatars.md).

Reviewed Coding commits use `coding.commit` Runs and a typed native job. A private Git index limits the commit to verified review snapshots; compare-and-swap advances only the owned task ref. Worktree manifests retain their original base and current owned HEAD. NativeJobExecutor shares the existing dispatch/poll/cancel lifecycle with Cursor proposals.

[Library management](library.md) separates versioned user annotations and reversible Trash from immutable execution provenance. Run history and source lineage retain access to artifacts in Trash.

[Local coding proposals](local-coding.md) extend the existing owned-worktree proposal and validation flow with local inference through the private Runner bridge. The native snapshot/write boundary and review artifacts are shared across proposal providers.

The central Assistant can route selected-project coding to the conversation's local model through the same local proposal workflow. A coding scope without external consent routes locally; model-generated plans cannot grant Cursor permission. Project/version/file validation remains in the shared coding enqueue boundary. After a proposal in that conversation, the assistant projects the review and can queue `coding.commit` or `coding.publish` through the same domain services; the model cannot confirm review or GitHub approval.

Optional Chat web search is a permissioned worker tool inside the existing Chat Run. It uses a private SearXNG service and stores sources as events/artifacts before passing untrusted snippets to local inference. The switch is off by default; model-generated routing cannot enable it. See [web search](web-search.md).

Research agents reuse the same bounded search tool as Chat. An explicit saved query is required before activating web_search, and only that query reaches search engines. Manual and scheduled executions snapshot the query and network permission in ordinary Runs; sources are recorded before local report generation. No browser/page-fetch capability or model-generated network permission is introduced.

Local coding optionally uses a bounded read-only repository exploration loop inside its owned worktree before proposal generation. The local model requests typed listing, literal search, file reads, public GET and optional configured search; public URLs written in the task are fetched first. The Runner validates each request and records observations. Cursor and Codex discovery stay repository-only. Selected snapshots then enter the existing checked-write, validation and review workflow. No arbitrary shell, browser, external model or access to the active checkout is introduced.

Agent report retention is an explicit output tool. Selecting `remember_report` grants only scoped `memory_write`; successful output is stored as an observation with Run provenance. `remember_workflow` stores successful telemetry, public search and HTTP fetch child observations the same way and does not copy `memory_search`. Retention and successful final state share one transaction, while cancellation/failure do not populate memory. Existing scoped retrieval and Memory CRUD remain the inspection and control surface.

Local coding repair is a user-requested child Run after confirmed validation failure. It reuses the owned task worktree, original model/file scope and saved validation commands. Bounded failure observations enter the local prompt as untrusted data. The Runner retains a cumulative review against the task base; superseded proposals cannot be committed. Each repair reruns validation and requires a fresh human review. No cloud execution, automatic retry or command changes are introduced.

Local tasks may opt into at most two automatic repair attempts. The budget is snapshotted at task creation; only confirmed validation failures queue the existing local repair operation. Each attempt is a separate Run using the same owned worktree, model, scope and commands. Cancellation, interruption, proposal failure or exhausted budgets stop the chain. Review/commit remain explicit.

Reviewed GitHub publication is a separate user-approved Task/Run operation after a successful reviewed commit. The control plane snapshots project policy, exact commit, origin repository, integration branch and PR text into an approval record. The native Runner revalidates ownership and origin before dispatch, publishes only the owned `ai/` ref, and opens a draft PR. Network Git uses a private bare export with the validated object store and clean configuration, so source repository hooks, credential helpers and URL rewrites are not executed. Existing `gh` authentication is reused without copying credentials. Cancellation or uncertain network completion requires inspection; publication is never blindly retried and never merges.

Automatic conversation memory is a saved opt-in policy, default off. A successful Chat Run may enqueue one existing summary Run in the same transaction, linked to that answer. Summary failure cannot change answer success or previous memory; provenance, cancellation and inspection use the established Run lifecycle.

The Codex proposal adapter reuses selected-file snapshot application, native process ownership, validation and reviewed Git progression. It isolates the provider workspace and permission profile from the task worktree; explicit external consent remains required. See [adapter contract](coding-codex.md).

Coding workspaces make Task the durable user-facing coding conversation. Managed project setup and subsequent turns remain ordinary Runs; the Host Runner owns repository creation and isolated worktrees. See [coding workspace design](coding-workspaces.md).

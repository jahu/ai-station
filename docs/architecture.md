# Architecture

## Planned conversation and long-media milestone — 2026-10-14

The [first-send increment](first-send.md) now adds transactional turn receipts and
mode enforcement to existing services, with no additional execution architecture.

[Create project & build](assistant-project-build.md) composes existing setup,
worktree, proposal and configured checks on the same Task. Only confirmed setup
completion publishes coding; failure preserves the created project and the failed
stage. The dispatcher performs deterministic routing without provider inference.

[First-use model loading](chat-model-selection.md) uses the existing owned runtime
load prerequisite. Merely selecting a GGUF creates no workload; explicit presets
or dynamically discovered devices configure its first consumer.

The [implementation brief](plans/2026-10-chat-work-media.md) and
[updated handoff](plans/implementation-handoff.md) distinguish delivered and planned
increments. Atomic first Send, server-enforced Chat/Work, selection-only local
autoload, the [shared conversation shell](conversation-shell.md), the
[unified model catalog](model-catalog.md) and distinct System/Settings are delivered.
[Qualified thinking](chat-thinking.md), session drafts and searchable history are also delivered.
[Automatic local coding routing](coding-auto-model.md) uses installed GGUF/context
observations and worker-owned runtime preparation. Auto requires 100k+ actual
context at coding dispatch, records the chosen model and never grants external AI.

[Contextual Work](contextual-work.md) reuses coding Tasks/worktrees with durable
Task Stop. [Long-media jobs](long-media.md) add durable segmented video/full-speech
avatar plans, existing RunDependency edges, owned native execution and a typed CPU
composition executor. Final job success requires a verified final artifact from
the selected revision. Task Stop/resume covers this bounded graph; resource
admission includes GPU and host RAM. Longer output hardware qualification is
recorded separately from normal fake-GPU/real-CPU integration tests. See
[the media execution design](plans/long-media-execution.md) for subsequent profiles.

[Conversational media](conversational-media.md) exposes the same aggregate jobs
in Chat/Work, with final-only artifact projection and task-wide Stop. Deterministic
video/avatar actions do not require an LLM planner.

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage, including bounded text, PDF text extraction and stored image attachments and assistant pixel inspection through owned vision GGUF/projector pairs, plus a persisted provider registry with secret references. Project registration, policy editing, and read-only Git status are enabled with disposable-repository integration coverage. Owned worktree preparation, explicit confirmed removal are enabled through the worker and a managed native process. Scoped memory with pinned Chat context and managed model-file discovery are enabled. Local agents now have reviewed definitions, explicit activation, durable schedules, scoped context tools, GET of reviewed public pages, versioned Skills as instruction packs, optional durable approval before each Run, sequential or gated workflow steps, optional bounded registry tool calling during the report, saved retry policies and in-app notices. Named HTTP GET connectors with secret references are inspectable health Runs; public-page Browser is an optional agent workflow tool; account browser automation and other connector kinds stay unpublished. Bounded Cursor and Local AI file-edit proposals (complete rewrites or unique snippet replacements), review artifacts and separate validation Runs are operational. Declared Python dependency installation in owned worktrees is operational. Codex also uses the bounded proposal workflow; Claude Code remains inactive. The Platform assistant can review, commit and publish those coding Tasks through the same Git domain services, and can load or unload owned llama.cpp instances without granting extra permissions from a model plan. See README for runnable commands and limitations.


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

Replacing containers does not drop the database, artifacts, memory, or run history because those files are on the host bind mount. The launcher's `compose down` never passes `--volumes`. `/data` is not a named volume.

## Execution

Coding providers share the [selected source removal](coding-file-removal.md)
contract alongside checked writes and snippet replacements. Removed paths retain
source hashes and reversible diff artifacts; follow-ups and reviewed commits use
the same task/worktree boundary.

Almost every action is a **Task** that produces one or more **Runs**. A Run is performed by an **Executor** on an **Execution Target** (`host` or `container`; `remote-node` is reserved). The worker is the only component that executes runs. HTTP handlers enqueue work and stream stored events.

The worker container supervises bounded independent process slots (three by
default, configurable with `AI_STATION_WORKER_SLOTS`). Slots share the durable
queue and resource reservations, not ORM sessions or executor instances. They
preserve the same claim, permission, cancellation and recovery contracts. See
[execution model](execution-model.md) for shutdown and restart behavior.

The Host Runner does not expose an arbitrary shell. Photo, Git, coding CLIs, cancellation, telemetry, and discovery are separate validated operations.

SQLite backups are explicit Task/Run copies (`VACUUM INTO` plus integrity check). A successful copy can be re-checked in place. The Host Runner can inspect `ai-station:local` versus running compose containers without building or retagging; restore and image rollout stay unpublished. See [operations](operations.md).

## Networking

Synchronous operator-session database checks run in the thread pool. SQLite lock waits must not block the HTTP event loop: response completion releases other request sessions, so blocking that loop can turn ordinary concurrent reads into database-lock failures.

The published UI/API port is `127.0.0.1:8765`. Inside the container the process listens on `0.0.0.0` so Docker's localhost publish mapping works. That internal bind is not host exposure. `AI_STATION_BIND_HOST` is the host publish policy; a non-loopback value aborts startup. An optional operator password can be stored as a PBKDF2 hash and then gates the loopback UI with a session cookie that idles out after 30 minutes and cannot outlive 12 hours. It does not enable LAN publish because authenticated node transport is unpublished. See [nodes and operator access](nodes.md).

Loopback-only host model services are reached through the private Host Runner bridge. Optional direct container connections use `host.docker.internal` or another configured reachable endpoint; container `127.0.0.1` remains the container itself. The only networked node is this Host Runner over its Unix socket. Remote invitations and loopback token registration persist as `StationNode` rows; they do not add a LAN listener.

## Extension points

New behavior plugs in at:

- executor (`Executor` protocol)
- LLM provider (OpenAI-compatible client)
- tool (registry entry with permissions and a real implementation)
- connector (status and credential reference; no fake integrations)
- runtime / model discovery (host scan, no mutation) and explicit local installation (verify existing files/images, never pull)
- skill (versioned directory under `skills/`)

## Scoped memory integration

Agents may explicitly select `project_memory`, which grants only `project_memory_read` on their snapshotted linked project. Retrieval is an ordinary child Run with saved context and provenance. Linking a project alone grants no memory or repository access. See [memory](memory.md#explicit-project-memory).

The [Memory workspace](memory.md) exposes durable scoped entries with validated provenance and FTS retrieval. Optional embeddings use an explicit local OpenAI-compatible endpoint; they are not downloaded and fail closed without that setup. Chat snapshots only enabled pinned global and matching conversation entries into new Run parameters; changes never rewrite historical contexts. The editor reuses the shared list keyboard on pin and enabled flags with unique Memory names; Space or Enter selects the focused row and does not invent a Run.

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred. Users may then save a curated definition with a load preset and explicitly install it; installation verifies the existing file and an already-present llama.cpp image, and never downloads GGUFs or pulls container images.

## Local agents

[Agent lifecycle](agents.md) uses the shared queue, local provider, Run events and Markdown artifacts. Explicit telemetry, own-scope memory, configured public search and GET of reviewed public pages gather bounded context as persisted child Runs before the report. Optional bounded tool calling during the report may request those same selected registry tools; invented tools, URLs and commands fail closed. Versioned [Skills](skills.md) inject reviewed instruction text; they do not grant tools or permissions. The definition editor reuses the shared list keyboard on installed Skills and tools with unique Skill/Tool names; Space or Enter selects the focused row and does not invent a Run. Approval, retry and notice policies reuse that sequence with unique Approval, Retry and Notice names; Space or Enter selects the focused row and does not invent a Run. Bounded tool calling and sequential or gated workflow mode reuse that sequence with unique Tool calling and Workflow names; Space or Enter selects the focused row and does not invent a Run. Linked project radios reuse that sequence with unique Linked project names; Space or Enter selects the focused row and does not invent a Run. Save definition persists it through `PUT /api/agents/{id}`; that tags Runs for filtering and does not grant coding access. The Agents list shows that project name and can filter through `GET /api/agents?project_id=`. Inspect project and View tagged Runs stay on that card and open the project and the tagged Runs filter without calling Enable. View tagged Runs stays on a saved agent even without a project. A saved definition link opens them the same way. The tagged Runs list and Run inspector open that agent and project without calling Enable. The inspector opens tagged Runs from a saved project_id even without an agent, and from a saved agent_id even without a project. Project details list those linked agents from that same query; Enter inspects the selected definition. View tagged Runs stays on that row. Project details also open tagged Runs through `/runs?project_id=`. View all linked agents opens the Agents filter. That list does not grant coding access or Enable or Run now. The Agents definition shows other agents on that same project and omits the current definition. The conversation shows that same list after agent.create. Definitions start disabled; the natural-language factory copies recognized schedules and policies into that disabled draft. Unsupported tools block activation. Enable stays disabled in the conversation and Agents until those tools are removed, a local model is selected, and web_search or http_fetch have their saved query or URLs. The conversation can remove an unavailable or unknown attached tool through `PUT /api/agents/{id}` without calling Enable. Add stays on an operational catalog tool through that same PUT; unpublished adapters cannot be added. The conversation can save the UTC schedule through that same PUT. The conversation can save approval, retry, notice, sequential or gated workflow and bounded tool calling policies through that same PUT. The conversation can save the goal and system prompt through that same PUT. The conversation can save the name, time limit and expected outcome through that same PUT. The conversation can save the description through that same PUT. The conversation can save a linked project through that same PUT; that tags Runs for filtering and does not grant coding access. An optional durable Approval can park the parent workflow before children are published. Gated mode parks the report after those children succeed. The conversation, Agents, Home and the Run inspector grant or deny that parked Run through the existing approval endpoint without starting tools from the UI. Conversation and Agents Stop an in-progress history Run through the existing cancel endpoint without opening the inspector. The latest ordinary agent report is shown inline from its stored markdown artifact. Independently recorded search sources, fetched pages and registry tool calls from that report stay next to it. Workflow steps of the last parent stay next to history from that parent's `workflow.steps`; Enter inspects the child Run. A saved observation opens Memory. The conversation can Inspect this agent's memory. Attached skills are listed from the installed catalog; Review instructions stays on the selected row and does not invent a Skill Run. Remove stays on a stored id missing from that catalog and saves the remaining list through `PUT /api/agents/{id}` without calling Enable. Add stays on an installed catalog skill through that same PUT. At most four. Saved in-app notice policy is shown on that definition. Attached remember-reports or remember-workflow tools show how observations are stored. An enabled idle definition can Run now from the conversation through the existing agent run endpoint without opening the inspector. Saved retry policies never auto-loop; manual retry starts a new Run from the snapshot. Saved notification policies write in-app notices. Scheduling is serialized, persistent and non-overlapping.

## Named connectors

[HTTP GET connectors](connectors.md) persist a reviewed public URL and optional secret reference. A user-requested health check is an ordinary Run with `network_read`, cancellation and a JSON artifact. Public-page Browser is a separately permissioned agent tool; GitHub, email, calendar and social connector adapters remain unavailable.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Host loopback model access

Compose defaults to the [typed local-model bridge](local-model-bridge.md) over the existing private Runner socket. Model listing and bounded streamed completions target only the configured local endpoint, with no redirects or caller-selected URL. Canceling a Run closes the upstream response. Direct provider transport remains available for native development and explicitly configured container-reachable endpoints.


## Dashboard activity projection

The dashboard reads bounded summaries of persisted Runs, enabled agents, upcoming schedules, conversations, generated artifacts and runtime observations through `/api/dashboard`. Those agent summaries include a saved `project_id` when one exists. Home opens that project and the tagged Runs filter without calling Enable. View tagged Runs stays on a saved agent even without a project. The tagged Runs list and Run inspector open that agent and project without calling Enable. The inspector opens tagged Runs from a saved project_id even without an agent, and from a saved agent_id even without a project. Home attention notices include that saved agent and `project_id` and open them the same way. In-progress and waiting agent Runs include those same ids from `/api/dashboard` and open them the same way. In-progress coding and worktree Runs include `project_id` from that payload and open the project and the tagged Runs filter without starting a coding Run. Home unifies interrupted work, notices and in-progress Runs into one attention list. Arrow keys move between attention rows; Enter inspects; Stop, Retry as a new run, Mark inspected, Mark read, Approve and Deny remain on the selected row and include a short Run or notice id. That sequence reuses the shared list keyboard. Those actions call the existing cancel, image-retry, workflow-retry, interrupted-acknowledgement, notice-read and approval endpoints. Image retry stays on Home and does not open the inspector; Mark inspected still does not replay. A failed agent notice can Retry as a new workflow when `retry.allowed` is set; that does not call Run now. Audio and avatar retries stay unpublished. Granting a parked Run queues it for the worker and does not start tools or inference from Home. They do not restore backups or start discovery. Upcoming schedules, enabled agents, recent conversations, recent artifacts and runtime observations each reuse that list keyboard with unique Inspect names; runtime rows open System rather than inventing an observation Run. Activity sections, compute telemetry and the resource chart are labelled landmarks. Home GPU cards reuse the shared list keyboard with unique GPU names; live telemetry stays on Home and there is no inspectable GPU Run. Home CPU, memory, storage and in-progress Run cards reuse that sequence with unique Metric names; Enter inspects Runs from that card and does not invent a telemetry Run. GPU allocation checkboxes in Chat, Models and the assistant load form reuse that sequence with unique Allocate GPU names; Space or Enter selects the focused card and does not invent a Run. Explicit Coding file checkboxes reuse that sequence with unique Edit file names; Space or Enter removes the focused path and does not start a coding Run. Runtime observations retain their original age and source; overdue schedules remain visible without promising an execution time. Hardware and worker/scheduler health retain their separate live endpoints. Status also lists held run leases and expired-lease counts without recovering or replaying them. Ctrl+K opens the command palette, including Backup and upgrade readiness. After in-app navigation the workspace `#main` region is focused, the document title matches the destination, and a polite live region announces that workspace. Overlay pickers keep Radix titles, descriptions and focus traps. Command palette, Library, model and media search fields have accessible names. Sidebar chrome and placeholders use AA contrast tokens. The Runs table uses the same arrow-key selection; Enter inspects the selected row. Remaining keyboard workflows stay open.


Conversation summaries use a dedicated persisted coverage/provenance record and the existing scoped Memory model. [Summary updates](conversation-summaries.md) run through the worker and preserve the full conversation history.


Saved project test/lint/build commands now run through the worker and a managed native sandbox in an owned worktree. Commands are snapshotted from versioned project settings, Git metadata stays read-only, networking is blocked, and results become events plus a JSON artifact. Declared Python dependencies are installed by a separate typed Run that uses vendor wheels offline or a public PyPI index after SSRF-safe DNS checks. See [project validation and dependency installation](coding-boundary.md). The [bounded Cursor adapter](coding-cursor.md) adds explicit external-AI consent, checked selected-file writes, review artifacts and a separate validation Run; other provider adapters remain disabled. Coding, follow-up and assistant consent checkboxes reuse the shared list keyboard with a unique Consent name; Space or Enter selects it and does not start a coding Run.

## Reviewed Git progression

[Reviewed commits](coding-commits.md) extend a completed coding Task with a user-approved Git Run. The review acknowledgement reuses the shared list keyboard with a unique Review name; Space or Enter selects it and does not queue a commit. Approval data binds the exact review and validation snapshot; the native Runner owns checked commit publication and its interruption journal. The [full-product ledger](product-completion.md) tracks the remaining acceptance increments.

## Conversation orchestration

The default entry point is the [platform assistant](orchestrator.md). Dedicated workspaces remain available. Conversation intent is compiled into typed capability actions, dispatched as ordinary Runs, and projected back into the conversation with live state and artifacts. Coding review in that conversation and on the Run inspector lists files as a keyboard listbox that shows only the selected patch, labels cumulative diffs against the task base, lists saved validation commands from that validation Run with unique Command names, and links the stored patch artifact without changing commit or publication permissions. There is no inspectable validation-command child Run. That file list reuses the shared list keyboard; Enter does not open a Run. Repository exploration steps use the same sequence with unique Step names and do not invent an exploration Run. Explicit assistant file checkboxes reuse that sequence with unique Edit file names; Space or Enter removes the focused path and does not enqueue a coding Run. Staged Chat text attachments and assistant image references reuse that list keyboard with unique Attachment and Image reference names; Remove and reorder stay on the selected item and Enter does not send. Saved Chat transcript attachments are a nested sequence with unique Saved attachment names; Enter opens the selected file and does not inspect a Run. Images workspace sources use the same sequence with unique Source names; Enter does not queue a photo Run. The assistant shares domain services with workspaces; it cannot bypass their permissions, resource scheduling or native boundaries.

## Owned llama.cpp instances

[Managed llama.cpp](managed-llama.md) loads discovered GGUF files into an owned container through the native Runner. Inference uses a private Unix socket, selected GPUs remain reserved for the runtime lifetime, and a separate stop Run releases them after confirmed termination. Health inspects only that owned instance; restart reuses the saved load preset after a confirmed stop. The configured Ollama/OpenAI-compatible endpoint remains available alongside it.

## Runtime prerequisites

RunDependency records durable scheduling prerequisites independently of parent Run provenance. The worker skips blocked Runs, fails consumers of unsuccessful prerequisites, and continues unrelated work. Managed model selection and idle eviction compose ordinary load/stop Runs with Chat, agent, summary and image Runs. See [managed llama.cpp](managed-llama.md).

Speech and images share the owned-process media executor lifecycle; capability adapters provide typed dispatch and output validation. See [local speech](audio.md) for the Chatterbox contract.

Portrait animation uses the same owned-process media lifecycle as images and speech. The native EchoMimic adapter runs offline with CPU offload; Video and Avatars expose the real `avatar.animate` capability, and MP4 results retain image/audio lineage. See [avatar execution](avatars.md).

Reviewed Coding commits use `coding.commit` Runs and a typed native job. A private Git index limits the commit to verified review snapshots; compare-and-swap advances only the owned task ref. Worktree manifests retain their original base and current owned HEAD. NativeJobExecutor shares the existing dispatch/poll/cancel lifecycle with Cursor proposals.

[Library management](library.md) separates versioned user annotations and reversible Trash from immutable execution provenance. Run history and source/derived lineage retain access to artifacts in Trash.

[Local coding proposals](local-coding.md) extend the existing owned-worktree proposal and validation flow with local inference through the private Runner bridge. The native snapshot/write boundary and review artifacts are shared across proposal providers.

The central Assistant can route selected-project coding to the conversation's local model through the same local proposal workflow. A coding scope without external consent routes locally; model-generated plans cannot grant Cursor permission. Project/version/file validation remains in the shared coding enqueue boundary. After a proposal in that conversation, the assistant projects the review and can queue `coding.commit` or `coding.publish` through the same domain services; the model cannot confirm review or GitHub approval.

Optional Chat web search is a permissioned worker tool inside the existing Chat Run. It uses a private SearXNG service and stores sources as events/artifacts before passing untrusted snippets to local inference. The switch is off by default; model-generated routing cannot enable it. The composer reuses the shared list keyboard on that toggle with a unique Search name; Space or Enter selects it and does not send. See [web search](web-search.md).

Research agents reuse the same bounded search tool as Chat. An explicit saved query is required before activating web_search, and only that query reaches search engines. Manual and scheduled executions snapshot the query and network permission in ordinary Runs; sources are recorded before local report generation. No browser/page-fetch capability or model-generated network permission is introduced.

Local coding optionally uses a bounded read-only repository exploration loop inside its owned worktree before proposal generation. The local model requests typed listing, literal search, file reads, public GET and optional configured search; public URLs written in the task are fetched first. The Runner validates each request and records observations. Cursor and Codex discovery stay repository-only. Selected snapshots then enter the existing checked-write, validation and review workflow. No arbitrary shell, browser, external model or access to the active checkout is introduced.

Agent report retention is an explicit output tool. Selecting `remember_report` grants only scoped `memory_write`; successful output is stored as an observation with Run provenance. `remember_workflow` stores successful telemetry, public search and HTTP fetch child observations the same way and does not copy `memory_search`. Retention and successful final state share one transaction, while cancellation/failure do not populate memory. Existing scoped retrieval and Memory CRUD remain the inspection and control surface.

Local coding repair is a user-requested child Run after confirmed validation failure. It reuses the owned task worktree, original model/file scope and saved validation commands. Bounded failure observations enter the local prompt as untrusted data. The Runner retains a cumulative review against the task base; superseded proposals cannot be committed. Each repair reruns validation and requires a fresh human review. No cloud execution, automatic retry or command changes are introduced.

Local tasks may opt into at most two automatic repair attempts. The budget radios reuse the shared list keyboard with unique Repair names; Space or Enter selects a row and does not start a coding Run. The budget is snapshotted at task creation; only confirmed validation failures queue the existing local repair operation. Each attempt is a separate Run using the same owned worktree, model, scope and commands. Cancellation, interruption, proposal failure or exhausted budgets stop the chain. Review/commit remain explicit.

Reviewed GitHub publication is a separate user-approved Task/Run operation after a successful reviewed commit. The approval checkbox reuses the shared list keyboard with a unique Publication name; Space or Enter selects it and does not publish. The control plane snapshots project policy, exact commit, origin repository, integration branch and PR text into an approval record. The native Runner revalidates ownership and origin before dispatch, publishes only the owned `ai/` ref, and opens a draft PR. Network Git uses a private bare export with the validated object store and clean configuration, so source repository hooks, credential helpers and URL rewrites are not executed. Existing `gh` authentication is reused without copying credentials. Cancellation or uncertain network completion requires inspection; publication is never blindly retried and never merges.

Automatic conversation memory is a saved opt-in policy, default off. A successful Chat Run may enqueue one existing summary Run in the same transaction, linked to that answer. Summary failure cannot change answer success or previous memory; provenance, cancellation and inspection use the established Run lifecycle.

The Codex proposal adapter reuses selected-file snapshot application, native process ownership, validation and reviewed Git progression. It isolates the provider workspace and permission profile from the task worktree; explicit external consent remains required. See [adapter contract](coding-codex.md).

Coding workspaces make Task the durable user-facing coding conversation. Managed project setup and subsequent turns remain ordinary Runs; the Host Runner owns repository creation and isolated worktrees. See [coding workspace design](coding-workspaces.md).

## Conversation workstation inspection

`system.inspect` is a read-only child Run. The worker invokes the existing typed Runner hardware endpoint, then atomically publishes observed artifacts and an inline conversation report. It needs no LLM or GPU reservation. The planner also receives bounded, immutable same-conversation excerpts without previous permissions or attachment IDs. See [station inspection](station-inspection.md).

## Architecture-aware model context

Owned Q8 llama.cpp load Runs inspect a bounded GGUF header through the typed Runner model-verification operation. The worker records the architecture-derived KV estimate and fitted context before dispatch; handlers do not open external model files. Saved observations are bound to file size and modification time. See [local coding context](model-context.md).

## Local pixel vision

The assistant dispatches image inspection through ordinary owned runtime-load and Chat Runs. Its worker prepares explicit artifact images as bounded inline inputs, and the private Runner rejects remote image URLs. A paired projector is mounted read-only beside the selected model. Descriptions persist as Markdown artifacts with source lineage. See [Chat vision](chat-vision.md).

## Coding agents

Agents may explicitly select the Local coding tool and a Project. They publish the same fresh-worktree/exploration/proposal/validation Runs as manual Coding. The child chain stays inspectable in agent history and Coding; no commit or publication is implied. See [coding agents](agent-coding.md).

Image generation and edits can now queue a dependent 4× Upscale with the existing photo executor. The result/completion and child publication are atomic, and Images follows the active stage after refresh. See [image workflows](image-workflows.md).

Portraits can now use a voice reference and typed Polish speech through a sequential Chatterbox → EchoMimic workflow, retaining both outputs and following the active stage after refresh. See [speaking avatars](speaking-avatars.md).

Public GET adapters pin connections to checked DNS addresses, preserve original HTTP/TLS identity and isolate each redirect connection. Origin changes drop connector credentials. See [network boundaries](security-model.md#public-connection-identity).


Public-page browsing is available as an optional isolated agent workflow tool,
with JavaScript, Library screenshots, bounded text, exact container ownership and
cancellation/recovery. It requires an explicitly built local executor image and
configuration; missing setup remains unavailable. See [browser setup and security](browser.md).


## General video

[Wan video](video.md) reuses HostMediaExecutor and native process ownership. A fixed
worker invokes required built-in ComfyUI components; no ComfyUI server or raw
workflow graph is exposed. Inputs/output/cache and transient configured-model aliases
belong to the Run directory/data root; installed models and runtimes are unchanged.


The Assistant's bounded Image → video workflow composes the existing photo and
Wan executors. Successful image registration, child publication and completion
commit atomically; the child consumes only that registered artifact and uses a
new normal GPU reservation. See [media workflow](image-workflows.md).

Search-informed image generation composes ordinary Assistant → Chat brief →
Photo Runs in one Task. The search switch augments an explicit new-image intent
instead of overriding routing. Sources and the generated prompt are persisted;
only successful bounded inference publishes the photo child in the completion
transaction. See [web search](web-search.md#search-informed-image-generation).

The image Generate adapter's prompt-only profile changes two style defaults in
an owned imported pipeline process without changing the original file. The
configured pipeline and Python remain administrator-owned; callers select only
the typed profile. See [image profiles](image-workflows.md#prompt-only-generation-profile).

Optional research can now precede the same first-frame animation workflow.
The selected action determines whether a bounded Chat brief publishes a plain
image or an image with the user's separate motion instruction; photo completion
then publishes Wan atomically. No model-generated tool graph is executed.

Assistant project creation reuses the existing pure setup enqueue service with
its parent's Task and ordinary native executor. The worker alone creates the
repository/environment. Success publishes the saved project's identity back
to the conversation; continuation selects a versioned coding scope without
starting work from the UI. See [assistant projects](orchestrator.md#create-a-project-in-the-assistant).

System and the central workstation report now include bounded NVIDIA compute
process observations: GPU, executable basename, PID and reported VRAM. They
never expose command lines or control external processes. See
[GPU process reporting](gpu-processes.md).


Chat and Work Stop address the active Task within that conversation, including
project setup before a coding workspace exists. The durable Task stop marker
blocks later child publication; a stale stop targets the original Task, never a
new turn. A pending owned llama.cpp load is retained if another active Task
already depends on it. The stopped conversation's consumers are canceled while
the other conversation keeps its model prerequisite. Newly submitted consumers
cannot attach to a startup already being canceled. Native cancellation and
process inspection continue through the existing worker/Runner contracts.

Work can explicitly bind a conversation to an existing owned coding Task through
`ChatWorkContext`. This selection is metadata only and version-checked; it never
moves the Task's original conversation/history, grants external-provider consent,
or launches work. Follow-up Runs retain the same Task/worktree and record the
conversation that submitted that turn. Existing conversations without an explicit
binding retain their original automatic task context.

A Coding session can stage its existing Task in the blank Work composer. The
read-only draft context and pinned proposal version do not create database rows.
First Send atomically binds the new conversation to that Task, enqueues its
follow-up and records the existing chat turn receipt. Invalid scope/consent or a
stale proposal rolls back the conversation and binding. Conversation model
settings never replace the selected task's executor/model.

Full-recording EchoMimic jobs can carry bounded, model-observed safetensors motion
checkpoints as hidden general document Artifacts. Their in-process adapter preserves
the existing portrait identity reference and shared seventeen-frame prefix through
flow-scheduler steps. Installed models/runtime source are unchanged. Legacy clips
without checkpoints use the existing pixel path. See [Echo motion](echo-motion-context.md).

GitHub repository snapshots use the same [connector registry](connectors.md) and
ordinary native Run contract. Only fixed GET projections run through the existing
host gh session; connector metadata and snapshots never expose credential values.

Local agent workflows can now gather [reviewed GitHub snapshots](agent-github-reports.md) through the same native connector executor. The agent stores a resource identity, receives minimum child permissions, and passes only a bounded excerpt to its local report model. No extra execution engine or account-write integration is introduced.

## Offline transcription

[Audio transcription](audio-transcription.md) adds a CPU-only typed native executor
and conversation action using the shared Task/Run infrastructure. Audio remains
inside application storage; model files remain external references. Whisper's
optional Python environment does not change the control-plane image or existing
speech/video runtimes. Immutable source/model checks, bounded offline audio decoding and
verified completion gate TXT/SRT/JSON artifact publication.

[Transcript conversation continuity](transcript-conversation-context.md) adds bounded, source-checked artifact references to the existing Chat, planner and summary snapshots. It grants no new tools or host access and preserves original message coverage offsets.

[Recording questions](conversational-audio-analysis.md) publish an ordinary Chat child only after verified native CPU transcription. Both stages share the original Task, frozen provider/model selection and task-wide Stop; publication is transactional and idempotent. No additional execution engine or schema is introduced.

# AI Station

A local-first AI workstation control plane. Work is represented by **Task → Run → Events → Artifacts**, with a Dockerized control plane and a native, user-level Host Runner.

Development targets the [complete product vision](docs/product-completion.md). Earlier [local acceptance evidence](docs/mvp-acceptance.md) records verified milestones, not completion of that vision.

## What works now

- Platform assistant: the default conversation routes instructions to images, agent drafts and explicitly scoped Cursor tasks, showing ordinary Runs and image results inline. Existing workspaces remain available. See [orchestrator contracts and roadmap](docs/orchestrator.md).

- Local chat: persisted conversations, selectable managed llama.cpp GGUFs across multiple GPUs alongside Ollama/compatible providers, model discovery, streaming Markdown, bounded text attachments, stop, regeneration, and inspectable Runs.
- Agents: disabled natural-language drafts, explicit activation, local reports, scoped context tools, persistent UTC schedules, pause/resume, duplication and execution history.
- Memory: scoped FTS search, validated provenance, editing, pin/disable controls, and immutable pinned Chat context.
- External runtimes: read-only process observations and configured local endpoint health, with durable history and explicit external ownership in System.
- Models: managed metadata-only discovery Runs, persistent file observations, category/search/detail views and report artifacts.
- Projects: host-validated repository registration, read-only Git status, persisted branch policies, argv validation commands, and agent guidance.
- Cursor coding: explicit external-AI consent, selected-file proposals in a fresh worktree, checked writes, diff review and automatic saved validation.
- Owned worktree preparation: a queued local Run creates an isolated task branch, captures logs, and records a JSON artifact without changing the active checkout.
- Audio: local Polish speech with the installed Chatterbox pipeline, bounded WAV voice references, cancelable Runs and playable Library artifacts. See [speech setup](docs/audio.md).
- Images: Qwen/Juggernaut Generate, Edit, multi-reference Recompose, and 4× Upscale through the existing photo pipeline.
- Library: image/WAV import, search and type filters, editable names and notes, reversible Trash, source reuse and preserved Run history. See [Library management](docs/library.md).
- Avatars and Video: local EchoMimic portrait animation from an image and speech, with inline playback and reusable Library outputs.
- One-command startup of the native runner, API, worker, scheduler, and web UI.
- Live GPU/CPU/RAM/storage dashboard, telemetry history, worker health, and read-only diagnostics.
- Durable run state, atomic claims, leases, cancellation, conservative recovery, event replay over SSE, and a run inspector.
- Alembic migrations and SQLite WAL persistence under one application-owned data directory.
- Keyboard navigation through a command palette (`Ctrl+K` / `Cmd+K`).

The bounded Cursor adapter is operational. Other coding-agent modules remain inactive drafts; reviewed changes can be committed to the owned task branch; pushes and PR actions are not yet exposed. Saved project validation runs in prepared worktrees through the native sandbox.

## Prerequisites and installation

Linux, Python 3.12+ with venv support, Git, and Docker Engine with Docker Compose. Docker must be usable by your current user. A GPU, installed models, and coding CLI credentials are not required to start the control plane or run tests. Node is provided by a project-scoped Docker container; no host Node installation is necessary.

```bash
git clone https://github.com/jahu/ai-station.git
cd ai-station
git switch develop
cp .env.example .env
./scripts/bootstrap.sh
./scripts/start.sh
```

Open **http://127.0.0.1:8765**. Startup builds one application image, starts or reuses a compatible native runner, checks health, and supervises the deployment in the foreground. Ctrl+C stops the containers and the runner started by this invocation. It does not remove data or touch other Docker projects. A pre-existing Compose deployment is never taken over for cleanup. `./scripts/start.sh --no-build` reuses an already built image.

Bootstrap installs Python dependencies only in `.venv`. It never installs drivers, changes CUDA, downloads AI models, or modifies existing AI software.

## Configuration and persistence

Copy `.env.example`; configure existing integrations using host paths. Relative paths resolve from the repository root. `AI_STATION_DATA_HOST_PATH` defaults to `./data`, mounted as `/data` in containers. Database records store app-owned paths relative to this root. External repositories/models remain references.

The normal launcher uses `data/runtime/runner/runner.sock` with mode `0600` in a private directory; configure `AI_STATION_RUNNER_SOCKET` to place it elsewhere (filename `runner.sock`). Containers run as your uid/gid and mount only application data and the socket directory. The runner can also be started independently with `./scripts/runner-dev.sh`, using its configured socket or the user's XDG runtime directory by default.

Configure `AI_STATION_LLM_BASE_URL` with the host endpoint. Compose defaults to `AI_STATION_LLM_TRANSPORT=runner`, carrying typed model requests over the private socket so loopback-only servers remain reachable without reconfiguration. Direct connections remain available with `AI_STATION_LLM_TRANSPORT=direct` and `AI_STATION_LLM_CONTAINER_BASE_URL`; `host.docker.internal` maps to the Linux host gateway. See [local model bridge](docs/local-model-bridge.md).

Do not commit `.env` or secrets. The UI/API port is bound to localhost; authentication must be introduced before LAN exposure.

## Local chat

Expand **Local model files · llama.cpp** in conversation settings to load a discovered GGUF, choose GPUs and context size, then select it for the conversation. Multiple selected GPUs share the model by layers. Stop unloads only AI Station's owned instance. Later messages automatically reload that model with its saved GPU/context settings. Image generation and other model loads can evict idle managed models; active conversations remain protected. Use Models to scan configured roots first. The Runner uses the already-installed image selected by `AI_STATION_LLAMA_IMAGE` and never pulls models or images automatically. See [runtime lifecycle](docs/managed-llama.md).

Configure `AI_STATION_LLM_BASE_URL` (for example `http://127.0.0.1:11434/v1` for Ollama or `http://127.0.0.1:8080/v1` for llama.cpp) and optionally `AI_STATION_LLM_MODEL`. An existing compatible server must already be running; the private runner bridge reaches it on the host, and AI Station does not launch or reconfigure it. If required, supply its key through `AI_STATION_LLM_API_KEY`, never in the URL.

Open Chat, select or enter a model name, set a system prompt, and create a conversation. Send with the button or Ctrl/Cmd+Enter. Responses stream into persistent history and link to their Run. Stop closes the active provider connection even if no tokens arrive. Regenerate preserves the previous response and creates a new Run for the same Task. A conversation permits one active Run; settings can be changed when it is idle.

This slice supports text, UTF-8 file attachments and local endpoints: localhost, host.docker.internal, loopback/private IPs. Public/cloud URLs and redirects are rejected. Markdown images do not load remote content. Context is a visible bounded policy: the latest 16 eligible messages, at most 56,000 history characters plus the system prompt. Full history remains persisted; the UI shows the latest 200 messages. Inspectable rolling summaries can be updated explicitly from Conversation memory. Image/PDF attachments, cloud Chat providers, and coding execution modes inside Chat are not enabled yet. See [chat execution](docs/local-chat.md).

Attach up to four UTF-8 text/code files in the Chat composer (16 KB per file, 24 KB combined). Preview or remove them before sending; the prompt and serialized attachment context share a 32,000-character limit. Files become general text artifacts with hashes and message/Run provenance, remain downloadable after restart, and are included in regeneration and explicit summaries. Downloads use plain text and attachment disposition even for an HTML filename. See [Chat attachments](docs/chat-attachments.md).

## Images

Set `AI_STATION_PHOTO_PYTHON` and `AI_STATION_PHOTO_SCRIPT` to absolute paths for the existing Python environment and `photo_pipe.py`; `AI_STATION_SD_CLI` helps diagnostics. Restart AI Station after changing configuration. The original script remains independent and unchanged.

Open Images, select an operation and GPU (or Auto), and submit. The worker creates an ordinary Run, reserves a discovered GPU, and calls the native runner. Images appear in Library with actual dimensions, parameters, and source links. Library actions reuse an image for Edit, Recompose, or Upscale. Uploads accept PNG/JPEG/WebP up to 20 MiB and 64 megapixels; upscale output is capped at 64 megapixels. Qwen's existing pipeline does not use seed/negative-prompt controls, so those controls appear only for Juggernaut.

Models must already be installed/cached. The runner sets Hugging Face offline mode; it never downloads missing Juggernaut weights. The external script still owns its existing cache/temp conventions. All six mode/backend cases passed small real GPU acceptance Runs; normal automated tests use a fake pipeline.

Failed, canceled, or interrupted image runs may be explicitly retried after the runner confirms the original process is gone. A retry has a new ID/output path, shares the Task, and links to its parent Run. Inspect partial output before retrying an interrupted run; recovery does not automatically adopt orphaned output or repeat generation.

## Projects

Include your repository roots in `AI_STATION_ALLOWED_ROOTS` (colon-separated host paths) and restart the runner. Open Projects → Register project and enter an existing Git repository's host path. The runner checks its canonical root and metadata; registering a subdirectory or symlink cannot create a duplicate project. AI Station's own checkout can be registered the same way.

Project details show the current branch and working-tree changes on explicit refresh. Configure default/integration branches, protected branches, executor preference, test/lint/build commands, and agent guidance. Commands use one JSON argv array per line, such as `["pytest", "-q"]`. Saving does not execute commands or alter the repository. Stale edits and edits during active project Runs are rejected. Repository paths are immutable; removal is not exposed yet. See [Projects](docs/projects.md).

Choose **Prepare isolated worktree** to queue a local Run from the project's existing integration branch. The worker asks the runner to create `ai/<run-id>-workspace` under `worktrees/<project-id>/<run-id>`, leaving your current checkout and index unchanged. The Run captures logs and a JSON report; Projects lists the preserved worktree. Cancellation signals only its owned process group. No coding agent, validation command, commit, push, or PR is launched. Hooks/filters are disabled during preparation, submodules are not initialized, and partial data is preserved for inspection after errors. Custom `core.worktree`, partial clones, and alternate object stores are not supported. See [owned worktrees](docs/worktrees.md).

Choose **Run saved validation** on a prepared worktree to enqueue its saved test, lint and build commands. The runner requires the installed Cursor native sandbox helper and fails closed if isolation is unavailable. Commands can write only inside the worktree; Git metadata stays read-only and network access is blocked. Dependencies must be installed within the worktree or available in system runtime paths. The Run includes live logs, cancellation, command exit codes and a JSON report. See [validation boundary](docs/coding-boundary.md).

## Coding with Cursor

Open Coding, select a registered project, describe a change and list up to ten relative UTF-8 file paths (existing or new). Explicitly approve sending the prompt, project guidance and selected contents to external Cursor AI. A fresh task branch/worktree starts from the configured integration branch. Cursor proposes complete replacements with tools disabled; the runner checks paths and source hashes before applying them. Inspect the linked Coding Run for the summary, changed files, diff and downloadable patch, then follow its separate validation Run for test/lint/build results. The worktree remains available under the application data root for human review.

The installed, authenticated `cursor-agent` CLI is required. Credentials are used by the CLI and never copied by AI Station. The initial adapter allows at most 32 KB per file and 64 KB of selected context, with a five-minute provider limit. Hidden/configuration credential paths, binary edits, deletion and autonomous repository exploration are unsupported. Saved validation additionally needs Cursor's installed native sandbox helper and worktree-local or system dependencies. No commit, push, merge or restart follows a coding result. Codex, Claude Code and local coding remain unavailable. See [Cursor execution and limits](docs/coding-cursor.md).

## Development and verification

```bash
./scripts/dev.sh                 # runner + Docker backend/worker/scheduler + Vite
# Open http://127.0.0.1:5173; Ctrl+C shuts down this deployment.
./scripts/check.sh               # Python lint, format, backend and runner tests
./scripts/frontend.sh ci
./scripts/frontend.sh run lint
./scripts/frontend.sh run typecheck
./scripts/frontend.sh test
./scripts/frontend.sh run build
docker compose config --quiet
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
docker build -t ai-station:local .
.venv/bin/python scripts/smoke.py # opt-in, temporary Docker deployment and fake executor
.venv/bin/python scripts/chat_smoke.py # opt-in Chromium test; loopback fake provider, no inference
.venv/bin/python scripts/projects_smoke.py # opt-in Chromium + native UDS runner; disposable Git repository
```

Normal tests use temporary databases and disposable processes. They never call AI providers, consume cloud tokens, or generate GPU images. Set `AI_STATION_BROWSER_SMOKE=1 AI_STATION_IMAGE_SMOKE=1` to add the fake image browser flow on a workstation with a discoverable GPU (the fake pipeline never uses that GPU). The Docker smoke test checks the UI/API, native UDS telemetry, worker execution, SSE, restart persistence, and cleanup. Its optional `AI_STATION_BROWSER_SMOKE=1` mode requires Playwright and Chromium separately installed for development; it writes screenshots under `/tmp`.

`AI_STATION_ENABLE_TEST_EXECUTOR=true` enables `POST /api/testing/runs` for fake execution; it is disabled by default. Actual GPU/coding/provider workloads remain separate opt-in tests. See [verification](docs/verification.md) for exactly what has been exercised.

## Architecture and extension points

Read [architecture](docs/architecture.md), [domain model](docs/domain-model.md), [execution model](docs/execution-model.md), and [security model](docs/security-model.md).

- **Executor:** implement `app.executor.Executor`, use the run lifecycle, commit before external I/O, and register only after testing cancellation and recovery.
- **Capability:** validate intent, permissions, resources, and parameters before enqueueing a task/run. HTTP handlers do not execute workloads.
- **Tool:** declare schemas, permissions, risk, timeout, and a real implementation; unavailable integrations remain unavailable.
- **Model provider:** implement behind the provider adapter rather than coupling domains to a runtime.
- **Connector:** expose actual status/capabilities and secret references, never plaintext credentials.

The scheduler enqueues normal runs and samples telemetry. Short SQLite transactions serialize claims, event sequencing, and resource reservations. Raw telemetry is retained six hours, then one observed sample per hour for 30 days (not an averaged measurement).

## Security boundaries and limitations

The runner is not a shell daemon. Its enabled API offers host inspection, validated photo launches, owned worktree preparation, model metadata discovery, bounded Cursor proposals, sandboxed saved validation, and cancellation of recorded, verified process groups. Boot identity, process start ticks, session, and group membership protect against PID reuse. Read-only Git inspection disables repository command helpers and enforces metadata roots, time/output bounds, and revision validation. Partial clones and alternate object stores are not supported for inspection yet. Draft filesystem/Git mutation routes are unavailable. Existing external services are never stopped or imported implicitly. Managed workload containers and remote nodes remain future work.

Uncertain host execution keeps its reservations pending inspection; recovery never blindly repeats side effects. If a worker disappears after dispatch, the run requires inspection when the process is gone. SQLite uses short serialized transactions; multi-node/distributed execution is not implemented. A real local OpenAI-compatible `qwen3:8b` completion and persisted response were verified on 2026-09-25. Real Qwen/Juggernaut generation, Edit, one/multiple-reference Recompose and Upscale passed small GPU acceptance Runs. A real Cursor selected-file coding task passed with diff review and sandboxed validation. Codex remains unavailable; no real Codex task has passed.

Contributions use reviewed feature PRs to `develop`; `main` is the release branch. See [AGENTS.md](AGENTS.md).

### Memory workspace

Memory now supports scoped FTS search, provenance inspection, versioned editing, pinning, disabling and confirmed deletion. Enabled pinned global and conversation entries are snapshotted into new Chat Runs. See [memory contracts](docs/memory.md) and the [MVP acceptance ledger](docs/mvp-status.md). Agents can retrieve enabled entries from their own scope when the memory tool is selected. Conversation memory now supports [explicit rolling summary updates](docs/conversation-summaries.md), with source Runs, preserved history and editable/disableable scoped Memory.

### Models workspace

Models now discovers existing host files through a cancellable worker Run, persists observations and exposes category/search/detail views. Set `AI_STATION_MODEL_ROOTS` to colon-separated host model directories. No weights are loaded or modified. See [discovery contracts](docs/models.md). Runtime management remains unavailable.

### Agents workspace

Describe a task in Agents, inspect and edit the disabled definition, select a local model and tools, then enable it explicitly. Schedules use UTC. Run now, pause, duplicate and execution history share the global Runs inspector. See [agent contracts and limits](docs/agents.md).

Runtime observations are refreshed through a normal Run from **System → Observe runtimes**. Process presence, endpoint availability and model files remain separate. See [runtime observation semantics](docs/runtimes.md).


The Home workspace combines live hardware with saved activity: active/queued Runs, enabled agents, scheduled work, recent conversations and generated artifacts. Runtime cards distinguish process observations from endpoint checks and flag stale data. Quick actions open the relevant workspaces without starting a workload.

Runs supports combined status, capability, executor, execution target, project, agent, GPU and creation-time filters. Filters are kept in the page URL and paging makes older history accessible. Dates are entered in local time and submitted with an explicit timezone.

## Local validation and hosted CI

Run `./scripts/check-all.sh` for Python tests/lint, frontend checks/tests/build, Compose validation and a Docker image build. The script stops on the first failure and does not restart the application. GitHub Actions remains available by manual dispatch; automated hosted runs are paused because the maintainer's free credits are exhausted. Per maintainer instruction (2026-09-28), reviewed PRs may merge into `develop` using equivalent successful local checks. Failing code checks are never waived.

Portrait-driven video is available in **Avatars** and **Video**, including assistant dispatch and inline playback. Configure the existing offline EchoMimic installation as described in [avatar execution](docs/avatars.md).

After a Coding proposal and its configured validation pass, inspect the diff and choose **Commit reviewed changes**. This queues a local task-branch commit containing exactly the reviewed file snapshots. Changed files, staged edits and protected branches are rejected. See [reviewed commits](docs/coding-commits.md).

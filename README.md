# AI Station

A local-first AI workstation control plane. Work is represented by **Task → Run → Events → Artifacts**, with a Dockerized control plane and a native, user-level Host Runner.

## What works now

- Images: Qwen/Juggernaut Generate, Edit, multi-reference Recompose, and 4× Upscale through the existing photo pipeline.
- Validated image uploads, artifact Library, source reuse, live stdout/stderr, owned-process cancellation, and explicit image retries.
- One-command startup of the native runner, API, worker, scheduler, and web UI.
- Live GPU/CPU/RAM/storage dashboard, telemetry history, worker health, and read-only diagnostics.
- Durable run state, atomic claims, leases, cancellation, conservative recovery, event replay over SSE, and a run inspector.
- Alembic migrations and SQLite WAL persistence under one application-owned data directory.
- Keyboard navigation through a command palette (`Ctrl+K` / `Cmd+K`).

Earlier chat, coding, agent, memory, and discovery modules are preserved. They are drafts, not operational integrations. Unimplemented workspaces show unavailable states. Coding writes remain disabled until runner-side authorization and worktree ownership are verified.

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

Configure `AI_STATION_LLM_BASE_URL` for host diagnostics and `AI_STATION_LLM_CONTAINER_BASE_URL` for container clients. `host.docker.internal` maps to the Linux host gateway. A host service bound exclusively to loopback may not be reachable through that gateway; diagnose reachability before changing any service. No external service is reconfigured automatically.

Do not commit `.env` or secrets. The UI/API port is bound to localhost; authentication must be introduced before LAN exposure.

## Images

Set `AI_STATION_PHOTO_PYTHON` and `AI_STATION_PHOTO_SCRIPT` to absolute paths for the existing Python environment and `photo_pipe.py`; `AI_STATION_SD_CLI` helps diagnostics. Restart AI Station after changing configuration. The original script remains independent and unchanged.

Open Images, select an operation and GPU (or Auto), and submit. The worker creates an ordinary Run, reserves a discovered GPU, and calls the native runner. Images appear in Library with actual dimensions, parameters, and source links. Library actions reuse an image for Edit, Recompose, or Upscale. Uploads accept PNG/JPEG/WebP up to 20 MiB and 64 megapixels; upscale output is capped at 64 megapixels. Qwen's existing pipeline does not use seed/negative-prompt controls, so those controls appear only for Juggernaut.

Models must already be installed/cached. The runner sets Hugging Face offline mode; it never downloads missing Juggernaut weights. The external script still owns its existing cache/temp conventions. No GPU inference has been smoke-tested yet; the full integration is tested with a fake pipeline.

Failed, canceled, or interrupted image runs may be explicitly retried after the runner confirms the original process is gone. A retry has a new ID/output path, shares the Task, and links to its parent Run. Inspect partial output before retrying an interrupted run; recovery does not automatically adopt orphaned output or repeat generation.

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

The runner is not a shell daemon. Its enabled API offers host inspection, validated photo launches, and cancellation of recorded, verified process groups. Boot identity, process start ticks, session, and group membership protect against PID reuse. Draft filesystem/Git mutation routes are unavailable. Existing external services are never stopped or imported implicitly. Managed workload containers and remote nodes remain future work.

Uncertain host execution keeps its reservations pending inspection; recovery never blindly repeats side effects. If a worker disappears after dispatch, the run requires inspection when the process is gone. SQLite uses short serialized transactions; multi-node/distributed execution is not implemented. No real Qwen, Juggernaut, Codex, Cursor, or local LLM completion has been smoke-tested yet.

Contributions use reviewed feature PRs to `develop`; `main` is the release branch. See [AGENTS.md](AGENTS.md).

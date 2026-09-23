# AI Station

A local-first AI workstation control plane. Work is represented by **Task → Run → Events → Artifacts**, with a native user-level Host Runner for host operations and a Dockerized control plane as the deployment target.

## Current implementation

The initial run foundation is executable: Alembic schema, SQLite WAL, atomic worker claims, persisted events and cancellation, conservative lease recovery, a private Unix-socket runner, hardware diagnostics, and an HTTP/SSE API. Normal tests exercise a fake executor and disposable local processes; they do not call AI providers or launch GPU workloads.

The repository also preserves earlier draft image, chat, coding, agent, memory, and discovery modules. A draft adapter is **not** an operational integration. Only registered executors and explicitly exposed runner routes are enabled. Coding writes remain unavailable until runner-side permissions and worktree ownership are verified.

## Development checks

Requires Linux, Python 3.12+, and Git. Install dependencies in this repository:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.lock
.venv/bin/pip install --no-deps -e backend -e host-runner
./scripts/check.sh
```

For foundation development, the API can be run with `.venv/bin/uvicorn app.api:app --host 127.0.0.1 --port 8765`. It applies migrations at startup. The worker entry point is `.venv/bin/python -m app.worker_main`; the runner is `.venv/bin/python -m ai_station_runner.main`. Deployment scripts and a frontend are the next slice, not yet part of this baseline.

Configuration uses `AI_STATION_` environment variables or a local untracked `.env`. `AI_STATION_DATA_DIR` defaults to `./data`; all persistent application state belongs beneath it. `AI_STATION_RUNNER_SOCKET` defaults to the user's runtime directory. `AI_STATION_ENABLE_TEST_EXECUTOR=true` enables `POST /api/testing/runs` for a fake-executor integration check; it is disabled by default.

## Architecture and extensions

Read [architecture](docs/architecture.md), [domain model](docs/domain-model.md), [execution model](docs/execution-model.md), and [security model](docs/security-model.md). New executors implement `app.executor.Executor`, use the existing run lifecycle, and commit before external I/O. New capabilities enqueue typed tasks/runs; they do not launch work inside requests. Tools declare schemas and permissions. Providers belong behind the provider adapter. Connectors must expose real capabilities and secret references rather than plaintext credentials.

## Security and limitations

Localhost-only, single-user operation; authentication must precede LAN exposure. The runner has no shell endpoint, does not own external services, and never uses broad process-kill commands. Cancellation verifies boot identity, process start time, session, and process group. Its socket is created with mode `0600`. Filesystem and application-data paths are canonicalized.

Recovery does not replay uncertain side effects. An unavailable host runner keeps ownership and resource reservations pending. Dispatched runs whose worker disappears require inspection after the host process finishes. Coding, agents, and cloud execution are not enabled by this baseline. No real image generation, coding task, or model completion has been smoke-tested.

Contributions use feature branches and reviewed PRs to `develop`; see [AGENTS.md](AGENTS.md).

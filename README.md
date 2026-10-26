# AI Station

A local-first AI workstation control plane: one conversation for questions,
files, images and agent tasks, backed by inspectable execution on your machine.

Open the application, choose a model if needed and describe the outcome you want.
The orchestrator chooses a direct answer, tools or a workflow. Progress, sources,
artifacts and follow-ups stay in the same conversation. Dedicated workspaces
remain available for direct control.

## What you can do

| Workspace | Use it for |
| --- | --- |
| Conversation | Stream answers, attach documents/images/audio, search the web, read pages, analyse files and request media or agent actions. |
| Agents | Review a draft, choose tools and permissions, enable a schedule, run now, pause or stop, inspect results and continue an agent's project. |
| Images | Generate, edit, recompose and upscale using configured photo-pipeline or LUSTIFY runtimes. Reuse ordered references from Library. |
| Video and Avatars | Generate bounded scenes or segmented films; animate a portrait against a recording or generated speech. Inspect progress and resume compatible unfinished work. |
| Audio | Generate speech/music and transcribe recordings with configured local runtimes. |
| Library and Runs | Inspect files, provenance, logs and parameters; edit metadata, reuse results, manage Trash and explicitly confirm permanent deletion. |
| Memory | Inspect, edit and search scoped contextual entries, summaries and provenance, including optional managed CPU embeddings. |
| Models, System and Settings | Discover models, manage owned llama.cpp instances, inspect hardware/health and configure providers, integrations and access. |

Local agents can analyse Excel/CSV/documents and create files, or build a website
in an isolated project with validation and a preview. Projects and advanced Git
workflows retain their existing services; the main product is agent-oriented.
Models, media runtimes and external accounts must be configured before their
capabilities become available. The application reports actual availability.

## Install and start

Prerequisites: Linux, Python 3.12+ with venv support, Git, Docker Engine and
Docker Compose, usable by your user. Host Node is unnecessary: the project frontend
helper uses Docker. A GPU, models and cloud credentials are optional for starting
the control plane and running normal tests.

```bash
git clone https://github.com/jahu/ai-station.git
cd ai-station
git switch develop
cp .env.example .env
./scripts/bootstrap.sh
./scripts/start.sh
```

Open **http://127.0.0.1:8765**. Startup builds the application image, starts or
reuses a compatible native Host Runner, checks health and supervises the deployment
in the foreground. Ctrl+C stops this invocation's owned services and retains data.
Use `./scripts/start.sh --no-build` to reuse an existing application image.

Bootstrap creates project Python dependencies in `.venv`; it does not install
GPU drivers, alter CUDA, download AI models or replace existing AI software.
An existing Runner must match the checkout's native source identity. Inspect active
work before restarting its owning service; the launcher does not replace an
unrelated or incompatible Runner. [Runner compatibility](docs/runner-source-compatibility.md).

## Configure your workstation

Use [.env.example](.env.example) as the configuration reference. Set host paths
for the integrations you actually have, then restart the affected AI Station
services. Start with model roots and an inference provider; media integrations
can be added independently. Diagnostics distinguishes available, unavailable,
misconfigured and unknown integrations.

- `AI_STATION_DATA_HOST_PATH` defaults to `./data`, mounted as `/data` in Docker.
  It contains SQLite, uploads, artifacts, logs and other persistent state. App-owned
  database paths are relative to this root. Containers can be replaced without
  moving external repositories or model files.
- `AI_STATION_MODEL_ROOTS` selects existing host model roots.
  `AI_STATION_ALLOWED_ROOTS` constrains permitted host filesystem access.
  Discovery reads metadata; it does not move or delete model files.
- AI Station can load compatible discovered GGUFs through an owned **llama.cpp**
  runtime, including discovered multi-GPU configurations. Existing llama.cpp,
  Ollama and other compatible servers can also be configured as providers.
  Use Models and the conversation model picker; a model's advertised context
  alone does not establish that the chosen profile fits your hardware.
- `AI_STATION_LLM_BASE_URL` is the host inference endpoint. The default
  `AI_STATION_LLM_TRANSPORT=runner` reaches loopback-only host servers through the
  private Runner. For direct container networking use
  `AI_STATION_LLM_CONTAINER_BASE_URL`; Compose provides `host.docker.internal`.
  [Provider and networking guide](docs/local-model-bridge.md).
- Configure the original photo pipeline and other media runtimes using their
  documented environment keys. AI Station adapts existing installations and
  preserves the original scripts and model files.

Keep `.env` and secrets out of Git. Secrets belong in environment/secret files or
configured secret references, not prompts or ordinary metadata responses.
[Configuration and operations](docs/operations.md) covers backups, upgrades,
owned process recovery and guarded restore.

## Access from another device

Localhost is the default listener. To add a home-LAN listener, first save an
operator password in Settings, then configure `AI_STATION_LAN_HOST` with the
workstation's private IPv4 address. LAN access requires an authenticated operator
session; public bind addresses are refused. [LAN access](docs/private-network-access.md).

Settings → Access → **Access from anywhere** provides optional private Tailscale
setup using an AI Station-owned userspace service. The owner must sign in, approve
HTTPS and verify their device's remote connection. An installed service or
`NeedsLogin` is not remote readiness. This does not expose a public Funnel or
change unrelated system Tailscale services.
[Private access and acceptance](docs/plans/private-tailnet-access.md).

Browser microphone capture requires a secure browser context and device consent;
HTTP access over a LAN does not grant microphone permission. SMTP delivery likewise
requires your configured account and a reviewed message/recipient or explicitly
activated scoped agent policy. Search and public-page tools need no finance API key.

## How execution works

The architecture is a modular monolith: **Docker control plane + native user-level
Host Runner**, communicating through typed HTTP over a private Unix socket.

The control plane owns the UI/API, metadata, scheduling and durable run engine.
The Runner owns constrained native work such as Git worktrees, installed CLI/media
adapters, owned processes and hardware inspection. Container executors are also
launched behind that controlled boundary.

Every application workload follows **Task → Run → Events → Artifacts**. HTTP
handlers enqueue; workers execute. GPU/worktree reservations, live events, Stop,
approvals and conservative recovery belong to the shared lifecycle. Three worker
slots are the default; `AI_STATION_WORKER_SLOTS` can configure 1–8 slots.

The control plane receives no privileged container, Docker socket or unrestricted
host mount. The Runner exposes typed operations rather than an arbitrary shell.
Canonical root checks, process identity and owned groups constrain filesystem and
cancellation actions. External services are not implicitly adopted or stopped.
Read the [architecture](docs/architecture.md), [domain](docs/domain-model.md),
[execution](docs/execution-model.md) and [security](docs/security-model.md) contracts.

## Development and verification

```bash
./scripts/dev.sh                 # Runner, Docker API/worker/scheduler and Vite
# Development UI: http://127.0.0.1:5173
./scripts/check-all.sh           # Python, frontend, Compose and image checks
./scripts/check.sh               # Python lint/format and backend/Runner tests
./scripts/frontend.sh ci         # Install frontend dependencies
```

Normal tests use temporary databases, fake providers and disposable processes;
they do not consume cloud tokens or launch model/GPU generation. Real integration
and browser/recovery probes are separate opt-ins. See [verification](docs/verification.md)
for commands and the distinction between unit, integration and actual hardware
results. Tests passing is not a claim that every model or quality profile works.

The Polish [operator QA package](docs/qa/README.md) contains stable cases, XLSX/CSV,
synthetic input files and release-specific instructions. Its offline feedback
importer preserves returned answers and produces a triage list without executing
spreadsheet formulas or changing the app. Final operator handoff is separate from
internal qualification; unperformed operator tests remain **Nie testowano**.

Contributions use feature/fix branches, full diff review and successful checks,
then squash PRs into `develop`. Hosted Actions are currently manual; equivalent
local verification is authorized by the maintainer. Actual failing checks are
never waived. Follow [AGENTS.md](AGENTS.md); `main`/`master` are protected release
branches and are not autonomous push/merge targets.

## Extend AI Station

- **Executor:** implement the existing `app.executor.Executor` contract; test
  permissions, cancellation, recovery and resource release before registration.
- **Capability:** validate intent and scoped inputs, then enqueue ordinary Runs
  through shared domain services.
- **Tool:** declare schemas, permissions, risk, timeout and a real implementation.
- **Provider:** use the provider adapter boundary rather than tying domains to one
  model server. Preserve actual local/external disclosure and secret references.
- **Connector:** expose real health and capabilities with server-side credentials.
  Incomplete adapters stay unavailable.

## Detailed guides and current scope

| Topic | Guide |
| --- | --- |
| Models and local inference | [Models](docs/models.md), [managed llama.cpp](docs/managed-llama.md), [chat](docs/local-chat.md) |
| Images and results | [Images](docs/image-workflows.md), [Library](docs/library.md), [image models](docs/plans/krea2-lustify-images.md) |
| Media | [Long jobs](docs/long-media.md), [video](docs/video.md), [avatars](docs/avatars.md), [audio](docs/audio.md) |
| Agents and projects | [Agents](docs/agents.md), [agent-first direction](docs/plans/agent-first-product.md), [projects](docs/projects.md), [local code](docs/local-coding.md) |
| Context and tools | [Memory](docs/memory.md), [web search](docs/web-search.md), [page reading](docs/plans/chat-page-reading.md), [Skills](docs/skills.md), [connectors](docs/connectors.md) |
| Operations | [Operations](docs/operations.md), [private access](docs/private-network-access.md), [QA](docs/qa/README.md) |

Supported settings and recorded qualification are distinct. The [release audit](docs/plans/platform-acceptance-audit.md)
and [product ledger](docs/product-completion.md) retain exact tested profiles,
adverse results and remaining gates. Longer media may show identity, color or
lip-sync limitations; a successful decode alone is not a visual-quality pass.

Actual outside-LAN access and operator-inbox delivery require owner-controlled
setup and acceptance. Remote execution nodes, additional runtime/connector
families and standalone IDE parity remain future work. Existing code/worktree
services are retained. New integrations must meet the same observable permission,
Stop, artifact and recovery contracts before being presented as operational.

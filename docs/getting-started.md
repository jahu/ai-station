# Setup, configuration and development

AI Station is source-available under [PolyForm Noncommercial 1.0.0](../LICENSE).
Permitted noncommercial use is free; other commercial use requires a separate
written license. See [licensing](../COMMERCIAL.md) and [contributing](../CONTRIBUTING.md).

Run the commands below from the repository root. For the product overview, see
[AI Station](../README.md).


Prerequisites: Linux, Python 3.12+ with venv support, Git, Docker Engine and
Docker Compose, usable by your user. Host Node is unnecessary: the project frontend
helper uses Docker. A GPU, models and cloud credentials are optional for starting
the control plane and running normal tests.

```bash
git clone --branch master https://github.com/jahu/ai-station.git
cd ai-station
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
unrelated or incompatible Runner. [Runner compatibility](runner-source-compatibility.md).

## Configure your workstation

Use [.env.example](../.env.example) as the configuration reference. Set host paths
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
  [Provider and networking guide](local-model-bridge.md).
- Configure the original photo pipeline and other media runtimes using their
  documented environment keys. AI Station adapts existing installations and
  preserves the original scripts and model files.

Keep `.env` and secrets out of Git. Secrets belong in environment/secret files or
configured secret references, not prompts or ordinary metadata responses.
[Configuration and operations](operations.md) covers backups, upgrades,
owned process recovery and guarded restore.

## Access from another device

Localhost is the default listener. To add a home-LAN listener, first save an
operator password in Settings, then configure `AI_STATION_LAN_HOST` with the
workstation's private IPv4 address. LAN access requires an authenticated operator
session; public bind addresses are refused. [LAN access](private-network-access.md).

Settings → Access → **Access from anywhere** provides optional private Tailscale
setup using an AI Station-owned userspace service. The owner must sign in, approve
HTTPS and verify their device's remote connection. An installed service or
`NeedsLogin` is not remote readiness. This does not expose a public Funnel or
change unrelated system Tailscale services.
[Private access and acceptance](plans/private-tailnet-access.md).

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
Read the [architecture](architecture.md), [domain](domain-model.md),
[execution](execution-model.md) and [security](security-model.md) contracts.

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
and browser/recovery probes are separate opt-ins. See [verification](verification.md)
for commands and the distinction between unit, integration and actual hardware
results. Tests passing is not a claim that every model or quality profile works.

The Polish [operator QA package](qa/README.md) contains stable cases, XLSX/CSV,
synthetic input files and release-specific instructions. Its offline feedback
importer preserves returned answers and produces a triage list without executing
spreadsheet formulas or changing the app. Final operator handoff is separate from
internal qualification; unperformed operator tests remain **Nie testowano**.

Ordinary generated results appear in Library and their Runs. Isolated acceptance
probes have separate databases/data roots and record file locations in their
receipts. Developer exports such as `data/test-previews` are independent local
copies; they do not automatically create entries in the running Library.

Contributions use feature/fix branches, full diff review and successful checks,
then squash PRs into `develop`. Hosted Actions are currently manual; equivalent
local verification is authorized by the maintainer. Actual failing checks are
never waived. Follow [AGENTS.md](../AGENTS.md); `main`/`master` are protected release
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
| Models and local inference | [Models](models.md), [managed llama.cpp](managed-llama.md), [chat](local-chat.md) |
| Images and results | [Images](image-workflows.md), [Library](library.md), [image models](plans/krea2-lustify-images.md) |
| Media | [Long jobs](long-media.md), [video](video.md), [avatars](avatars.md), [audio](audio.md) |
| Agents and projects | [Agents](agents.md), [agent-first direction](plans/agent-first-product.md), [projects](projects.md), [local code](local-coding.md) |
| Context and tools | [Memory](memory.md), [web search](web-search.md), [page reading](plans/chat-page-reading.md), [Skills](skills.md), [connectors](connectors.md) |
| Operations | [Operations](operations.md), [private access](private-network-access.md), [QA](qa/README.md) |

Supported settings and recorded qualification are distinct. The [release audit](plans/platform-acceptance-audit.md)
and [product ledger](product-completion.md) retain exact tested profiles,
adverse results and remaining gates. Longer media may show identity, color or
lip-sync limitations; a successful decode alone is not a visual-quality pass.

The owner has confirmed private Tailscale access. SMTP remains optional and its
real-inbox acceptance is deferred; push notifications are
[future work](plans/notification-delivery.md). Remote execution nodes, additional runtime/connector
families and standalone IDE parity remain future work. Existing code/worktree
services are retained. New integrations must meet the same observable permission,
Stop, artifact and recovery contracts before being presented as operational.

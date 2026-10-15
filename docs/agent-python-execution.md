# Isolated Python execution for agents

Implementation target: the first execution component of the
[agent-first plan](plans/agent-first-product.md). This increment provides the
Runner contract and ordinary executor infrastructure. Agent script generation,
automatic workspace provisioning, spreadsheet upload/preview and agent UI wiring
remain subsequent parts of the same vertical slice; do not advertise a working
spreadsheet agent from this component alone.

A Python Run freezes an owned project's worktree reservation, a canonical `.py`
entrypoint and SHA-256, selected stored input artifact identities/hashes/sizes,
required output filenames and a 1–600 second execution budget. The worker
publishes the typed request over the existing private Runner socket. No caller
supplies an interpreter, command string, image, environment variables, mounts or
network configuration. `python_execute` is an explicit capability grant alongside
filesystem/workspace permissions, never an implication of ordinary chat.

The Runner verifies worktree/project/branch/HEAD ownership, snapshots only the
selected script and inputs, and pins an already installed `ai-station-python:*`
image with the exact expected entrypoint and protocol. Docker create is journaled
before dispatch. Replay must match the immutable request; missing owner process
or an uncertain create response requires inspection rather than duplicate work.

The workload is a non-root CPU container with its own PID/network namespaces,
network disabled, a read-only root, no capabilities, no privilege escalation,
64 processes, 512 MB RAM/swap limit, one CPU, bounded descriptors and private
64 MB `/tmp` and `/outputs` tmpfs mounts. Only frozen inputs are mounted, read-only.
There is no host output mount, project checkout/Git metadata mount, Docker socket,
GPU, home directory, credential, host process tree or arbitrary app data access.
Generated code reads `AI_STATION_INPUTS` (JSON mapping staged filenames to paths)
and writes into `AI_STATION_OUTPUT_DIR`. The image includes standard Python and
pinned openpyxl; installing packages is not implicit script execution.

The image-owned wrapper runs the script with isolated Python module loading,
wraps bounded stdout/stderr, kills its owned child process group and collects only
required outputs. It rejects symlink components, hardlinks, devices, FIFOs,
oversized or changing files. Each file is at most 4 MB; at most eight files and
16 MB total are transferred as bounded protocol messages. The tmpfs bounds all
other generated file writes as well. Missing outputs make a zero-exit script
unsuccessful. Script failure cannot publish successful output artifacts.

The native job validates every protocol field and output identity and stores
exports outside the container's reach. It removes only the exact owned container
ID/image/labels. Stop serializes with create and the process manager retries
cleanup after a dead wrapper; uncertain cleanup is `interrupted`, never success.
Stale-worker recovery retains inspection/lease state when this Runner-managed
container cannot be reached. No script or container is blindly replayed.

The control plane verifies all exported sizes/hashes/paths before adopting any
output. The actual source script and execution report are artifacts too, with
input/source lineage. Existing Run events, logs, cancellation and inspection are
reused. Active HTML or other unknown output types are downloadable binary files;
no generated document is served as trusted application HTML.

Build the optional CPU image explicitly:

```bash
docker build -f python-executor/Dockerfile -t ai-station-python:local .
```

Configure `AI_STATION_PYTHON_IMAGE=ai-station-python:local` for the native Runner.
No model, driver or external runtime installation is involved. The image is never
pulled automatically by a workload request. Availability is observed through
`GET /v1/python/capabilities`; typed dispatch/report use `/v1/runs/python`.

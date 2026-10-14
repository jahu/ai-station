# Security model

> Implementation status: this document includes the target architecture. The operational slice includes Docker startup, the React dashboard, run inspector/SSE, fake worker execution, private runner transport, process ownership, telemetry history, and diagnostics. The image workspace and photo executor are enabled with fake-pipeline integration coverage. Local chat is enabled with fake-provider integration coverage. Local agents now have explicit activation, durable schedules, bounded context tools, GET of reviewed public pages, versioned Skills as instruction packs, sequential or gated workflow steps, optional bounded registry tool calling during the report, saved retry policies and in-app notices. Named HTTP GET connectors are operational; account browser automation and other connector kinds are not. Bounded Cursor file-edit proposals, review artifacts and separate validation Runs are operational. Other coding adapters remain inactive. See README for runnable commands and limitations.


AI Station is a single-user workstation application. The default network exposure is loopback only. When an operator password hash is stored, loopback API requests require a session cookie except health, login status, login and logout. A non-loopback bind is refused even after that hash exists because LAN/node transport is unpublished. Do not publish port 8765 on a LAN or the public internet.

## Control plane

Containers run without `--privileged`, without extra capabilities, and without `/var/run/docker.sock`. The only host mounts are the application data directory and the Host Runner socket directory. Compose sets `user` to the host uid/gid so a mode `0600` socket works without making it world-writable. The socket directory itself is the per-user runtime dir (`0700`).

The process inside the container listens on all container interfaces so Docker can proxy `127.0.0.1:8765`. The host publish address is `127.0.0.1`. Startup refuses `AI_STATION_BIND_HOST` values that are not loopback.

## Host Runner

The runner is a user-level process. It does not use sudo. It binds a Unix socket created with mode `0600` and does not listen on TCP in this version.

There is no `POST /shell`. Each operation has a schema. Subprocesses are started with an argv array (`shell=False`) in a new session so cancellation signals only that process group.

## Filesystem

Allowed roots come from configuration: application data, model roots, and project roots. The runner resolves canonical paths and rejects:

- `..` segments
- absolute paths that escape a root after symlink resolution
- symlink components whose target leaves the root
- null bytes and non-normalized absolute injection

Project commands are the argv lists stored on the project. The runner refuses `shell=True`, `sudo`, and shells invoked as the executable (`bash`, `sh`, `zsh`). Agents cannot replace those commands during a run.

## Git

Coding work happens in a fresh worktree and a new `ai/...` branch. The user's current checkout is not the cwd of an agent. Explicit worktree removal deletes only the recorded owned checkout and that local task branch. Unregistered paths, the current checkout and GitHub remotes are never deleted. Protected branches reject automatic commits, pushes, history rewrites, and merges. Force-push is not implemented. Push and opening a pull request require an approval record. Applying or restarting a changed AI Station checkout is not automatic.

## Permissions

Coding's existing `workspace_write` permission covers checked selected source
removal inside the owned worktree. It exposes no general deletion operation.
Review identifies every removal; commit remains a separate `git_write` Run.
Repairs cannot introduce removals. See [source removal](coding-file-removal.md).

Runs store an effective permission list. There is no universal full-access flag. Profiles grant named capabilities (`filesystem_read`, `workspace_write`, `git_read`, `git_write`, `network_read`, `network_external`, `shell_project_commands`, `external_ai`, `manage_station`, and others). Missing permission fails the tool call. SQLite backup Runs require `manage_station`; agents do not receive it. Inspecting a copy is read-only. Restore and image rollout are unpublished.

## Network tools

HTTP fetch is a real tool and is off unless the run has `network_read` (GET) or `network_external` (POST). URLs are resolved and rejected when any address is loopback, private, link-local, reserved, or multicast. That blocks trivial SSRF to the host's model servers and cloud metadata endpoints. Local coding exploration may GET public pages under that rule. Agents may GET up to three explicitly reviewed public URLs stored on the definition; the model cannot add URLs. Named HTTP connectors reuse the same public-URL rule for a single GET, with optional Bearer secret references that never appear in API responses. Chat web search is an explicit per-message opt-in through a configured private SearXNG service. Only the query leaves the control plane; history, memory and attachments are not sent to search engines. Results are bounded untrusted snippets, with persisted provenance; Chat and agents do not fetch arbitrary search-result pages. Interactive/account interactive/account browser automation remains unavailable.

## Operator credential

The `operator_auth` setting stores PBKDF2-SHA256 material only. Responses omit password, salt and hash. Rotation and removal require the current password. After the hash exists, the loopback UI/API are gated by `ais_operator` (HMAC in `operator_session`, httpOnly, SameSite=strict, not Secure). The cookie idles out after 30 minutes without authenticated API use; activity refreshes `last_seen_at` and the idle `Max-Age`. A 12-hour absolute expiry still wins. Idle or absolute expiry deletes the HMAC and clears the cookie. Health and login remain public so the workstation can unlock itself. Node invitations require that hash to exist; join tokens are HMAC-SHA256 and returned once. Registration is accepted only on the loopback API and still needs the session. LAN transport stays unpublished.

SQLite backups require `manage_station` and write under the data root. Inspecting a copy re-opens that file read-only and never restores over the live database. Compose image inspect asks the Host Runner to compare the `ai-station:local` tag with running API/worker/scheduler containers; it does not build, tag, start or stop. Compose shutdown does not pass `--volumes`. Interrupted-run acknowledgement records inspection only and does not replay side effects. Held-lease status is inspect-only and does not recover or restore. See [operations](operations.md).

## Secrets

Secrets are environment variables or files outside Git. Database rows store references (`env:NAME` or a data-root file path). Logs, events, errors, and prompts pass through a redactor for common token patterns. Connector and chat-provider responses omit secret values; the UI may show that a secret is present and the environment reference name. Chat provider URLs cannot embed credentials. External chat providers require a secret reference and fail closed when it is missing. The built-in local provider may run without a key.

## External runtimes

Discovered llama.cpp, Ollama, or ComfyUI processes are `external`. Discovery never stops, restarts, or rewrites them.

## Autonomy

Agent drafts are created disabled. The UI shows prompt, tools, permissions, and schedule before enablement. Optional per-Run approval parks execution in `waiting_for_approval` until the user grants or denies it; the worker does not start parked Runs. GitHub publication still requires an explicit granted Approval at enqueue.

## Image boundaries

The typed photo endpoint accepts bounded values and writes the fixed UUID path for its Run. Sources must be validated images inside artifact storage, without symlink redirection. Uploads are bounded by request/file size and decoded image dimensions; HTML/SVG are not accepted as images. Artifact delivery uses canonical data-root paths and nosniff headers. Draft filesystem/Git mutation adapters remain disabled; owned worktree preparation has a separately validated endpoint described below.

## Read-only Git inspection

The enabled validation/status/diff endpoints use a separate bounded inspection adapter. It rejects option-like revisions, resolves branch/commit identifiers before diffing, clears inherited Git environment overrides, and disables repository fsmonitor commands, filters, text conversion, external diff helpers, hooks, and optional index writes. Git can otherwise run configured helpers even during inspection; see [Git diff options](https://git-scm.com/docs/git-diff#Documentation/git-diff.txt---no-ext-diff) and [fsmonitor configuration](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefsmonitor).

Worktree roots, common Git metadata, and object stores must resolve inside configured roots. Repositories using alternate object stores or partial-clone fetch configuration are rejected in this slice. Inspections stop after 15 seconds per subprocess or 2 MiB combined output; failure terminates only the owned command group. Simple branch names and commit IDs are accepted as diff bases; revision expressions are not accepted. Draft Git mutations remain disabled and do not share the inspection adapter.

Project registration uses this inspection boundary before storing a canonical host path. The control plane never opens repository files directly. Configuration updates keep mandatory protected branches and reject stale versions or active project Runs. Stored argv commands and optional task-branch policy preferences do not expose a command, commit, push, or PR endpoint. Worktree preparation uses a separate typed Run endpoint with derived paths/branches, a durable runner reservation, explicit capability permissions, and owned-process cancellation. See [Projects](projects.md).

## Memory boundaries

Memory scope/source IDs must resolve to existing records; mismatched source conversations and Runs are rejected. Scope and provenance cannot be reassigned by editing content. Chat consumes only enabled pinned global and matching conversation entries. Historical context remains in Run parameters after disabling or deleting an entry. See [memory contracts](memory.md).

## Model discovery

[Model discovery](models.md) runs as a managed native process through Task → Run → Events → Artifacts. Only host-configured roots are scanned, and only metadata is persisted. Known successful completion is required to update observations; unavailable roots and missing files remain distinguishable. No runtime ownership is inferred. Explicit installation re-stats a snapshotted path inside those roots and may inspect a locally installed llama.cpp image ID. It never opens model contents, never pulls images, never copies weights and never starts a runtime.

## Local agents

[Agent lifecycle](agents.md) uses the shared queue, local provider, Run events and Markdown artifacts. Explicit telemetry and own-scope memory tools gather bounded context as persisted child Runs before inference. Optional bounded tool calling during the report is limited to selected operational registry tools; HTTP URLs and search queries cannot be chosen by the model. Versioned Skills are instruction files snapshotted by hash; they cannot add permissions, tools or Host Runner operations. A model cannot invent extra workflow steps, tools or commands; unknown keys fail closed without publishing children or executing calls. Definitions start disabled; unsupported tools block activation. Retry is an explicit saved policy and never silently repeats side effects. Notices stay in the control plane. Scheduling is serialized, persistent and non-overlapping.

## Runtime observations

The [external runtime registry](runtimes.md) records bounded native process observations and the configured local endpoint’s model-discovery health through an explicit worker Run. It grants no runtime management capability and preserves earlier observations after errors.

## Host loopback model access

Compose defaults to the [typed local-model bridge](local-model-bridge.md) over the existing private Runner socket. Model listing and bounded streamed completions target only the configured local endpoint, with no redirects or caller-selected URL. Canceling a Run closes the upstream response. Direct provider transport remains available for native development and explicitly configured container-reachable endpoints.


Saved project test/lint/build commands now run through the worker and a managed native sandbox in an owned worktree. Commands are snapshotted from versioned project settings, Git metadata stays read-only, networking is blocked, and results become events plus a JSON artifact. Declared Python dependencies install through the same sandbox with `--only-binary :all:` and either a local `vendor/` directory (no network) or `https://pypi.org/simple` after public DNS confirmation. Manifest URLs, VCS refs and extra indexes are rejected. See [project validation and dependency installation](coding-boundary.md). The [bounded Cursor adapter](coding-cursor.md) adds explicit external-AI consent, checked selected-file writes (complete rewrites or unique snippet replacements), review artifacts and a separate validation Run; the [local coding adapter](local-coding.md) reuses those checked selected-file writes with local inference, bounded public GET/search during exploration and no external-AI permission. Codex uses the same write boundary. Claude Code remains unavailable. File deletion is not authorized.

## Managed llama.cpp containers

The [llama.cpp adapter](managed-llama.md) is the first enabled container runtime executor. Only the native Runner invokes Docker with fixed argv templates. It pins an already-installed image ID, disables automatic pulls and networking, drops capabilities, runs as the host user and mounts a single validated model read-only plus private socket storage. Container IDs, ownership labels and immutable manifests constrain inspection/stop. Manifests are outside the container-writable mount. Inference accepts runtime IDs through the private Runner socket, never caller URLs.

## Automatic managed-model scheduling

Automatic reload reuses a previously selected GGUF and GPU/context preset. Idle eviction only queues typed stop operations for owned llama.cpp instances; it does not stop external providers. Health and restart Runs target only AI Station-owned llama.cpp containers. New consumers and eviction are serialized in the metadata transaction. Unknown ownership/state requires inspection instead of duplicate loading. No new shell, mount, network or download permission is granted.

Agent web research requires a separately saved public query and explicit `network_read` permission. Only that query reaches the configured search service; goals, memory and model output cannot select network requests. Search observations remain untrusted context. Shared search execution checks cancellation and agent deadlines, and reports do not render remote images.

Agent HTTP fetch requires separately reviewed public URLs and the same `network_read` permission. DNS answers and redirects are re-checked; private targets fail closed. Fetch observations remain untrusted excerpts. The model cannot choose additional URLs, POST, or run a browser.

Local coding exploration exposes validated listing, literal search and reads inside the allocated worktree, plus GET of public http(s) URLs (including automatic fetch of up to three public URLs written in the task) and optional configured SearXNG queries. Hidden/credential paths, symlink escapes, loopback/private/link-local/multicast targets, credentialed URLs, non-80/443 ports and arbitrary operations are rejected after DNS resolution. Redirects are re-validated. JavaScript is not executed; interactive/account browser automation remains unavailable. The same process-group cancellation and deadline cover exploration, fetches and proposal inference. No shell, external AI, caller-selected inference URL or POST to arbitrary hosts is granted. Read and fetch observations remain inspectable in the coding review.

Agent report retention requires explicit `memory_write` on the snapshotted Run. It writes only an observation under that Run's agent scope, never global/project/conversation memory. Successful final state and memory/FTS writes are atomic. Partial or failed output is not retained as memory. Reports remain untrusted reference data, and the user can disable or delete saved entries.

Local repair accepts only a source Run ID after confirmed validation failure. The control plane serializes project work and preserves model, file scope, guidance and validation commands. The Runner independently verifies the previous successful local report, unchanged task base and original scope. Failure context comes from redacted persisted events with a bounded excerpt. Old reviews cannot be committed after a repair is requested; the cumulative new review uses the existing hash-checked commit path.

Automatic local repair requires an explicit task budget of one or two attempts (default zero); the budget radios reuse the shared list keyboard with unique Repair names and do not start a coding Run. Strict validation rejects booleans, strings and larger budgets. Only confirmed failed validation uses that budget. Model output cannot change it, choose new commands/files, trigger external inference or authorize commits. Cancellation, uncertain completion and execution failures do not queue repair.

## Reviewed GitHub publication

Publication requires project permission for task-branch push and integration PRs plus an explicit approval bound to the exact commit, repository, base and PR text. The worker verifies that approval before dispatch. The Runner validates the successful owned commit, unchanged HEAD/origin, task ref and non-production base again. The task parent must match the current remote integration head, preventing accidental publication of unreviewed local ancestors.

Only credential-free github.com origins are supported. Network Git runs with a fresh private bare Git directory, the validated object store, disabled hooks, clean system/global configuration and a fixed GitHub credential helper. Source hooks, credential helpers and URL rewrites are not used. Existing gh authentication stays in its normal host location; credentials never enter request files, database records or logs. The managed process has bounded output/time and owned-group cancellation. Push and PR creation are separate remote effects: partial progress is retained, uncertain outcomes require inspection, and no automatic republish/force-push/merge is available.

Codex uses explicit external-AI consent bound to the selected provider, an empty provider workspace and a named read-only filesystem profile. The CLI retains its own authentication reference; AI Station copies no credential files. Shell, apps, plugins, hooks, browsing, host skills and child agents are disabled. Returned tool actions are rejected, selected snapshots alone form the task payload, and only the shared Runner write boundary applies proposals to the owned worktree. Uncertain completion is not retried.

Managed project setup accepts a name and generated identifiers, never a destination path. It initializes only a newly reserved application-owned directory with Git helpers/hooks disabled and does not download dependencies. Explicit dependency installation later reads declared manifests in an owned worktree; it does not accept caller pip argv. Coding follow-ups serialize against active project Runs, retain the owned worktree boundary and supersede older reviews. External automatic source exploration requires source-sharing consent; provider tools stay disabled and only bounded Runner source operations execute.

Workstation inspection from Chat uses an ordinary read-only worker Run and the existing hardware endpoint. It accepts no filesystem path, URL or command and never controls processes. Sensor fields are allowlisted; runtime states remain timestamped saved observations. Recent planner context is bounded same-conversation reference text; metadata, earlier scopes and consents are not inherited. See [station inspection](station-inspection.md).

## Model context inspection

The existing private model-verification operation can optionally inspect GGUF metadata with filesystem-read and model-management permissions. It enforces configured model roots, the discovery observation, a regular read-only file descriptor, a 32 MiB header budget and bounded entries/arrays. It skips tokenizer strings and never opens tensor data. Unsupported headers retain an explicitly recorded fallback estimate. Cancellation before dispatch does not start or stop another process. See [context estimation](model-context.md).

## Vision input boundary

Image inspection reads explicit app-owned artifact IDs and uses local owned runtimes. The worker bounds source files and decoded pixels, normalizes orientation/transparency and creates transient inline data. The Runner validates inline raster format/size/pixels and rejects URLs or paths. Validation responses omit original request values. Projector mounts follow configured model roots and discovery observations; runtime recovery preserves their immutable identity. Model-operation children roll back on rejected inspection. See [local vision](chat-vision.md).

Local coding agents require the exclusive reviewed coding tool and an explicit project. Its write/Git/validation permissions are visible before activation; the model cannot choose another project or generated command. Gated execution waits before worktree creation. Deadlines request cancellation only for the associated coding Runs, and human continuations drop the old deadline. See [coding agents](agent-coding.md).

Image generation and edits can now queue a dependent 4× Upscale with the existing photo executor. The result/completion and child publication are atomic, and Images follows the active stage after refresh. See [image workflows](image-workflows.md).

Portraits can now use a voice reference and typed Polish speech through a sequential Chatterbox → EchoMimic workflow, retaining both outputs and following the active stage after refresh. See [speaking avatars](speaking-avatars.md).

## Public connection identity

Public GET tools in both the control plane (agent pages and HTTP connectors) and
Host Runner (Local Coding references) connect to a numeric IP from the checked
DNS result. Every returned address must be public and non-multicast; 6to4, Teredo
and the well-known NAT64 prefix are denied to prevent embedded private IPv4
routing. A subsequent DNS change cannot redirect that request into the workstation network. Redirects
repeat URL and DNS validation before connecting, within the existing hop/body/time
limits.

The original authority stays in `Host`, TLS SNI and certificate hostname
verification; returned page URLs and relative links keep their public URL. Each
hop gets a fresh client so hosts sharing an IP cannot reuse a TLS connection
verified for another domain. HTTP connectors retain explicitly configured headers
only while the origin (scheme, host and port) stays the same. An origin-changing
redirect drops all extra headers, including Bearer tokens, API keys and cookies;
response cookies are never carried between hops. There is no credential downgrade
or ambient session import.

This uses the documented [HTTPCore SNI extension](https://www.encode.io/httpcore/extensions/#sni_hostname).
Normal tests exercise actual HTTPX/HTTPCore transports with fake socket streams,
assert checked connection IP, verified TLS configuration and original Host/SNI,
and cover rebinding answers, IPv6, multicast, private redirect DNS and secret
stripping. They never fetch the public internet.


Public-page browsing is available as an optional isolated agent workflow tool,
with JavaScript, Library screenshots, bounded text, exact container ownership and
cancellation/recovery. It requires an explicitly built local executor image and
configuration; missing setup remains unavailable. See [browser setup and security](browser.md).


## Explicit project memory

The optional **Project memory** tool requires a saved linked project and the
separate `project_memory_read` permission. A link alone grants no access. Reads
remain within that snapshotted project, save exact context and provenance in an
ordinary child Run and never promote entries into another scope. Model arguments
cannot change the target. See [retrieval bounds and retention](memory.md#explicit-project-memory).


Wan scene-video requests select no commands or graphs. The fixed native job
uses administrator-configured existing safetensors, app-owned validated image inputs
and UUID-derived outputs, an allowlisted environment with private Run caches and
offline model flags. It starts no ComfyUI server or custom nodes. Cancellation
and inspection use the shared owned-process group journal. See [video](video.md).

GPU compute-process observation is a fixed, parameter-free native query. Only
UUID, PID, basename and reported memory leave the Runner; command lines and
environments are never read. Live polling is separate from permanent telemetry
sampling. Unavailable/partial data remain explicit. This grants no process
ownership or cancellation capability.

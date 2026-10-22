# Isolated interactive agent website preview

Status: offline renderer plus typed Native Runner session/action ownership are
implemented and real-tested. Control-plane Runs/resources and agent UI integration
are still pending; the production configuration does not enable this adapter. Until all lifecycle
contracts pass, this capability must remain unpublished/unavailable. A screenshot
alone does not establish interactive preview completion.

## Product outcome

After a website agent builds successfully, its Workspace offers Preview beside
source/build downloads and follow-up instructions. The operator opens the actual
static build, clicks controls, types into its forms and scrolls, then continues
work in the same agent/Task. Desktop and phone use the same authenticated API.
Existing build archives and reviews remain immutable. Preview is not publication,
a development server, backend hosting or a grant to access external sites.

## Execution boundary

Run untrusted generated JavaScript inside the existing style of optional Chromium
workload container, never in the authenticated control-plane origin. Reuse the
project's already installed browser image/dependencies through an explicitly built
preview workload image. No automatic pulls, public ports or host browser profile.

The container is non-root, CPU-only, network-disabled, read-only, capability-free,
no-new-privileges and bounded by RAM/CPU/PID/time/tmpfs limits. It has no host mount,
Docker socket, credentials, model access, home directory or project checkout.
The native parent supplies only a verified, immutable static-build archive through
bounded resource messages. Canonical relative member names, unique regular files,
ZIP budgets, input hash and successful same-Task build provenance are rechecked.

Chromium navigates a synthetic internal origin. GET is fulfilled from those frozen
archive members; other origins, schemes, non-GET requests, popups, downloads,
WebSockets and service workers are blocked. The container network namespace is
the final boundary, independent of request interception. The optional local
renderer is not the existing public-page network broker and grants no network tool.
Only rendered PNG frames cross back to the station UI. No iframe executes user
JavaScript or obtains operator cookies. External links and APIs are visibly blocked.

## Typed interaction and ownership

The initial preview is an ordinary operator inspection Task/Run dispatched by a
worker through the private Runner socket. It retains the source project, source
build Run/Task and artifact provenance, but is not an autonomous agent execution.
Actions belong to that preview Task. Do not hide project identity to evade busy
checks: explicitly classify this immutable artifact viewer as non-mutating in
shared project admission checks. Agent coding can continue in its separate Task
while the preview still shows the frozen older build; label that build clearly.
Close targets only the preview Task, and coding Stop retains its own task scope. One preview per Runner is admitted initially, with a
durable exclusive resource lock, conservative RAM reservation and a bounded active
session (maximum 15 minutes). A live preview occupies one existing worker slot;
normal deployment has three. Native admission also enforces the single-session
limit so one API cannot consume all worker slots with previews. No new queue or
service is required. Future session scheduling can extend this without changing
agent or capability APIs.

Every interaction is an ordinary child Run, not a shell/evaluate endpoint. Supported
operations are bounded viewport clicks, literal text insertion, enumerated keys,
scroll and reset. Requests bind preview Run identity, action Run/receipt identity
and the expected frame revision. Coordinates refer to the captured viewport.
Native replay returns the same receipt; stale revisions and conflicting receipt
bodies cannot repeat a click. No arbitrary URL, script, selector, interpreter,
environment, mount or container command is accepted.

The native owned wrapper multiplexes container resource requests and a private
validated action mailbox, retaining the current browser context between actions.
Each action has a separately registered native proxy process, so ordinary process
inspection/recovery can identify an interrupted send. Native admission permits
one session and one action proxy at a time. Queued cancellation has no browser
effect; cancellation after an uncertain send closes only its owning preview.
The mailbox and container are identified by preview Run UUID, request digest and
immutable image/container IDs. Actions write only canonical app-owned UUID records.
Process ownership, cancellation and lost-create inspection reuse the existing
native job/container contracts. A close/Stop cleans up only that owned process
group/container. Crash, stale lease and uncertain cleanup interrupt the session
without replay and retain inspection/resource holds until absence is confirmed.

The worker adopts validated PNG frames as immutable artifacts with source build,
preview/action Run and revision provenance. A compare-and-swap update selects the
current frame. Parent polling must refresh metadata and never overwrite a newer
action frame. Operator close is an explicit cancellation, not successful workload
completion. Leaving the page does not silently kill work; the UI shows remaining
session time and Close. Reload restores the live session/frame or its honest
interrupted/expired state. Rebuilds require opening a new preview of the new bundle.

## Delivery and acceptance

1. Pure protocol validation plus actual offline renderer: initialize a static
   module-based page, serve frozen assets, click a counter, type literal text,
   scroll/reset, capture PNG and reject stale/duplicate/unsafe messages. Normal
   tests fake the browser; real Chromium/container tests are explicit opt-ins.
2. Verified build-archive source, optional image capability, native process/job
   dispatch, bounded action mailbox/receipts, Stop and conservative recovery.
   Test ZIP/path/symlink escapes, output/queue budgets, interrupted creation and
   unrelated container/process preservation. Never expose the unfinished adapter.
3. Start/action/close API, ordinary parent/child Runs, exclusive/RAM admission,
   artifact adoption/revisions, permission/provenance checks and owned Task Stop.
   HTTP handlers enqueue only. Stale source and action revision tests are required.
4. Agent workspace preview canvas, pointer scaling, literal keyboard/text input,
   scroll/reset/Close, clear blocked-network state, frames/history and responsive
   loading/error/expired states. Show the local CPU execution target.
5. Disposable real agent site: reviewed URL → local model → owned worktree → build
   and checks → source ZIP → interactive offline preview → same-Task follow-up →
   rebuilt preview. Keep original website/checkout unchanged. Verify desktop/phone,
   JS modules/assets, no external traffic/credentials, Stop, restart/timeout and
   cleanup. Record real model/browser checks separately from fake-provider tests.

This extends the [agent-first plan](plans/agent-first-product.md) and existing
[build artifacts](coding-build-artifacts.md), [browser isolation](browser.md) and
[agent workspace](agent-workspace.md). It does not revive IDE expansion or remove
legacy task history before equivalent agent access exists.

## Internal renderer evidence — 2026-10-22

The first protocol/renderer implementation passes 53 normal tests covering typed
inputs, internal-origin/path handling, identity/revision guards, literal text,
duplicate/conflicting receipts and failure without replay. An explicit real
container test passed on the already-installed project Chromium base, with no
model download, GPU, public network or host mount. It loaded JavaScript modules,
clicked a counter, inserted literal script-like text, decoded each PNG, rejected
a duplicate/stale click, blocked POST/private-network requests, reset and removed
its own container. The direct workload test does not prove native/API ownership,
Run recovery, resource admission or UI integration. Those remain unpublished.

Evidence: `data/acceptance/agent-site-preview-20261022/{image.log,real-renderer.log}`.
Full backend/Runner regression and complete integration gates are still required
before this feature is reviewed for merge/deployment. Existing production does
not load these unpublished modules.

## Native lifecycle evidence — 2026-10-22

Native session/action requests, immutable ZIP sourcing, image capability checks,
single-session/action admission, durable receipts and exact process/container
cleanup are implemented. The optional image now requires protocol **2**, including
explicit document-versus-asset requests so SPA navigation cannot fabricate HTML
responses for missing API data. Earlier prototype images are rejected.

Focused normal coverage also includes archive traversal/symlink/duplicate/expansion
bounds, geometry, journal identity/deadlines, native close, unknown create results,
foreign container preservation and the atomic mailbox race found during real QA.
A first native attempt failed because a mailbox scan could see the in-progress
atomic temporary file; only committed requests are now considered. Failed attempts
are preserved under the acceptance directory. A test wait also needed to re-read
a confirmed zero-exit action rather than fail between its last running inspection
and receipt publication.

The final explicit real tests passed (**2**) on protocol 2: actual Native API,
registered session/action process groups, local archive/modules, pointer/text,
receipt replay, stale rejection, reconstructed-manager inspection, cleanup after
killing a proxy while its page was wedged, and closing a second live session.
Repeated inspection of the older action did not close the newer container, and
an unrelated test process survived. Both containers were removed. CPU only; no
production models, credentials or external services were used. Evidence:
`data/acceptance/agent-site-preview-20261022/real-native-protocol2.log`.

Full regression is required before merge. Control-plane permissions, RAM/exclusive
admission, ordinary Run/artifact adoption and UI remain unfinished. No integrated
website preview is advertised by the current production release.

## Integrated workspace increment — awaiting release qualification

The control plane now publishes typed preview, interaction and Close Runs. A
preview has its own operator inspection Task with source-project provenance; it
never joins or stops the coding Task. Immutable preview Runs are excluded from
project *write* admission checks, while all other existing project guards remain.
RAM (1536 MiB) and the single per-Runner preview slot are reserved before native
dispatch. Low-memory waits defer only preview admission. No GPU allocation or
model eviction is requested.

Frames become immutable PNG Artifacts on the preview Run with the exact source
build as their parent. Frame hashes, viewport, revision and interaction ownership
are checked before adoption. Stop and adoption serialize on the same Task. An
uncertain native dispatch or recovery retains reservations until an explicit
Close confirms cleanup. Native admission and Close share a lock and a persistent
cancel barrier, preventing a delayed initial dispatch after a confirmed close.

Successful build cards link to `/preview/<validation-run-id>/<artifact-id>`.
The view offers desktop/phone dimensions, screenshot interaction, literal text
entry, scrolling, reset, session history recovery on reload and Close. Site
JavaScript runs exclusively in the offline container; the authenticated UI
receives images. A lost HTTP response can retry only the same operation receipt,
so it does not repeat an uncertain click. Session and interaction history remain
ordinary inspectable Runs. This is a static build preview, not an internet browser
or a live Node development server; server/API calls and remote assets stay offline.

Setup after qualification:

```bash
docker build -f preview-executor/Dockerfile -t ai-station-site-preview:development .
```

The installed `ai-station-browser:local` base must already be available; preview
setup does not download models. Configure `AI_STATION_SITE_PREVIEW_IMAGE` on the
native Runner and `AI_STATION_SITE_PREVIEW_ENABLED=true` in the control plane.
Both default to unavailable until explicitly configured. Normal startup never
silently replaces an incompatible existing Runner.

Verification so far: the actual worker/native Unix socket/container test passed
pointer interaction, PNG adoption, idempotent replay, Close and released locks.
It uses a disposable registered build, not an unexecuted claim about a new
LLM-generated website. Normal focused coverage includes uncertain dispatch,
recovery reservations, CPU admission, revision identity and Stop. Full regression,
compiled desktop/mobile acceptance and deployment remain required before release.

# Isolated interactive agent website preview

Status: internal offline renderer/protocol implemented and directly real-tested;
owned Runner dispatch, durable Run actions and the agent UI are still pending. Until all lifecycle
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

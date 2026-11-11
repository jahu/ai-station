# Resource-wait SQLite contention repair

## Incident and evidence

After a successful image, the conversation's model reload failed with SQLite
BUSY at BEGIN IMMEDIATE. Its dependent decision and controller then failed.
Two actual reloads had 85 and 134 claims/preparation attempts without native
dispatch while other image work held the required GPUs. A speech preparation
had 220 claims while host RAM was below its declared budget. These are valid
resource waits, not permission to stop active work or lower resource budgets.
No private instructions or media are needed to reproduce the failure.

## Causes and implementation plan

1. GPU-lock rejection in Llama preparation and ordinary media RAM/GPU rejection
   requeue immediately. Existing Task-level deferral primarily covers segmented
   films and some external-memory admission, leaving these ordinary Runs in a
   fast claim/prepare/requeue loop. Add a per-Run eligibility timestamp reused by
   atomic claiming, including CPU-only memory waits. Retain existing Task-scoped
   film deferral; do not delay unrelated children or cancellation actions.
2. The executor exception boundary treats transient SQLite BUSY/LOCKED as a
   workload failure. Preserve the durable claim and inspection/recovery contract
   instead: roll back and leave the executor stack, rather than fail the Run or
   replay its provider/native side effects. The worker's existing database-busy
   backoff/recovery remains authoritative. Other database errors still fail.
3. Clear per-Run deferral only when admitted, preserve worker/account checks and
   explicit resource reservations. Never increase busy timeouts, relax atomic
   claims, stop another workload, or silently spill models to host RAM.

## Verification and rollout

Use temporary SQLite databases, real concurrent writer contention and fake
executors/native calls. Verify waiting Runs are not immediately reclaimed, other
work can proceed, CPU memory waits are gated, Stop remains available, and a BUSY
exception creates no failure or duplicate native dispatch. Retain claim-loss,
permission, cancellation, deadline and recovery regression coverage. Qualify
ordinary model/media admission together before reviewed develop merge.

For worker/executor changes, deploy after active user Runs drain, with an offline
verified backup and unchanged data/transport. A compatible HTTP-only rollout is
qualified separately below. Do not automatically retry the user's failed prompt.
Use neutral disposable QA through normal APIs to verify resource waiting and
continuation. Publication of a patch release is separate from this repair.

## Admission recovery proof

New media preparation commits `media_admission_pending` before admission I/O.
The same transaction that records `dispatch_attempted` removes that marker.
Recovery may requeue only the qualified pre-dispatch phase, with no start/PID
and an expired, unchanged lease; cancellation completes instead. Legacy or
ambiguous native work retains the existing inspection policy. This is not a
general retry of provider/native side effects. A newly published owned stop
prerequisite supplies readiness, so it does not add a redundant timer after
that stop finishes. Existing Task-level admission waits remain compatible.

## Local qualification — 2026-11-06

The reviewed runtime passed coverage of **8,860 unique Python tests**, with 19
explicit opt-in integration skips. This combines the distributed regression,
its recorded remaining cases, and 102 archive cases run sequentially because
their generated ZIP timestamps can change collection identities. No failing
case was waived. Corrected desktop interrupt fixtures passed their complete
54-case family; native storage fixtures passed 23 cases using one stable native
disk observation. These test-only corrections leave application/Runner code
unchanged. Ruff lint/format and the exact application Docker build also passed.

The admission/recovery contract passed real concurrent SQLite-writer tests,
including exactly-once fake native dispatch and a recovery/dispatch race.
Film admission retains its existing Task gate and immediate wakeup; ordinary
media and model loads use their individual backoff. Real neutral deployment
qualification remains the final gate; these tests are not a hardware smoke test.

## HTTP response lifetime follow-up

Live qualification confirmed that the same single model-load Run waited for
occupied GPUs and completed the neutral conversation after the existing image
completed. No user prompt or media was replayed. It also caught a separate long
writer reservation held by the API process, causing readiness and unrelated
requests to time out. Restarting only the owned API released that reservation;
workers and native images were retained and completed normally.

A slow-body ASGI regression reproduces a request retaining BEGIN IMMEDIATE
through response delivery. HTTP Session dependencies now use FastAPI function
scope, including account coordination and explicit administrator inspection.
The session closes after response preparation, before transport. The normal
owner checks and streamed per-batch authorization remain unchanged. Worker
sessions, atomic claims, SQLite settings and native execution are untouched.
Three actual endpoint backpressure cases and the account/API contract subset
passed (40 tests). The final full regression passed **8,863 Python tests**, with
19 explicit opt-in skips, including 102 freshly repeated sequential archive cases.
Ruff lint/format and the exact application image build passed.

## Deployed qualification — 2026-11-06

Both repairs are reviewed and merged into `develop` (PRs #687 and #688). The
resource/worker repair was applied after active work drained, with an offline
verified backup. Actual existing image work and a new neutral local conversation
completed successfully; the same single model-load Run waited for GPU ownership
to release. Only status/resource metadata was observed; private image content
and failed user prompts were neither inspected nor replayed.

The HTTP-only repair was applied to the API with a consistent SQLite online
backup, preserving active work. Complete AST comparison established that all
56 changed application files differ only in function-scoped HTTP dependencies;
the already-qualified worker/scheduler execution logic is unchanged. Those
containers and the native Runner were retained, and scheduling resumed. No
schema, model, driver or transport change was required. Local/LAN delivery,
account protection, schema 0045, integrity and foreign keys passed verification.

The exact deployed image then passed all three blocked-body ASGI cases plus an
ordinary fake-executor API lifecycle, using a disposable database in owned cache
storage. That storage was removed afterward; no production account or file was
used in that test. This qualifies response backpressure inside the actual image,
not a physical slow-network experiment. The live GPU-wait conversation above
is separate real-hardware evidence. Historical failed Runs remain inspectable.

## Decision preparation contention — 2026-11-11

A conversation inferred its text/research intent, then its decision Run was
interrupted with `Lease expired and the owned process is not running`. Worker
logs showed transient SQLite contention; the worker container had neither
restarted nor been OOM-killed. The model had completed the intent inference.

Managed-runtime lookup and provider binding ran before the decision's guarded
persistence/stream loop. A busy `BEGIN IMMEDIATE` there escaped to the worker
slot's generic contention handler, which deliberately preserves a durable claim
instead of blindly re-executing side effects. That abandoned decision later
expired. The lease message describes recovery, not a GPU/model crash.

Preparation now uses the same rollback-aware, deadline/claim/cancellation guard
as decision publication. Binding returns an unstarted asynchronous generator;
the short database transaction is committed before provider I/O. Only failed
DB-only preparation retries. A completed intent, actual completion or dispatched
tool is not replayed, and provider/credential changes remain normal failures.

The original implementation reproduces the failure against a real competing
SQLite writer. The repaired case also verifies an independent lease writer can
commit during streaming. Raw LlamaIndex ReAct tests inject busy/locked failures
after intent and observe one action/reply, while cancellation during binding
backoff dispatches no provider request. Affected backend/runner validation passed
117 tests plus full Ruff/format checks. This evidence uses temporary databases
and fake inference; live-model deployment qualification is recorded separately.

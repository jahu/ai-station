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

Deploy only after active user Runs drain, with an offline verified backup and
unchanged data/transport. Do not automatically retry the user's failed prompt.
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
passed (40 tests). Complete regression and deployed qualification are pending.

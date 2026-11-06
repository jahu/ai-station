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

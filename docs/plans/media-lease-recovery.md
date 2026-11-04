# Owned media supervision after SQLite contention

## Confirmed failure

Two workstation reports (an agent image and a manual video) had the same event
sequence: native dispatch, progress, `recovery.inspection_required` with SQLite
BUSY at `BEGIN IMMEDIATE`, repeated observations of the live owned process, then
`Lease expired and the owned process is not running`. Native journals recorded
exit code zero for both. Expiry was the downstream symptom: a transient database
exception had ended the worker's polling loop before it collected the result.
Recovery kept renewing observation while the process lived, but had no path to
resume media collection after it exited.

SQLite reserves its writer for explicit reads too. The scheduler could leave
reconciliation with such a transaction (including an empty model list) and hold
it across native hardware telemetry. A slow native request then exceeded another
writer's busy timeout. Historical logs establish the lost-supervision sequence;
the exact competing transaction in each historical failure is not recorded.
The scheduler lock lifetime is reproduced independently with a real second writer.

## Correction

- Commit scheduler reconciliation before any native telemetry call. No database
  transaction spans that request.
- Common media polling retries only rolled-back SQLite BUSY/LOCKED persistence
  steps. Keep the original process, permissions, deadline and resource allocation.
  Retry neither native start nor model inference. Other database/validation
  errors retain their normal failure semantics.
- Advance log offsets and incomplete-line parser state only after successful
  persistence. Retried writes cannot skip or duplicate an observed log page.
- Every persistence step rechecks the worker and claim timestamp, status and
  owner-scoped session. A replaced worker cannot publish old observations/results.
- Expired media leases with matching Run/executor native journals yield an
  inspection-only queue handoff. The next claim bypasses preparation, model
  discovery, resource acquisition and dispatch; it inspects/drains that exact
  process and collects its original deterministic output. Preserve existing locks
  until owned exit is confirmed. Unknown identity/exit status and unconfirmed
  cleanup keep the conservative inspection policy.
- Stop during queued handoff is durable and reaches the owned process on resume.
  It must not declare a still-running job canceled or expose a successful artifact.
- Persist owned-exit proof separately from final output validation. Artifact and
  dependent-child publication remain atomic. Missing/invalid output fails once;
  it must not enter an endless inspection loop.

The common contract covers image, video, speech, music, avatar, effects, timeline
and composition adapters. No arbitrary shell, process adoption, new permissions,
new schema, larger lease/busy timeout or inference retry is introduced. Previously
terminal interrupted Runs retain their history; they are not silently re-executed.

## Verification

Use temporary databases and fake/native fixture processes. Required cases include
real SQLite contention during polling, busy log flush and completion commit,
complete ordered logs and one artifact, stale worker claim fencing, image/video
inspection resumption with start forbidden, cancellation during handoff, missing
outputs, unknown native state and existing media/worker/privacy contracts.
Native telemetry must allow a concurrent SQLite writer after reconciliation.
Expensive real inference is unnecessary to reproduce a persistence/lease fault.

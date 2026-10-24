# Yield GPU memory without pinning a prerequisite

Current next branch: `fix/dependent-consumer-eviction`, owned worktree
`.tools/dependent-consumer-eviction`, based on deployed PR #400 (`1522ef6`).
The full platform objective remains active; this is a focused reliability
increment, not a redefinition of platform completion.

## Evidence and requirement

HostMediaExecutor already defers scarce RAM/GPU work and queues owned idle llama.cpp
stops. `evict_idle_models` treats every nonterminal endpoint-bound consumer as
busy. A queued consumer that depends on the very media Run needing those GPUs
cannot make progress, yet prevents that model from yielding its reservation.
The new regression in `test_llama.py` models this valid dependency graph with
the existing fake managed runtime; it must fail on the base source. It does not
prove that every currently exposed media route builds such a graph.

Do not solve this by merely ignoring the future consumer: it retains the stopped
instance endpoint and would fail later. Do not stop an active/runnable unrelated
consumer, touch external services, change its model/preset, or create a speculative
reload that can compete with media or make independent conversations depend on
the media's success.

## Proposed implementation

1. Use bounded actual RunDependency reachability, separate from parentage. Only
   queued consumers that demonstrably wait on the requesting Run are eligible
   to yield. Claimed/preparing/running, runnable queued, approval-waiting and
   unrelated consumers retain the existing protection. Refuse ambiguous or
   oversized graphs rather than widening eviction.
2. Persist a controller-owned deferred-consumer marker binding the exact original
   instance, stable model-file identity, saved preset and prerequisite. Serialize
   marker creation with stop/dependency publication. Never grant additional
   tools or alter source/budget/approval snapshots. The requesting media keeps
   its normal dependency on the owned stop.
3. Restore a future consumer only after its real prerequisites succeed, while it
   is still queued. Reuse `prepare_consumer` and existing durable model-load Runs;
   preserve approved model identity and saved GPU/context/KV selection. Reuse an
   already suitable ready/pending load normally. No speculative load behind the
   media: unrelated new consumers must not inherit a media-cancellation failure.
4. Integrate a bounded deferred refresh with the existing worker. Atomic claiming
   must exclude unresolved marked consumers so another worker cannot race past
   refresh and dispatch the stale endpoint. Under a verified queued/Task guard,
   restore endpoint/dependencies and clear the pending marker atomically. No
   native operation happens in this transaction. No new Run state is needed.
5. A failed/canceled prerequisite must finish the dependent Run through existing
   prerequisite-failure semantics without loading a model. Stop, expired budgets,
   changed model identity and unknown native ownership must never cause a new
   load. Refresh must be crash-safe/idempotent across workers and restarts.
6. Emit structured yield/resume/wait events, retaining the existing resource and
   dependency UI. Add user-facing waiting detail only where the current UI cannot
   explain the actual queued work; do not expose internal marker jargon.

## Required gates

Prove direct and transitive dependencies, unrelated/runnable/active consumers,
external runtime exclusion, exact model/preset retention, multiple consumers,
duplicate refresh, atomic claim exclusion, Stop/expiry before and after yield,
failed prerequisites, unknown native state, and an independent conversation
arriving during media work. Run fake worker stop → media → reload → completion
and verify GPU locks and no duplicate native side effects. Only then run the
complete Python/Runner checks and any affected UI/image/Compose gates, review a
PR to develop, and deploy with a verified database backup.

Current live source remains PR #400. Its proof is
`data/acceptance/agent-report-email-20261024/post-deployment-qualified.json`.
Preserve the live Runner/model, the original Memory WIP (already ported in #319),
all acceptance trees, and pending Whisper-small consent. Do not repeat an old GPU
qualification merely because a historical plan labels it pending.

## Baseline captured

The focused regression failed exactly at the final assertion on develop #400:
ready remained ready instead of queuing an owned stop. No native GPU or live
model operation was executed. Evidence:
`data/acceptance/dependent-consumer-eviction-regression.log`.

Implementation is still pending. In particular, inspect existing read-only Runner
verification performed by `prepare_consumer`/`enqueue_load` before choosing the
refresh transaction boundary: adding network waits while holding a SQLite writer
would regress API responsiveness. Claim exclusion must not leave stopped/failed
or canceled prerequisite graphs permanently hidden from normal failure handling.

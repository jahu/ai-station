# Yield GPU memory without pinning a prerequisite

Owned branch/worktree: `fix/dependent-consumer-eviction`,
`.tools/dependent-consumer-eviction`, based on deployed PR #400 (`1522ef6`).
The full platform goal remains active. This controller reliability increment
adds no schema column, host endpoint, native command or distributed scheduler.

## Reproduced problem

`evict_idle_models` protected every nonterminal endpoint-bound consumer. A queued
consumer depending on the media Run needing those GPUs therefore pinned the
model required to make its own prerequisite progress. The focused base-source
regression failed exactly as `ready` versus expected `stopping`; evidence is
`data/acceptance/dependent-consumer-eviction-regression.log`. This demonstrates a
valid dependency graph, not a claim that every public media route builds it.

Ignoring that consumer alone would leave a stopped-instance endpoint. A
speculative replacement load could compete with media and make an unrelated
conversation inherit media cancellation. Both approaches are avoided.

## Implemented design

Only queued, undispatched consumers with a verified bounded RunDependency path
to the requesting Run can yield. Runnable, unrelated, claimed, preparing,
running, approval-waiting and ambiguous consumers remain protected. Graph
traversal stops at 1024 nodes; external runtimes remain outside ownership.

Model stop and deferred preparation publish together with the ordinary GPU
prerequisite. A `llama_resume_consumer` Run on each consumer's own Task waits for
its original prerequisites and the owned stop. The consumer also depends on
that preparation. Existing atomic claiming therefore prevents stale endpoint
dispatch without modifying worker selection or introducing a refresh loop.

```text
owned stop → media → model preparation → owned model load → queued consumer
```

Preparation is an atomic database-only executor. It freezes model-file identity,
original load/source observation, selected GPUs, fitted context, KV cache and
vision companion; an identity hash binds execution parameters, target, resources
and permissions. It rejects changes and uncertain ownership. It reuses a matching
ready/pending model, or enqueues the exact saved preset through the normal load
service. Model verification, hardware access and native dispatch remain in the
existing load worker. The private previously-fitted option is not an HTTP field;
the native load still checks admission/source/context. No network operation runs
under the preparation Task lock.

A pure preparation cannot persist partial publication: its startup/dependency
changes and success commit together. A lost claim can use existing safe recovery;
uncertain unexpected execution remains inspectable. No external inference or
process action is replayed by preparation recovery.

## Stop, budgets and sharing

Direct consumer Stop cancels its owned pending preparation. Whole-Task Stop
handles children already canceled recursively and reports every targeted ID.
Failed/canceled prerequisites use normal failure propagation without model loads.
The original execution/coding/report deadlines apply before preparing a model.

Newly restored loads check current consumers before native startup and during
startup polling. With no active consumer they cancel through ordinary owned
lifecycle handling. Their short database check serializes with Task/message
publication and reloads ORM identities; no native call holds that writer lock.
A later independent consumer keeps a shared startup alive. Existing independent
loads have no media prerequisite and are not reclassified as restoration work.
A subsequent ordinary Chat can therefore share/reuse a suitable model while
another workflow stops. When a retained shared load belongs to an already stopped
Task, idle-model resource support uses its own ordinary management Task, preserving
the no-new-work-in-a-stopped-Task rule. Automatic stops retain their requesting
Run reference and recheck need before dispatch. Stop is retained if another Task
already depends on it; otherwise abandoned requests never unload the idle model. Completed owned runtimes retain normal idle-cache policy.

## Qualification

Normal tests use temporary databases, fake model runtimes and the actual worker,
lease recovery, dependency and resource services. Focused coverage includes
direct/transitive and cross-Task graphs, multiple consumers, active/runnable
protection, exact large Q8 and vision presets, source/permission changes, Stop,
expiry before/during startup, shared independent Chat, duplicate publication,
bounded graphs and a crash before atomic commit. No GPU inference, external
account or model download has been executed for this increment.

Complete Python/Runner checks, exact frontend-source reuse where unchanged,
Docker/Compose/image binding, full PR review and a backed-up controller rollout
must pass before claiming delivery. The live record remains authoritative:
`data/acceptance/safety-redeploy-20261012/deployment.json`. Preserve root Memory
WIP (already ported in #319), live/proof trees and pending Whisper-small consent.

Focused implementation qualification currently passes 38 new fake-runtime cases,
plus the existing model/Run/Chat-Stop/resource tests. Complete final-head evidence
is collected under `data/acceptance/dependent-consumer-eviction-20261024`. These
checks do not claim a new real GPU mixed-workload smoke test. Native code and
frontend source are unchanged; their previous qualification is reused only after
exact source/asset comparison. The earlier malformed email-preface ordering in
three architecture documents is also corrected without changing their content.

Final reviewed implementation `8465cb0` passed all 3199 collected Python/Runner
cases: 3190 passes and nine explicit opt-in skips, with Ruff lint/format.
The exact unchanged frontend reuses the qualified 716-test UI/build gate from
PR #400 after tracked-source comparison. Docker backend/compiled assets and
normal/dev/private-LAN Compose configurations pass exact binding. Full diff
self-review found no unresolved material issue. Merge and deployment status
remain governed by the live acceptance record, not this pre-deployment gate.

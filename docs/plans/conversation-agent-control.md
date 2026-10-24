# Operate the conversation's agent

Work accepts explicit Polish/English commands to run the last agent created in
this conversation, pause its future executions, or stop its current Task. Chat
requires switching to Work. Quoted, negated or compound instructions do not
implicitly grant control. No model selects an agent ID or modifies permissions.

Resolve the latest visible creation result, verify its successful factory/quick
creation origin, and freeze source message/Run, current request, target definition
revision and (for Stop) the current Task. Reject missing/changed origins and never
fall back to an older agent. Recheck authority in the worker under database
serialization. Read-only runtime preparation releases SQLite before Runner I/O;
a controller-only before-publication hook rechecks Stop, source and the exact
saved definition before atomically publishing the workflow and control result. Disabled definitions require the existing review/activation UI.
Run reuses launch_agent, including approval, source, dependency and email consent
checks. Pause reuses consent revocation and disables future scheduling without
canceling current work. Stop uses existing Task-wide cancellation and never stops
a newer Task that appeared after Send. Resume/enable still needs explicit review.

The short controller Task and agent workflow are distinct, linked with immutable
provenance metadata. Background work has no conversation ownership, so the main
composer remains usable. Queue publication and controller success commit
atomically; turn receipts prevent repeated sends. Conservative recovery never
blindly repeats a committed side effect. All controls emit structured events.

Show the exact linked Run and its current status beside the existing live agent
card/results. Preserve old messages, source snapshots, request hashes, schedules,
permissions and ordinary agent APIs. No schema/native protocol/model change.

Verify actual worker dispatch, disabled/busy handling, origin/version/current-text
and permission tampering, turn replay, pause consent revocation, cancellation
before dispatch, exact-Task Stop, concurrent scheduler behavior and an unblocked
conversation. Qualify compiled desktop/mobile source → control → result paths
with isolated data and fake inference; report that separately from real models.

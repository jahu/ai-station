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

## Qualification scope

PR #417 builds on #416 with no schema/native/model change. Normal verification
includes the complete backend/Runner suite and all 47 controller tests, including
source/revision/permission tampering, replay, approval, one-shot schedules,
concurrent metadata writing, Stop during preparation and exact-Task cancellation.
The final composer-default/compact-receipt correction has a complete affected
controller-module recheck; all other baseline backend/Runner/test files are
byte-identical. Exact heads and successful coverage remain in the gate reports.

Compiled application-image desktop (1440px) and mobile viewport (390px) checks
exercise ten actual Send/worker controls, ordinary approval, pause without cancel,
Stop without disabling schedules, two completed report/artifact workflows and
reload. Model listing and report inference are injected. Controls call no model;
no new GPU/media generation or physical-phone qualification is claimed. A control
receipt does not repeat the full agent card; the existing source card retains live
results and the receipt links the specific execution and agent workspace.

Evidence: `data/acceptance/conversation-agent-control-20261024`. Earlier harness
failures and the deliberately interrupted superseded suite are retained and are
not passing gates. Use the post-deployment qualification and shared deployment
record to establish the actual live image. Whole-platform completion remains open.

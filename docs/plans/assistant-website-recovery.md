# Website-building conversation: failure analysis and repair

Incident: 2026-11-07, request to create a new version of a supplied public website.
Private conversation, full source captures, Run IDs and logs remain under ignored
`data/acceptance/assistant-website-recovery-20261107/`, not in public fixtures.
The original failed conversation and partial response must remain inspectable.

## Confirmed causes

1. The first independently inferred intent requested only a text redesign
   proposal. The model therefore chose `chat.reply` after real page/artifact reads,
   rather than the already available owned-project coding tool. Creating a working
   deliverable and explaining a design must be distinguished semantically by the
   planner; do not introduce URL, domain, language or keyword routing hotfixes.
2. The streaming Chat Run stopped on transient SQLite contention. Worker logs
   contain a failed lease renewal and the worker's SQLite-busy escape path;
   persisted deltas stopped before the lease expired. Recovery subsequently
   interrupted the Run because no native per-Run process exists for in-worker
   HTTP inference. Unlike controller inference, Chat has no retry/fencing wrapper
   for its cancellation checks and delivery commits. Its delivery buffer is
   cleared *before* persistence, so a failed write also discards received tokens.
   The exact original lock holder cannot be reconstructed from these logs. Do
   not claim the database's single-writer architecture or all contention is fixed.
3. The next ReAct decision crashes in `bounded_context`: canonical observation
   errors are dictionaries containing capability/status/error, but the excerpt
   loop slices each dictionary as if it were text. `KeyError(slice(...))` then
   masks the original interruption and terminates the controller.

## Implementation

- Preserve structured error observations while bounding their text fields;
  support existing text errors, retain failed status/evidence and leave canonical
  stored observations unchanged. Exercise the real ReAct bridge after failure.
- Retry only SQLite BUSY/LOCKED database checkpoints while keeping the existing
  single provider stream open. Keep delivery buffers until commit. Fence every
  update by the original worker/claim and nonterminal status, so recovery or a
  newer claim cannot be overwritten. Cancellation and failure retain durable
  partial output and close inference. Do not replay a tool, HTTP generation or
  uncertain side effect; do not change SQLite isolation, busy timeout or leases.
- Clarify the independent planning/tool instructions: requested working software,
  websites and new implementations require actual project/code/file outcomes;
  explanations, reviews and design proposals remain text. Advertise existing
  tool affordances to intent inference, without granting additional permissions.
  Existing owned project/worktree, Auto coding-model/context admission,
  validation/output-artifact and preview contracts perform the implementation.
- Keep the original failed records. Qualify a new ordinary request separately;
  do not edit historical messages or turn a partial proposal into a success.

## Verification and rollout

Use disposable databases, fake inference/public pages and existing fake Runner
boundaries for normal tests. Regress structured tool failure → next decision;
transient SQLite contention during both silent streaming and buffered delivery;
exactly-once provider invocation/delta ordering; cancellation, expired/lost claim,
provider error, account isolation and pending non-text outcomes. Validate planner
prompt contracts with build-versus-explain examples, never model-free word rules.
Run backend/runner checks, broader relevant suites and the application image
build. Review the full feature PR and local results before merging to develop.
Back up live SQLite consistently, drain owned active Runs, deploy only AI Station
services, and verify a real local execution in a separate account against the
same public-site task. Report actual resulting files/validation/preview, rather
than declaring success from a parent Run or a model's prose. No original site,
external repository, drivers or user model files are modified.

## Initial regression evidence

The new real-SQLite writer test fails against the preceding ChatExecutor with
`OperationalError: database is locked`; on the candidate both immediate and
silent-provider variants succeed with exactly one provider invocation and
ordered, nonduplicated deltas. Interrupted/replaced claims retain their existing
state and saved partial answer; the stale stream closes without writing.
The structured-error ReAct bridge test and durable failed-reply workflow pass;
ordinary Chat, reasoning, provider failure, Stop and prior controller regressions
passed in the initial focused runs (39, 20 and 53 cases respectively). These
are fake-provider/disposable-database checks, not real website qualification.
The complete backend/Runner regression and final image/rollout remain pending.

## Required website output

The existing generic new-project path does not require a website build archive by
default. Add an optional typed `static_site` output expectation to the existing
local new-project/build scope and ReAct tool arguments. Selecting it requires
automatic validation and uses the existing one-attempt local validation-repair
policy for this new owned website scope. It remains local and adds no dependency-installation or
publication authority. Ordinary software scopes omit this field, preserving
legacy request serialization. Freeze the expectation and offline build guidance
on the existing coding preparation; existing proposal/validation propagation
then requires a new, nonempty `dist/index.html` in its verified archive before
success. This reuses the already-tested website validation/preview contract and
is selected semantically by the model, without domain/keyword routing.

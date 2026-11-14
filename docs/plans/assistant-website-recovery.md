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
The broad backend/Runner sweep found one cleanup regression after 8,881 passing
cases (19 opt-in skips): a nontransient failed delta write was attempted again
from `finally`. The unchanged existing regression now passes after preventing
that cleanup replay; the full affected Chat family passes (41 cases). Final
controller/project families pass 279 cases (5 opt-in skips). The native Runner
suite passes 2,474 cases (8 opt-in skips), with the 20 archive cases checked
separately. Ruff/format and the production image build pass. These overlapping
suites are not additive unique-test counts or real-model qualification.

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

## Additional real-run finding

The first separate local-model qualification correctly read the supplied source,
inferred both project and implemented-code outcomes, created an owned Git project
and worktree, and selected the existing Auto coding model. However, native coding
stopped at its old 2 MiB *wire* limit before any proposal was applied: token SSE
frames repeat substantial metadata, so this limit is not a content budget.
The next controller decision processed that structured failure successfully,
without the original slice crash. This attempt is preserved as a failed coding
attempt, not reported as a completed website.

Bound stream transport separately (16 MiB), while retaining a 2 MiB UTF-8 content
and per-event bound, confirmed terminal completion, existing output-token limits,
timeouts and typed local-only execution. A metadata-heavy stream with a small
valid JSON proposal reproduces the rejection on the preceding code and passes on
the candidate. Oversized content, individual frames and total wire traffic are
still rejected. This requires the reviewed native parser update as well as the
control-plane image; it changes no installed model or external runtime.

The next qualification passed that transport threshold, but its format-correction
completion reached the separate 8,192 output-token limit. This was not a failure
to allocate the existing large coding context. No incomplete proposal was applied.
The typed single-message coding bridge now allows up to 16,384 output tokens and
native proposal generation uses that budget, including small-input proposals via
the coding route. Ordinary Chat remains limited to 8,192. Source/path/file-size,
two-attempt formatting, timeout, JSON-only and no-model-tools contracts remain
unchanged. Invalid file-object diagnostics name the permitted fields instead of
only saying "Invalid file replacement". Boundary tests cover both bridges and
reject coding requests beyond the new maximum. The test workflow was stopped
through its normal Task API before upgrading the native parser; old attempts and
their owned projects remain inspectable.

Subsequent real qualification exposed two model-protocol weaknesses. A model
selected eleven files; exploration previously aborted instead of returning its
validation error. Invalid count/duplicates/non-string selections now receive at
most two corrections within the existing request budget, without executing the
selection. Hidden/credential/symlink/path violations still fail immediately.
The editor is explicitly text-only; it does not invent binary media assets.

Finally, repeated file objects still violated the required proposal shape despite
format correction. Owned llama.cpp proposal calls now carry only the bounded
selected-path list to the typed coding bridge. The Runner constructs its fixed
JSON schema (summary/files; whole content, unique replacements or deletion) and
constrains model decoding to those paths and fields. No caller supplies an
arbitrary schema. This is an adapter-level output contract, not authority: the
existing parser, UTF-8 byte bounds, duplicate-path checks, exact-match edits,
stale snapshots and filesystem checks remain mandatory before any write.
Ordinary Chat and configured-provider legacy requests omit this option.
Owned-model exploration also uses a fixed schema for its declared read-only
operations and one-to-ten-path finish action. It cannot spend the small operation
budget emitting a whole source proposal in place of a tool request. The existing
tool implementation still validates paths, public URLs and its finite budget.

The constrained proposal then produced real source, but put its manifest inside
`src/`; root-manifest discovery therefore found no build command. A corrective
proposal cannot add an unselected root manifest without violating its frozen file
scope. New owned `static_site` tasks now freeze Station-supplied, literal Node
test/build argv: validate ordinary nonlinked files and a nonempty `src/index.html`,
then copy `src/` to the verified `dist/` archive offline. No generated manifest,
dependency installation or model-authored build wiring is needed. Existing
projects, other software contracts and their configured commands are unchanged.
The fixed commands are tested with actual Node on disposable source, including
missing/empty entry points, root/child symlinks and hard links.

Controller observations also reuse the existing canonical superseded-step
projection after bounded validation repair. A successful checked replacement
fulfills its output; a failed replacement remains a failure. The original failed
validation stays persisted and appears as recovered evidence, instead of
incorrectly poisoning a later successful build. Both cases are tested with real
disposable native validation/archive jobs and fake model changes.

An independent attempt selected the empty-project tool. Its typed short name was
only forwarded *after* legacy enqueue validation, which instead tried to validate
the long tool instruction as a project name. The adapter now passes the validated
name as that legacy name-only request; the root retains the full durable arguments.
An API/worker/native-project regression verifies the real handoff with an
instruction longer than 200 characters. When frozen pending outcomes require one
new project plus implementation and no existing coding scope is available,
affordances expose the composed build tool rather than an empty workspace.
Multiple-project chains and existing-project coding retain their applicable tools.
This uses typed requested results and real tool capabilities, never prompt words.

The ordinary public-site request then completed all three tool steps, produced a
verified six-file offline site, and passed desktop/mobile native rendering with
zero blocked/missing external assets. The generated page's cookie control worked.
Its final model response nevertheless had invalid terminal syntax and exhausted
the two corrections, causing an unnecessary clarification after completed work.
That fallback now finishes with authoritative successful evidence only when all
independently frozen outcomes are fulfilled. Missing, failed, interrupted or
undeclared outcomes could not authorize completion. The later
[model-aware action repair](model-aware-orchestrator-actions.md) tightened this
technical-failure case to a typed planner error, preserving completed results
without pretending that an internal contract error needs user clarification.
Genuinely missing user choices still use the explicit `ask_user` operation.
Both the complete and incomplete cases and the durable API/worker flow are
regressed. The earlier attempt and its actual files remain unchanged.

Content inspection found a further provenance bug after a successful retry: the
planner's smaller implementation notes explicitly requested generic sample news
and placeholder contact details, dropping the source URL. The adapter forwarded
only those notes as the coding task, so native exploration lost the real source
despite the earlier successful public-page read (whose full text contained the
contact details). A technically valid prototype was therefore not a faithful
rebuild of the user's requested source.

The NEW static-site handoff now binds the original user request and bounded
canonical successful page observations to the code task. Planner notes remain
implementation suggestions, not authority to drop requirements or invent facts.
Source excerpts preserve both heading and footer when bounded, remain untrusted
data, and grant no extra permissions. Failed reads are not promoted to evidence.
Explicitly requested examples/placeholders remain supported. Other software and
existing-project coding handoffs retain their previous request shape.

## Final qualification

The exact original public-site request was executed again through the normal
authenticated conversation API on the deployed candidate. All three tool steps
(page read, captured-reference read, owned project/code) succeeded on that run's
first coding attempt. The verified ZIP contains ten real HTML/CSS/JS/SVG files,
with no missing assets or runtime network dependencies. The actual source name,
address, postcode, telephone and news were retained; the placeholder address from
the preceding attempt is absent. Native desktop/mobile previews rendered with
zero blocked requests and accepted interaction. The Chat UI exposes the ready
receipt and real preview link without the original error banners. A separate real
local Chat smoke matched its durable message exactly to streamed delta events.
Coding admission recorded a 129,280-token context on one dynamically selected GPU.

Local verification includes the broad sweep (8,872 passing cases and 19 explicit
opt-in skips before updating two old assertions for the intentional 16K coding
endpoint/budget), the entire corrected Projects family (115 pass, 5 skips), final
assistant/Chat/provenance cases (339 pass), native Runner cases (2,478 pass,
8 skips), binary-fixture/archive cases (67 pass) and six actual Node copy/check
cases. Counts overlap. Timestamp-dependent binary parameter IDs were run
serially rather than weakening their assertions for parallel collection.
Ruff/format, frontend lint/typecheck/build, relevant UI tests and the production
image build passed; existing frontend warnings remain unchanged.

Phone inspection also caught a new presentation issue: the fixed inline Node
program made the validation panel very tall. Long recorded commands now default
to a compact, keyboard-accessible disclosure; the exact argv remains available
for inspection. Short commands retain their existing presentation. This changes
display only, not command execution or audit records.

Each local rollout drained owned work, took a consistent private SQLite backup,
preserved all preexisting relational records and retained the same settings,
authenticated local/LAN listeners and schema 0045. Native updates were limited to
the reviewed owned coding adapter. Original failed conversations and all
qualification attempts remain inspectable. No live source website, external
checkout, model file, independent image script, driver or release branch changed.

Final authenticated browser checks at desktop and phone widths confirmed that
long commands start collapsed, expand to the exact saved argv, and collapse
again; the completed receipt and artifact-preview link remain available.
The generated site remains a proposal in the existing coding review flow, not
a published production site. Rendering/build checks do not certify its design
or every interaction: manual inspection recorded a clipped SVG wordmark and
a mobile-menu positioning issue in that generated proposal. No sample-specific
CSS patch was applied, and automatic publication/commit approval was not added.
